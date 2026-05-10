"""SSE activity-stream endpoints.

Two routes:

  * `POST /api/v1/activity/stream/ticket` — authed via the normal
    Bearer token. Returns a one-shot ticket UUID + TTL. The frontend
    uses this because EventSource can't carry custom headers
    cleanly.

  * `GET /api/v1/activity/stream?ticket=<uuid>&project_id=<uuid>` —
    SSE endpoint. Redeems the ticket, opens the per-(org, project)
    pub/sub subscription, streams events. Heartbeats every 15s keep
    the connection alive through proxies that drop idle sockets.

Why GET (not POST) for the stream itself: EventSource only supports
GET, and SSE is a one-way server-to-client protocol. The query-string
ticket carries the auth.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

if TYPE_CHECKING:
    from arq import ArqRedis
from fastapi.responses import StreamingResponse

from core.envelope import ok
from middleware.auth import AuthContext, require_auth
from services.activity_stream import (
    HEARTBEAT_INTERVAL_SECONDS,
    TICKET_TTL_SECONDS,
    _redis_or_none,
    mint_ticket,
    redeem_ticket,
    subscribe_activity,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


# ---------- Ticket mint ----------


@router.post("/stream/ticket", status_code=201)
async def mint_stream_ticket(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: Annotated[UUID | None, Query()] = None,
) -> dict[str, Any]:
    """Mint a one-shot ticket bound to the caller's (user, org,
    project). Returns 503 when Redis is unavailable so the frontend
    can fall back to polling instead of silently breaking.
    """
    redis = await _redis_or_none()
    ticket = await mint_ticket(
        redis,
        user_id=auth.user_id,
        organization_id=auth.organization_id,
        project_id=project_id,
    )
    if ticket is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "activity_stream_unavailable: Redis required for SSE",
        )
    return ok({"ticket": ticket, "expires_in": TICKET_TTL_SECONDS})


# ---------- SSE stream ----------


@router.get("/stream")
async def stream_activity(
    ticket: Annotated[str, Query()],
    project_id: Annotated[UUID | None, Query()] = None,
) -> StreamingResponse:
    """Server-sent events for the activity feed. Redeems `ticket`
    (one-shot, 30s TTL) to authenticate without a Bearer header.

    The redemption verifies that `project_id` (if provided) matches
    the ticket's bound project. A mismatch returns 401 — partners
    minting a project-A ticket can't pivot to project-B by mutating
    the URL.

    Streams Server-Sent Events: each event is `data: {json}\\n\\n`.
    A `: heartbeat\\n\\n` comment frame fires every 15s to keep the
    connection alive through idle-timeout proxies.
    """
    redis = await _redis_or_none()
    bound = await redeem_ticket(redis, ticket) if redis is not None else None
    if bound is None:
        # 401 — ticket invalid, expired, or already redeemed. The
        # frontend's onerror handler should drop back to polling.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_or_expired_ticket",
        )

    bound_project = bound.get("project_id")
    requested_project = str(project_id) if project_id else None
    if bound_project != requested_project:
        # Pivot attempt — ticket was minted for project A but the
        # connection asks for project B. Reject.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "ticket_project_mismatch",
        )

    organization_id = UUID(bound["organization_id"])
    return StreamingResponse(
        _event_stream(redis, organization_id, project_id),
        media_type="text/event-stream",
        headers={
            # Tell intermediaries not to buffer SSE — without this an
            # nginx-style proxy can withhold events for minutes.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            # Connection: keep-alive is implicit in HTTP/1.1, but
            # being explicit stops broken proxies from closing the
            # socket.
            "Connection": "keep-alive",
        },
    )


# ---------- Stream generator ----------


async def _event_stream(
    redis: ArqRedis | None,
    organization_id: UUID,
    project_id: UUID | None,
) -> AsyncIterator[bytes]:
    """Yield SSE-formatted bytes. Interleaves real pub/sub events
    with periodic heartbeat comments so the connection survives
    idle-timeout proxies.

    Cancellation: when the client disconnects, asyncio cancels this
    coroutine. The pub/sub cleanup happens in `subscribe_activity`'s
    `finally` block.
    """
    # Initial "connected" event lets the frontend know the channel
    # is live before the first real event arrives. EventSource fires
    # `onopen` on the response itself; this is belt-and-suspenders
    # for clients that want to render a "live" indicator.
    yield b"event: ready\ndata: {}\n\n"

    last_heartbeat = asyncio.get_event_loop().time()

    try:
        async for event in subscribe_activity(
            redis,
            organization_id=organization_id,
            project_id=project_id,
        ):
            now = asyncio.get_event_loop().time()
            # Heartbeat if we've been idle. The sentinel events from
            # `subscribe_activity` come every ~1s, so this triggers
            # on the first sentinel after 15s of no real events.
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                yield b": heartbeat\n\n"
                last_heartbeat = now
            if event.get("_sentinel"):
                continue
            payload = json.dumps(event, default=str).encode("utf-8")
            yield b"event: activity\ndata: " + payload + b"\n\n"
            last_heartbeat = now
    except asyncio.CancelledError:
        # Client disconnect — silent return is correct.
        return
