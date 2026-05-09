"""Real-time activity-stream service.

The activity feed used to poll every 30s. Modern UX expectation is push:
"approval landed → row appears in <500ms." This module provides:

  * **Ticket auth.** SSE connections can't carry custom headers
    cleanly across all proxies, so the frontend POSTs (with its
    normal Bearer auth) to mint a one-shot ticket, then opens the
    EventSource with `?ticket=<uuid>`. The ticket lives in Redis
    with a 30s TTL and a GETDEL redeem — replay is rejected.

  * **Per-(org, project) pub/sub channel.** When `services.audit.record`
    appends an event, it also `PUBLISH`es a compact payload to
    `aec:activity:<org_id>:<project_id>`. SSE handlers `SUBSCRIBE` to
    that channel and stream the payloads as `data: {...}\n\n` frames.

  * **Heartbeats.** Every 15s, the handler sends a `: ping\n\n`
    comment frame to keep the connection alive through proxies that
    drop idle sockets.

Why Redis pub/sub (not Postgres LISTEN/NOTIFY): we already have Redis
for arq + rate limiting; adding LISTEN/NOTIFY pulls every API replica
into a postgres connection per active stream, and asyncpg's LISTEN
support has historically been fragile. Redis pub/sub is fan-out at
the broker, not the DB.

Redis-less dev: `_redis_or_none()` returns None if Redis isn't
configured. Callers handle None gracefully — the publish becomes a
no-op, the subscribe yields nothing. Tests can stub the redis pool
to avoid spinning up a real instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# Ticket TTL — the frontend mints, then connects within ~50ms in the
# happy path, but a slow CDN edge can stretch that. 30s gives plenty
# of headroom while still being short enough that a leaked ticket
# can't be hoarded for replay attacks.
TICKET_TTL_SECONDS = 30


# Heartbeat cadence. SSE comment frames (`: text\n\n`) are ignored by
# the EventSource API but keep the TCP connection warm. 15s is the
# sweet spot — most LBs idle-time-out at 60s, so a beat every 15s
# leaves ~3 chances to keep the link alive before disconnect.
HEARTBEAT_INTERVAL_SECONDS = 15


# Redis key prefix for tickets. Namespaced so a flush-all in dev
# doesn't accidentally nuke arq jobs or rate-limit buckets.
_TICKET_KEY_PREFIX = "aec:sse:ticket:"


# Pub/sub channel name. `<org>:<project>` granularity keeps the
# fan-out per-project; a customer with 50 projects only sees events
# for the project they have open. Org-wide subscribers can match the
# pattern `aec:activity:<org>:*`.
def _channel_name(organization_id: UUID, project_id: UUID | None) -> str:
    return f"aec:activity:{organization_id}:{project_id or 'org'}"


# ---------- Ticket mint / redeem ----------


async def mint_ticket(
    redis: Any,
    *,
    user_id: UUID,
    organization_id: UUID,
    project_id: UUID | None,
) -> str | None:
    """Mint a one-shot ticket bound to (user, org, project).

    Returns the ticket id (UUID4 hex string) on success, None when
    Redis is unavailable. The caller should 503 in the None case so
    the frontend can fall back to polling.

    Stores the bound principals as JSON under `aec:sse:ticket:<uuid>`
    with a 30s TTL. The redeem path uses GETDEL for one-shot
    semantics.
    """
    if redis is None:
        return None
    ticket = uuid4().hex
    payload = json.dumps(
        {
            "user_id": str(user_id),
            "organization_id": str(organization_id),
            "project_id": str(project_id) if project_id else None,
        }
    )
    try:
        await redis.set(
            f"{_TICKET_KEY_PREFIX}{ticket}",
            payload,
            ex=TICKET_TTL_SECONDS,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("activity_stream.mint_ticket failed (%s)", exc)
        return None
    return ticket


async def redeem_ticket(redis: Any, ticket: str) -> dict[str, Any] | None:
    """Redeem a ticket — atomic GETDEL. Returns the bound principals
    dict on success, None if the ticket doesn't exist (replay or
    expiry).

    The atomic GETDEL is the one-shot enforcement: a leaked ticket
    can be replayed within 30s, but only by the first connection that
    races the legitimate one. Frontend code should never re-use a
    ticket — the server enforces this.
    """
    if redis is None:
        return None
    key = f"{_TICKET_KEY_PREFIX}{ticket}"
    try:
        # Redis 6.2+ has GETDEL; fall back to GET+DEL pipeline for
        # older versions. Both branches are atomic enough for our
        # threat model (a 30s replay window is the upper bound).
        if hasattr(redis, "getdel"):
            raw = await redis.getdel(key)
        else:
            pipe = redis.pipeline()
            pipe.get(key)
            pipe.delete(key)
            raw, _ = await pipe.execute()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("activity_stream.redeem_ticket failed (%s)", exc)
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("activity_stream.redeem_ticket: malformed payload, dropping")
        return None


# ---------- Publish ----------


async def publish_activity(
    redis: Any,
    *,
    organization_id: UUID,
    project_id: UUID | None,
    event: dict[str, Any],
) -> None:
    """Publish one activity event. Best-effort — Redis hiccups must
    NOT propagate to the audit transaction. Called from
    `services.audit.record` after the audit row is added (still
    pre-commit; the publish is fire-and-forget within the same
    request scope).

    The payload is JSON-encoded with `default=str` so UUIDs /
    datetimes round-trip cleanly. Subscribers parse and re-render.
    """
    if redis is None:
        return
    try:
        await redis.publish(
            _channel_name(organization_id, project_id),
            json.dumps(event, default=str),
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "activity_stream.publish_activity failed (%s); event dropped",
            exc,
        )


# ---------- Subscribe ----------


async def subscribe_activity(
    redis: Any,
    *,
    organization_id: UUID,
    project_id: UUID | None,
) -> AsyncIterator[dict[str, Any]]:
    """Subscribe to the channel and yield decoded events.

    Returns an async iterator the SSE handler awaits in a loop. The
    `pubsub.get_message(timeout=1.0)` shape lets the SSE handler
    interleave heartbeats with real events without blocking on either.

    `arq.connections.create_pool` returns an `aioredis` pool that
    exposes `.pubsub()` directly; the implementation below assumes
    that interface.
    """
    if redis is None:
        return
    channel = _channel_name(organization_id, project_id)
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(channel)
        while True:
            # 1.0s timeout = ~1Hz idle check, batches into the
            # heartbeat cadence cleanly.
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                # Yield a sentinel so the caller can check for
                # cancellation / send a heartbeat.
                yield {"_sentinel": "tick"}
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            if not data:
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                logger.warning("activity_stream.subscribe_activity: malformed message, skipping")
                continue
    except asyncio.CancelledError:
        # Client disconnected — propagate so the caller can clean up.
        raise
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        except Exception:  # pragma: no cover — defensive
            pass


# ---------- Pool helper ----------


async def _redis_or_none():
    """Pull the arq Redis pool lazily. Mirrors the same shape used by
    `middleware.api_key_auth._get_redis` so a no-Redis dev env doesn't
    fail to boot."""
    try:
        from arq.connections import RedisSettings, create_pool

        from core.config import get_settings

        settings = get_settings()
        return await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception as exc:  # pragma: no cover — dev path
        logger.warning(
            "activity_stream: Redis unavailable (%s); SSE disabled",
            exc,
        )
        return None
