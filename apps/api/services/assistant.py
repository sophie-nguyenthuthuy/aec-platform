"""Cross-module AI assistant.

Given a project + a natural-language question, builds a structured
context blob from every module's roll-up + the last 7 days of activity,
sends it to Claude as a system prompt, and returns the answer + the
list of module sources cited.

Design notes:
  * **Stateless**: the assistant owns no conversation memory. The client
    replays prior turns on each request. Keeps the server simple, lets
    the client reset / branch threads cheaply.
  * **No tool use yet**: v1 stuffs *all* the context up front. Tool-use
    (let the model query specific modules on demand) is a clear sequel
    once we see what kinds of questions actually need it.
  * **Graceful degradation**: if `ANTHROPIC_API_KEY` is missing, we
    return a deterministic stub answer so dev/test runs don't need
    creds. Real prod behavior gates on the key.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from models.core import Project
from schemas.assistant import AskRequest, AssistantResponse, AssistantSource

logger = logging.getLogger(__name__)


# ---------- Context assembly ----------


async def build_project_context(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
) -> dict[str, Any]:
    """Pull a compact roll-up of every module's state for one project.

    Mirrors `routers.projects.get_project_detail` shape but returns a
    plain dict (no Pydantic round-trip) so the LLM sees a stable JSON
    structure with the field names already module-prefixed.

    Returns ``None`` if the project isn't found / cross-tenant.
    """
    project = (
        await session.execute(
            select(Project).where(
                Project.id == project_id,
                Project.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()
    if project is None:
        return {}

    # One COUNT-heavy round-trip per module — cheap because every column
    # in the WHERE clauses is indexed by `(project_id, ...)`.
    async def _scalar(sql: str, **params) -> int:
        return int((await session.execute(text(sql), {"pid": str(project_id), **params})).scalar_one() or 0)

    # Activity feed window: last 7 days. The assistant should weight
    # recent events but still see the steady-state shape.
    since = datetime.now(UTC) - timedelta(days=7)
    activity_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT module, event_type, title, timestamp
                FROM (
                    SELECT 'pulse' AS module, 'change_order_created' AS event_type,
                           ('CO #' || number || ' — ' || title) AS title,
                           created_at AS timestamp
                    FROM change_orders
                    WHERE project_id = :pid AND created_at >= :since
                      AND organization_id = :org_id
                    UNION ALL
                    SELECT 'pulse', 'task_completed',
                           ('Task done: ' || title), completed_at
                    FROM tasks
                    WHERE project_id = :pid AND completed_at IS NOT NULL
                      AND completed_at >= :since AND organization_id = :org_id
                    UNION ALL
                    SELECT 'siteeye', 'safety_incident_detected',
                           ('Safety incident: ' || incident_type), detected_at
                    FROM safety_incidents
                    WHERE project_id = :pid AND detected_at >= :since
                      AND organization_id = :org_id
                    UNION ALL
                    SELECT 'handover', 'defect_reported',
                           ('Defect: ' || title), reported_at
                    FROM defects
                    WHERE project_id = :pid AND reported_at >= :since
                      AND organization_id = :org_id
                    UNION ALL
                    SELECT 'drawbridge', 'rfi_raised',
                           ('RFI #' || number || ' — ' || subject), created_at
                    FROM rfis
                    WHERE project_id = :pid AND created_at >= :since
                      AND organization_id = :org_id
                ) e
                ORDER BY timestamp DESC
                LIMIT 30
                """
                ),
                {"pid": str(project_id), "org_id": str(organization_id), "since": since},
            )
        )
        .mappings()
        .all()
    )

    pulse_open_tasks = await _scalar(
        "SELECT count(*) FROM tasks WHERE project_id = :pid AND status IN ('todo','in_progress')"
    )
    pulse_open_cos = await _scalar(
        "SELECT count(*) FROM change_orders WHERE project_id = :pid AND status IN ('draft','submitted')"
    )
    drawbridge_open_rfis = await _scalar(
        "SELECT count(*) FROM rfis WHERE project_id = :pid AND status IN ('open','answered')"
    )
    drawbridge_unresolved_conflicts = await _scalar(
        "SELECT count(*) FROM conflicts WHERE project_id = :pid AND status != 'resolved'"
    )
    handover_open_defects = await _scalar(
        "SELECT count(*) FROM defects WHERE project_id = :pid AND status IN ('open','assigned','in_progress')"
    )
    siteeye_open_incidents = await _scalar(
        "SELECT count(*) FROM safety_incidents WHERE project_id = :pid AND status != 'closed'"
    )

    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "type": project.type,
            "status": project.status,
            "budget_vnd": project.budget_vnd,
            "area_sqm": float(project.area_sqm) if project.area_sqm else None,
            "floors": project.floors,
            "address": project.address,
            "start_date": project.start_date.isoformat() if project.start_date else None,
            "end_date": project.end_date.isoformat() if project.end_date else None,
        },
        "pulse": {
            "open_tasks": pulse_open_tasks,
            "open_change_orders": pulse_open_cos,
        },
        "drawbridge": {
            "open_rfi_count": drawbridge_open_rfis,
            "unresolved_conflict_count": drawbridge_unresolved_conflicts,
        },
        "handover": {"open_defect_count": handover_open_defects},
        "siteeye": {"open_safety_incident_count": siteeye_open_incidents},
        "recent_activity": [
            {
                "module": r["module"],
                "event_type": r["event_type"],
                "title": r["title"],
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            }
            for r in activity_rows
        ],
    }


# ---------- LLM call ----------


_SYSTEM_TEMPLATE = """You are an AEC (Architecture-Engineering-Construction)
project assistant for the AEC Platform — a Vietnam-focused multi-module
SaaS that combines design review (CodeGuard, Drawbridge), bidding
(BidRadar, WinWork, CostPulse), construction (ProjectPulse, SiteEye),
and handover (Handover) workflows.

You answer questions about ONE project at a time. The user's project
context is supplied as JSON below. Treat it as your only ground truth —
do not make up numbers, statuses, or events.

Reply rules:
  * Match the user's language. If they ask in Vietnamese, answer in
    Vietnamese; if in English, answer in English.
  * Be concrete: cite specific counts ("3 RFIs mở"), event titles, or
    project fields whenever you can.
  * Keep replies under ~150 words unless the user explicitly asks for
    more detail.
  * If a question can't be answered from the supplied context, say so
    plainly — don't invent. Suggest which module page might have the
    answer.

Project context:
{context_json}
"""


def _format_history(history: list) -> list[dict[str, str]]:
    """Convert ChatTurn list to Anthropic Messages API shape."""
    return [{"role": t.role, "content": t.content} for t in history]


async def ask_stream(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    user_id: UUID,
    request: AskRequest,
):
    """Streaming variant of `ask()`. Yields SSE-shaped strings:

      event: meta\\ndata: {"thread_id": "..."}\\n\\n  (sent first)
      event: token\\ndata: {"text": "..."}\\n\\n     (zero or more)
      event: done\\ndata: {"sources": [...], "context_token_estimate": N}\\n\\n

    The router wraps this in a `StreamingResponse(media_type="text/event-stream")`.
    Errors are emitted as `event: error` instead of raising — the
    EventSource API on the frontend doesn't surface HTTP errors well
    once the stream has started, so we keep error handling in-band.

    Falls back to a single-shot stub-emit when no Anthropic key is
    configured, mirroring the same fallback as `ask()`.
    """

    context = await build_project_context(session, organization_id=organization_id, project_id=project_id)
    if not context:
        yield _sse("error", {"message": "Project not found"})
        return

    thread, prior_messages = await _resolve_thread(
        session,
        organization_id=organization_id,
        project_id=project_id,
        user_id=user_id,
        thread_id=request.thread_id,
        first_question=request.question,
    )
    yield _sse("meta", {"thread_id": str(thread.id)})

    settings = get_settings()
    context_json = _safe_json_dumps(context)
    token_estimate = len(context_json) // 4
    sources = _default_sources(project_id, context)

    if not settings.anthropic_api_key:
        # Stub path: emit the whole stub answer as a single token event
        # so the client's stream consumer doesn't need a special-case.
        stub = _stub_answer(request.question, context)
        yield _sse("token", {"text": stub})
        await _persist_exchange(
            session,
            thread=thread,
            question=request.question,
            answer=stub,
            sources=sources,
            token_estimate=token_estimate,
        )
        yield _sse(
            "done",
            {
                "sources": [s.model_dump(mode="json") for s in sources],
                "context_token_estimate": token_estimate,
            },
        )
        return

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:  # pragma: no cover — packaging issue
        yield _sse("error", {"message": "langchain-anthropic not installed"})
        return

    llm = ChatAnthropic(
        model=settings.anthropic_model,
        anthropic_api_key=settings.anthropic_api_key,
        temperature=0.2,
        max_tokens=1024,
        streaming=True,
    )

    history = (
        [ChatTurnInternal(role=m.role, content=m.content) for m in prior_messages]
        if prior_messages
        else [ChatTurnInternal(role=t.role, content=t.content) for t in request.history]
    )[-20:]

    messages: list = [SystemMessage(content=_SYSTEM_TEMPLATE.format(context_json=context_json))]
    for turn in history:
        if turn.role == "user":
            messages.append(HumanMessage(content=turn.content))
        else:
            messages.append(SystemMessage(content=f"Previous answer: {turn.content}"))
    messages.append(HumanMessage(content=request.question))

    full_answer_chunks: list[str] = []
    try:
        async for chunk in llm.astream(messages):
            piece = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
            if not piece:
                continue
            full_answer_chunks.append(piece)
            yield _sse("token", {"text": piece})
    except Exception as exc:  # pragma: no cover — network / API
        logger.exception("assistant.ask_stream failed for project=%s", project_id)
        yield _sse(
            "error",
            {"message": f"AI assistant error: {type(exc).__name__}"},
        )
        return

    answer = "".join(full_answer_chunks)
    await _persist_exchange(
        session,
        thread=thread,
        question=request.question,
        answer=answer,
        sources=sources,
        token_estimate=token_estimate,
    )
    yield _sse(
        "done",
        {
            "sources": [s.model_dump(mode="json") for s in sources],
            "context_token_estimate": token_estimate,
        },
    )


def _sse(event: str, data: dict) -> str:
    """Server-Sent Events frame: `event: name\\ndata: {json}\\n\\n`."""
    import json as _json

    return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"


async def ask(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    user_id: UUID,
    request: AskRequest,
) -> AssistantResponse:
    """Build context, call Claude, persist the exchange, return the answer.

    Thread handling:
      * If `request.thread_id` is provided, load prior messages from the DB
        (the DB is authoritative — `request.history` is ignored).
      * If `request.thread_id` is None, auto-create a new thread titled
        from the first ~80 chars of the question.

    Falls back to a deterministic stub when no API key is configured.
    """
    context = await build_project_context(session, organization_id=organization_id, project_id=project_id)
    if not context:
        # 404 path — bubble a clean message; the router will turn this
        # into a 404 HTTPException.
        return AssistantResponse(
            project_id=project_id,
            answer="Project not found.",
            sources=[],
            context_token_estimate=0,
        )

    # Resolve / create the thread + load prior messages.
    thread, prior_messages = await _resolve_thread(
        session,
        organization_id=organization_id,
        project_id=project_id,
        user_id=user_id,
        thread_id=request.thread_id,
        first_question=request.question,
    )
    # Convert ORM messages to ChatTurn so the rest of the function can
    # treat the source uniformly.
    history_from_db = [ChatTurnInternal(role=m.role, content=m.content) for m in prior_messages]

    settings = get_settings()
    context_json = _safe_json_dumps(context)
    token_estimate = len(context_json) // 4  # ~4 chars per token rule of thumb

    if not settings.anthropic_api_key:
        # Stub path. Useful for unit tests + local dev — same shape as
        # the real path, deterministic content. Mentions a couple of
        # the most informative context numbers so it's not a useless reply.
        stub_answer = _stub_answer(request.question, context)
        sources = _default_sources(project_id, context)
        await _persist_exchange(
            session,
            thread=thread,
            question=request.question,
            answer=stub_answer,
            sources=sources,
            token_estimate=token_estimate,
        )
        return AssistantResponse(
            project_id=project_id,
            thread_id=thread.id,
            answer=stub_answer,
            sources=sources,
            context_token_estimate=token_estimate,
        )

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:  # pragma: no cover — packaging issue
        return AssistantResponse(
            project_id=project_id,
            answer="AI assistant unavailable: langchain-anthropic not installed.",
            sources=[],
            context_token_estimate=token_estimate,
        )

    llm = ChatAnthropic(
        model=settings.anthropic_model,
        anthropic_api_key=settings.anthropic_api_key,
        temperature=0.2,
        max_tokens=1024,
    )

    # Authoritative history comes from the DB when a thread is loaded;
    # legacy clients passing `request.history` only see effect when
    # there's no `thread_id` (i.e. their first turn before the DB has
    # anything). Cap at 20 turns either way to bound the prompt size.
    history = (
        history_from_db
        if history_from_db
        else [ChatTurnInternal(role=t.role, content=t.content) for t in request.history]
    )
    history = history[-20:]

    messages: list = [SystemMessage(content=_SYSTEM_TEMPLATE.format(context_json=context_json))]
    for turn in history:
        if turn.role == "user":
            messages.append(HumanMessage(content=turn.content))
        else:
            # langchain-anthropic doesn't expose a separate AIMessage
            # constructor in our pinned version — fall back to a plain
            # string in the SystemMessage chain. Acceptable trade-off
            # given chat history is just there for short context, not
            # for the model to deeply reason over.
            messages.append(SystemMessage(content=f"Previous answer: {turn.content}"))
    messages.append(HumanMessage(content=request.question))

    try:
        result = await llm.ainvoke(messages)
        answer = result.content if isinstance(result.content, str) else str(result.content)
    except Exception as exc:  # pragma: no cover — network / API
        logger.exception("assistant.ask failed for project=%s", project_id)
        answer = f"Xin lỗi, AI assistant đang gặp sự cố — vui lòng thử lại sau. (Lỗi: {type(exc).__name__})"

    sources = _default_sources(project_id, context)
    await _persist_exchange(
        session,
        thread=thread,
        question=request.question,
        answer=answer,
        sources=sources,
        token_estimate=token_estimate,
    )
    return AssistantResponse(
        project_id=project_id,
        thread_id=thread.id,
        answer=answer,
        sources=sources,
        context_token_estimate=token_estimate,
    )


# ---------- Thread persistence ----------


from dataclasses import dataclass  # noqa: E402 — keep helper-imports near use site
from uuid import uuid4  # noqa: E402

from models.assistant import AssistantMessage, AssistantThread  # noqa: E402


@dataclass
class ChatTurnInternal:
    """In-process representation of a chat turn. Distinct from the
    `schemas.assistant.ChatTurn` Pydantic model so we can construct it
    from either an ORM message or a request body without going through
    Pydantic validation each time."""

    role: str
    content: str


async def _resolve_thread(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    user_id: UUID,
    thread_id: UUID | None,
    first_question: str,
) -> tuple[AssistantThread, list[AssistantMessage]]:
    """Load an existing thread (with its messages) or create a fresh one.

    When `thread_id` is provided but doesn't match the caller's project +
    user, we silently fall through to creating a new thread instead of
    raising — the user is allowed to start a new conversation, just not
    impersonate an existing one. The auth context already established
    that org/user/project are legit.
    """
    if thread_id is not None:
        existing = (
            await session.execute(
                select(AssistantThread).where(
                    AssistantThread.id == thread_id,
                    AssistantThread.organization_id == organization_id,
                    AssistantThread.project_id == project_id,
                    AssistantThread.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            messages = (
                (
                    await session.execute(
                        select(AssistantMessage)
                        .where(AssistantMessage.thread_id == existing.id)
                        .order_by(AssistantMessage.created_at)
                    )
                )
                .scalars()
                .all()
            )
            return existing, list(messages)

    # Fresh thread — title derived from first question, capped at 80 chars
    # so the sidebar renders a meaningful but bounded label.
    title = first_question.strip().splitlines()[0] if first_question.strip() else "Cuộc trò chuyện"
    title = title[:80].rstrip() or "Cuộc trò chuyện"

    now = datetime.now(UTC)
    thread = AssistantThread(
        id=uuid4(),
        organization_id=organization_id,
        project_id=project_id,
        user_id=user_id,
        title=title,
        last_message_at=now,
        created_at=now,
    )
    session.add(thread)
    await session.flush()
    return thread, []


async def _persist_exchange(
    session: AsyncSession,
    *,
    thread: AssistantThread,
    question: str,
    answer: str,
    sources: list[AssistantSource],
    token_estimate: int,
) -> None:
    """Insert the user question + assistant answer; bump the thread's
    `last_message_at` so the sidebar re-orders correctly."""
    now = datetime.now(UTC)
    sources_payload = [s.model_dump(mode="json") for s in sources]

    session.add(
        AssistantMessage(
            id=uuid4(),
            thread_id=thread.id,
            role="user",
            content=question,
            sources=[],
            tool_calls=[],
            context_token_estimate=None,
            created_at=now,
        )
    )
    session.add(
        AssistantMessage(
            id=uuid4(),
            thread_id=thread.id,
            role="assistant",
            content=answer,
            sources=sources_payload,
            tool_calls=[],
            context_token_estimate=token_estimate,
            created_at=now,
        )
    )
    thread.last_message_at = now
    await session.commit()


# ---------- Helpers ----------


def _safe_json_dumps(obj: Any) -> str:
    """JSON dump with sensible fallbacks for Decimal / datetime / UUID."""
    import json
    from decimal import Decimal

    def _default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return float(o)
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return str(o)

    return json.dumps(obj, default=_default, ensure_ascii=False, indent=2)


def _stub_answer(question: str, context: dict[str, Any]) -> str:
    """Deterministic offline answer used when no Anthropic key is configured."""
    project = context.get("project", {})
    pulse = context.get("pulse", {})
    return (
        f"[AI assistant offline — no ANTHROPIC_API_KEY configured]\n\n"
        f"You asked: {question}\n\n"
        f"Quick stats for {project.get('name', 'this project')}: "
        f"{pulse.get('open_tasks', 0)} task mở, "
        f"{pulse.get('open_change_orders', 0)} change order mở. "
        f"Recent activity: {len(context.get('recent_activity') or [])} events in last 7 days."
    )


def _default_sources(project_id: UUID, context: dict[str, Any]) -> list[AssistantSource]:
    """Build clickable in-app citations from the context modules that
    have non-empty signal. Front-end renders these as a strip under the
    answer, so users can drill into the source data."""
    sources: list[AssistantSource] = []
    p = str(project_id)

    pulse = context.get("pulse", {})
    if pulse.get("open_tasks") or pulse.get("open_change_orders"):
        sources.append(
            AssistantSource(
                module="pulse",
                label=(f"{pulse.get('open_tasks', 0)} task mở · {pulse.get('open_change_orders', 0)} CO mở"),
                route=f"/pulse?project_id={p}",
            )
        )
    drawbridge = context.get("drawbridge", {})
    if drawbridge.get("open_rfi_count") or drawbridge.get("unresolved_conflict_count"):
        sources.append(
            AssistantSource(
                module="drawbridge",
                label=(
                    f"{drawbridge.get('open_rfi_count', 0)} RFI mở · "
                    f"{drawbridge.get('unresolved_conflict_count', 0)} xung đột chưa giải quyết"
                ),
                route=f"/drawbridge?project_id={p}",
            )
        )
    handover = context.get("handover", {})
    if handover.get("open_defect_count"):
        sources.append(
            AssistantSource(
                module="handover",
                label=f"{handover.get('open_defect_count', 0)} lỗi tồn đọng",
                route=f"/handover?project_id={p}",
            )
        )
    siteeye = context.get("siteeye", {})
    if siteeye.get("open_safety_incident_count"):
        sources.append(
            AssistantSource(
                module="siteeye",
                label=f"{siteeye.get('open_safety_incident_count', 0)} sự cố an toàn mở",
                route=f"/siteeye?project_id={p}",
            )
        )
    if context.get("recent_activity"):
        sources.append(
            AssistantSource(
                module="activity",
                label=f"{len(context['recent_activity'])} sự kiện trong 7 ngày qua",
                route=f"/activity?project_id={p}",
            )
        )
    return sources
