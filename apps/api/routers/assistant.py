"""AI assistant: project-scoped chat backed by every module's roll-up.

Endpoints:
  * POST /api/v1/assistant/projects/{project_id}/ask
      Append a question to a thread (auto-creates one if `thread_id` is
      omitted). Returns the assistant's answer + the thread_id to round-
      trip on follow-ups.

  * GET /api/v1/assistant/projects/{project_id}/threads
      Sidebar list — the caller's recent threads for this project.

  * GET /api/v1/assistant/threads/{thread_id}
      Full transcript: thread metadata + every message in chronological
      order. Cross-tenant / cross-user threads are 404'd, not 403, so
      we don't leak existence across organisations.

  * DELETE /api/v1/assistant/threads/{thread_id}
      Delete the thread (cascade to messages). Idempotent.

RBAC posture (the branch's named feature):

  * `/ask` and `/ask/stream` are gated at `Role.MEMBER` and above.
    Each call invokes the LLM, which costs the org real money — we
    don't want viewers (the role given to clients, auditors, and
    contractor liaisons) burning compute against the org's cap. A
    viewer hitting either endpoint gets a structured 403 with a
    plain-language explanation.

  * The READ endpoints (list threads, get transcript, delete thread)
    keep `require_auth` only. They're scoped to `auth.user_id` so a
    viewer who once had member access and got demoted can still see
    their own conversation history (low-stakes read of their own
    data). DELETE on a viewer's own thread is also permitted —
    cleaning up your own past conversations is not a cost-bearing
    operation.

  * Cross-tenant / cross-user threads return 404, NOT 403. Hiding
    existence across orgs is the load-bearing privacy contract; a
    403 would leak that the thread exists somewhere.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role
from models.assistant import AssistantMessage, AssistantThread
from schemas.assistant import (
    AskRequest,
    AssistantResponse,
    ThreadDetail,
    ThreadMessage,
    ThreadSummary,
)
from services.assistant import ask as assistant_ask
from services.assistant import ask_stream as assistant_ask_stream

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


# ---------- Ask ----------


@router.post("/projects/{project_id}/ask")
async def ask_about_project(
    project_id: UUID,
    payload: AskRequest,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.MEMBER))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Answer a natural-language question about one of the caller's projects.

    Threads:
      * Pass `thread_id` in the body to append to an existing conversation.
      * Omit it to start a fresh thread (auto-titled from the question).

    A 404 is returned for cross-tenant project IDs so the caller doesn't
    leak whether a project exists in another org.

    Role gate: `Role.MEMBER` and above. Viewers (clients, auditors,
    contractor liaisons) can't invoke this — each call hits the LLM
    and costs the org real money, and viewer-tier accounts shouldn't
    have spend authority.
    """
    response: AssistantResponse = await assistant_ask(
        db,
        organization_id=auth.organization_id,
        project_id=project_id,
        user_id=auth.user_id,
        request=payload,
    )

    if response.answer == "Project not found.":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    return ok(response.model_dump(mode="json"))


# ---------- Ask (streaming variant) ----------


@router.post("/projects/{project_id}/ask/stream")
async def ask_about_project_stream(
    project_id: UUID,
    payload: AskRequest,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.MEMBER))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """SSE streaming version of `/ask`. Frame format:

      event: meta  → `{"thread_id": "..."}` (always first)
      event: token → `{"text": "..."}` (zero or more)
      event: done  → `{"sources": [...], "context_token_estimate": N}` (last)
      event: error → `{"message": "..."}` (replaces `done` on failure)

    The browser consumes this via `EventSource` (or fetch + ReadableStream
    when the request body needs to be POSTed). Cross-tenant project IDs
    are signaled in-band via the first frame being `event: error` rather
    than via a 4xx status — by the time the stream is open, the response
    headers are already 200, so HTTP-level errors aren't visible client-
    side.

    Role gate: same as `/ask` — `Role.MEMBER` and above. The 403 fires
    BEFORE the StreamingResponse is constructed, so a viewer hits a
    standard 4xx; the in-band error frame mechanism is only for
    post-stream-open errors (cross-tenant project, DB blip mid-LLM).
    """
    from fastapi.responses import StreamingResponse

    generator = assistant_ask_stream(
        db,
        organization_id=auth.organization_id,
        project_id=project_id,
        user_id=auth.user_id,
        request=payload,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        # Disable any reverse-proxy buffering so frames flush in real time.
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------- Threads (sidebar list) ----------


@router.get("/projects/{project_id}/threads")
async def list_threads(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=30, ge=1, le=100),
):
    """Recent threads for the calling user on this project, ordered by
    `last_message_at DESC` so the most recently active conversation is
    on top."""
    rows = (
        (
            await db.execute(
                select(AssistantThread)
                .where(
                    AssistantThread.organization_id == auth.organization_id,
                    AssistantThread.project_id == project_id,
                    AssistantThread.user_id == auth.user_id,
                )
                .order_by(AssistantThread.last_message_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return ok([ThreadSummary.model_validate(r).model_dump(mode="json") for r in rows])


# ---------- Thread detail ----------


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Full thread transcript. Cross-tenant or cross-user → 404 (existence
    is hidden across orgs)."""
    thread = (
        await db.execute(
            select(AssistantThread).where(
                AssistantThread.id == thread_id,
                AssistantThread.organization_id == auth.organization_id,
                AssistantThread.user_id == auth.user_id,
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")

    messages = (
        (
            await db.execute(
                select(AssistantMessage)
                .where(AssistantMessage.thread_id == thread.id)
                .order_by(AssistantMessage.created_at)
            )
        )
        .scalars()
        .all()
    )

    detail = ThreadDetail.model_validate(thread)
    detail.messages = [ThreadMessage.model_validate(m) for m in messages]
    return ok(detail.model_dump(mode="json"))


# ---------- Delete thread ----------


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Idempotent delete — non-existent threads return 204."""
    thread = (
        await db.execute(
            select(AssistantThread).where(
                AssistantThread.id == thread_id,
                AssistantThread.organization_id == auth.organization_id,
                AssistantThread.user_id == auth.user_id,
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        return None
    await db.delete(thread)
    await db.commit()
    return None
