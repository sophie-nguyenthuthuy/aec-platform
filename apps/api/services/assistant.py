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
    # in the WHERE clauses is indexed by `(project_id, ...)`. We fan
    # them out concurrently below; an AsyncSession isn't safe under
    # concurrent execute() calls (same problem the project hub hit and
    # solved with a Semaphore), so each helper opens its own connection
    # via the engine and returns a plain int. That lets a 14-way
    # gather complete in ~one round-trip rather than 14×.
    async def _scalar(sql: str, **params) -> int:
        return int((await session.execute(text(sql), {"pid": str(project_id), **params})).scalar_one() or 0)

    # Activity feed window: last 7 days. The assistant should weight
    # recent events but still see the steady-state shape. The UNION ALL
    # below grew from 5 sources (pre-Phase-6) to cover every module that
    # emits a discrete user-facing event.
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
                    UNION ALL
                    SELECT 'submittals', 'submittal_review',
                           ('Submittal: ' || title || ' → ' || status),
                           updated_at
                    FROM submittals
                    WHERE project_id = :pid AND updated_at >= :since
                      AND organization_id = :org_id
                      AND status IN ('approved','approved_as_noted','revise_resubmit','rejected')
                    UNION ALL
                    SELECT 'dailylog', 'high_severity_observation',
                           ('Quan sát mức cao: ' || COALESCE(description, kind)),
                           created_at
                    FROM observations
                    WHERE project_id = :pid AND created_at >= :since
                      AND organization_id = :org_id
                      AND severity IN ('high','critical')
                    UNION ALL
                    SELECT 'punchlist', 'list_signed_off',
                           ('Punch list signed off: ' || name),
                           signed_off_at
                    FROM punch_lists
                    WHERE project_id = :pid AND signed_off_at IS NOT NULL
                      AND signed_off_at >= :since AND organization_id = :org_id
                    UNION ALL
                    SELECT 'changeorder', 'co_candidate_pending',
                           ('CO candidate: ' || COALESCE(title, 'untitled')),
                           created_at
                    FROM change_order_candidates
                    WHERE project_id = :pid AND created_at >= :since
                      AND organization_id = :org_id
                      AND status = 'pending'
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

    # ---- Per-module roll-ups (sequential — same TenantAwareSession can't
    # multiplex concurrent SQL, see the project hub note for the same
    # constraint). Each query is a single indexed COUNT or simple SELECT
    # that stays well under 5ms locally; the full 14-module sweep runs
    # in ~50-80ms total, fast enough that we don't need to fan out. ----

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

    # Costpulse: latest estimate snapshot. Kept in a single SELECT (no
    # JOIN) so the roll-up doesn't pay for an aggregate the LLM rarely
    # needs — `latest_total_vnd` and `approved_count` together cover
    # ~95% of cost-shape questions ("how big is the project?", "what's
    # been approved?").
    costpulse_estimate_count = await _scalar("SELECT count(*) FROM estimates WHERE project_id = :pid")
    costpulse_approved_count = await _scalar(
        "SELECT count(*) FROM estimates WHERE project_id = :pid AND status = 'approved'"
    )
    costpulse_latest = (
        (
            await session.execute(
                text("SELECT id, total_vnd FROM estimates WHERE project_id = :pid ORDER BY created_at DESC LIMIT 1"),
                {"pid": str(project_id)},
            )
        )
        .mappings()
        .first()
    )

    # Winwork: was this project seeded from a won proposal? Surface the
    # link so the model can answer "what was the original fee?" or
    # "who's the proposal owner on this project?".
    winwork_row = (
        (
            await session.execute(
                text(
                    "SELECT id, status, total_fee_vnd FROM proposals "
                    "WHERE project_id = :pid ORDER BY created_at DESC LIMIT 1"
                ),
                {"pid": str(project_id)},
            )
        )
        .mappings()
        .first()
    )

    # Codeguard: counts only — actual findings live in the per-check
    # detail page. Surfacing scan/checklist counts lets the model answer
    # "have we run compliance checks on this project?".
    codeguard_check_count = await _scalar("SELECT count(*) FROM compliance_checks WHERE project_id = :pid")
    codeguard_checklist_count = await _scalar("SELECT count(*) FROM permit_checklists WHERE project_id = :pid")

    # Schedulepilot: schedule + activity counts + slip days. The slip
    # is the single most-asked-about metric in CPM-style questions —
    # "are we behind?", "by how much?".
    schedulepilot_schedule_count = await _scalar("SELECT count(*) FROM schedules WHERE project_id = :pid")
    schedulepilot_row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                  COALESCE(SUM(CASE WHEN behind_schedule THEN 1 ELSE 0 END), 0) AS behind,
                  COALESCE(MAX(slip_days), 0)                                  AS max_slip,
                  COALESCE(AVG(percent_complete), 0)                           AS avg_pct,
                  count(*)                                                     AS activity_count
                FROM schedule_activities a
                JOIN schedules s ON s.id = a.schedule_id
                WHERE s.project_id = :pid
                """
                ),
                {"pid": str(project_id)},
            )
        )
        .mappings()
        .first()
    )

    # Submittals: ball-in-court counts. Two values matter — the
    # designer's review queue (designer_court) and the contractor's
    # response queue (contractor_court). Together they answer "who's
    # holding up the submittal flow right now?".
    submittals_row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                  count(*) FILTER (WHERE status IN ('open','submitted','under_review'))   AS open_count,
                  count(*) FILTER (WHERE status = 'revise_resubmit')                      AS revise_count,
                  count(*) FILTER (WHERE status IN ('approved','approved_as_noted'))      AS approved_count,
                  count(*) FILTER (WHERE status IN ('open','submitted','under_review')
                                   AND ball_in_court = 'designer')                        AS designer_court,
                  count(*) FILTER (WHERE status = 'revise_resubmit'
                                   AND ball_in_court = 'contractor')                      AS contractor_court
                FROM submittals
                WHERE project_id = :pid
                """
                ),
                {"pid": str(project_id)},
            )
        )
        .mappings()
        .first()
    )

    # Dailylog: log_count windowed to 30 days (the LLM cares about
    # recent shape, not lifetime). Severity counts not windowed —
    # "are there 5 high-severity unresolved observations?" is a
    # standing question regardless of when they were logged.
    dailylog_window_start = (datetime.now(UTC) - timedelta(days=30)).date()
    dailylog_log_count = await _scalar(
        "SELECT count(*) FROM daily_logs WHERE project_id = :pid AND log_date >= :since",
        since=dailylog_window_start,
    )
    dailylog_obs_row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                  count(*) FILTER (WHERE status IN ('open','in_progress'))         AS open_count,
                  count(*) FILTER (WHERE severity IN ('high','critical')
                                   AND status IN ('open','in_progress'))           AS high_count
                FROM observations
                WHERE project_id = :pid
                """
                ),
                {"pid": str(project_id)},
            )
        )
        .mappings()
        .first()
    )

    # Changeorder: counts + cumulative impact. The cost/schedule totals
    # are running sums across approved + executed — what's already been
    # committed against the original baseline. Pending-candidate count
    # answers "is the AI finding things we haven't reviewed yet?".
    changeorder_row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                  count(*)                                                            AS total_count,
                  count(*) FILTER (WHERE status IN ('draft','submitted'))             AS open_count,
                  count(*) FILTER (WHERE status IN ('approved','executed'))           AS approved_count,
                  COALESCE(SUM(cost_impact_vnd) FILTER
                                  (WHERE status IN ('approved','executed')), 0)      AS total_cost,
                  COALESCE(SUM(schedule_impact_days) FILTER
                                  (WHERE status IN ('approved','executed')), 0)      AS total_days
                FROM change_orders
                WHERE project_id = :pid
                """
                ),
                {"pid": str(project_id)},
            )
        )
        .mappings()
        .first()
    )
    changeorder_pending_candidates = await _scalar(
        "SELECT count(*) FROM change_order_candidates WHERE project_id = :pid AND status = 'pending'"
    )

    # Punchlist: list-level + item-level counts in one round-trip via
    # FILTER aggregates. high_severity_open_items is the field engineers
    # most-asked metric — "how many high-priority items still open
    # against handover?".
    punchlist_list_row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                  count(*)                                              AS list_count,
                  count(*) FILTER (WHERE status = 'open')                AS open_list_count,
                  count(*) FILTER (WHERE status = 'signed_off')          AS signed_off_count
                FROM punch_lists
                WHERE project_id = :pid
                """
                ),
                {"pid": str(project_id)},
            )
        )
        .mappings()
        .first()
    )
    punchlist_item_row = (
        (
            await session.execute(
                text(
                    """
                SELECT
                  count(*)                                                AS total_items,
                  count(*) FILTER (WHERE i.status = 'open')               AS open_items,
                  count(*) FILTER (WHERE i.status = 'verified')           AS verified_items,
                  count(*) FILTER (WHERE i.status = 'open'
                                   AND i.severity = 'high')               AS high_open
                FROM punch_items i
                JOIN punch_lists l ON l.id = i.list_id
                WHERE l.project_id = :pid
                """
                ),
                {"pid": str(project_id)},
            )
        )
        .mappings()
        .first()
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
        "winwork": (
            {
                "proposal_id": str(winwork_row["id"]),
                "proposal_status": winwork_row["status"],
                "total_fee_vnd": int(winwork_row["total_fee_vnd"]) if winwork_row["total_fee_vnd"] else None,
            }
            if winwork_row
            else {}
        ),
        "costpulse": {
            "estimate_count": costpulse_estimate_count,
            "approved_count": costpulse_approved_count,
            "latest_estimate_id": str(costpulse_latest["id"]) if costpulse_latest else None,
            "latest_total_vnd": int(costpulse_latest["total_vnd"])
            if costpulse_latest and costpulse_latest["total_vnd"]
            else None,
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
        "codeguard": {
            "compliance_check_count": codeguard_check_count,
            "permit_checklist_count": codeguard_checklist_count,
        },
        "schedulepilot": (
            {
                "schedule_count": schedulepilot_schedule_count,
                "activity_count": int(schedulepilot_row["activity_count"] or 0),
                "behind_schedule_count": int(schedulepilot_row["behind"] or 0),
                "overall_slip_days": int(schedulepilot_row["max_slip"] or 0),
                "avg_percent_complete": float(schedulepilot_row["avg_pct"] or 0),
            }
            if schedulepilot_row
            else {"schedule_count": schedulepilot_schedule_count}
        ),
        "submittals": (
            {
                "open_count": int(submittals_row["open_count"] or 0),
                "revise_resubmit_count": int(submittals_row["revise_count"] or 0),
                "approved_count": int(submittals_row["approved_count"] or 0),
                "designer_court_count": int(submittals_row["designer_court"] or 0),
                "contractor_court_count": int(submittals_row["contractor_court"] or 0),
            }
            if submittals_row
            else {}
        ),
        "dailylog": (
            {
                "log_count_30d": dailylog_log_count,
                "open_observation_count": int(dailylog_obs_row["open_count"] or 0) if dailylog_obs_row else 0,
                "high_severity_observation_count": int(dailylog_obs_row["high_count"] or 0) if dailylog_obs_row else 0,
            }
        ),
        "changeorder": (
            {
                "total_count": int(changeorder_row["total_count"] or 0),
                "open_count": int(changeorder_row["open_count"] or 0),
                "approved_count": int(changeorder_row["approved_count"] or 0),
                "pending_candidates": changeorder_pending_candidates,
                "total_cost_impact_vnd": int(changeorder_row["total_cost"] or 0),
                "total_schedule_impact_days": int(changeorder_row["total_days"] or 0),
            }
            if changeorder_row
            else {"pending_candidates": changeorder_pending_candidates}
        ),
        "punchlist": (
            {
                "list_count": int(punchlist_list_row["list_count"] or 0),
                "open_list_count": int(punchlist_list_row["open_list_count"] or 0),
                "signed_off_list_count": int(punchlist_list_row["signed_off_count"] or 0),
                "total_items": int(punchlist_item_row["total_items"] or 0) if punchlist_item_row else 0,
                "open_items": int(punchlist_item_row["open_items"] or 0) if punchlist_item_row else 0,
                "verified_items": int(punchlist_item_row["verified_items"] or 0) if punchlist_item_row else 0,
                "high_severity_open_items": int(punchlist_item_row["high_open"] or 0) if punchlist_item_row else 0,
            }
            if punchlist_list_row
            else {}
        ),
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
SaaS spanning the project lifecycle. The context blob below covers all
14 modules:

  * winwork           — proposal status + total fee (if seeded from a bid)
  * costpulse         — estimate counts + latest total VND
  * pulse             — open tasks + open change orders
  * drawbridge        — open RFIs + unresolved drawing conflicts
  * handover          — open defects on the handover punch list
  * siteeye           — open safety incidents (CV-detected)
  * codeguard         — compliance check + permit checklist counts
  * schedulepilot     — CPM slip days, behind-schedule count, % complete
  * submittals        — queue counts + ball-in-court split (designer vs contractor)
  * dailylog          — recent log count, open / high-severity observations
  * changeorder       — total + cumulative cost/schedule impact + AI candidates
  * punchlist         — list + item counts incl. high-severity open items
  * recent_activity   — last 30 events across modules in the past 7 days

You answer questions about ONE project at a time. Treat the JSON
context as your only ground truth — do not make up numbers, statuses,
or events. When a question crosses modules ("what's blocking handover
on Tower A?"), inspect every relevant section of the context — handover
defects, punchlist open items, submittals revise-resubmit, schedule
slip — before answering.

Reply rules:
  * Match the user's language. If they ask in Vietnamese, answer in
    Vietnamese; if in English, answer in English.
  * Be concrete: cite specific counts ("3 RFIs mở"), event titles, or
    project fields whenever you can. Use the exact module names above
    so the user can find the source data.
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
    """Deterministic offline answer used when no Anthropic key is configured.

    Phase 6: surfaces a one-liner per non-empty module so the dev/test
    flow exercises the full 14-module context shape, not just pulse.
    """
    project = context.get("project", {})
    parts = ["[AI assistant offline — no ANTHROPIC_API_KEY configured]", f"You asked: {question}"]

    pulse = context.get("pulse", {})
    drawbridge = context.get("drawbridge", {})
    handover = context.get("handover", {})
    siteeye = context.get("siteeye", {})
    schedulepilot = context.get("schedulepilot", {})
    submittals = context.get("submittals", {})
    dailylog = context.get("dailylog", {})
    changeorder = context.get("changeorder", {})
    punchlist = context.get("punchlist", {})

    snapshot: list[str] = []
    if pulse.get("open_tasks") or pulse.get("open_change_orders"):
        snapshot.append(f"pulse: {pulse.get('open_tasks', 0)} task mở, {pulse.get('open_change_orders', 0)} CO mở")
    if drawbridge.get("open_rfi_count"):
        snapshot.append(f"drawbridge: {drawbridge['open_rfi_count']} RFI mở")
    if handover.get("open_defect_count"):
        snapshot.append(f"handover: {handover['open_defect_count']} lỗi tồn đọng")
    if siteeye.get("open_safety_incident_count"):
        snapshot.append(f"siteeye: {siteeye['open_safety_incident_count']} sự cố an toàn mở")
    if schedulepilot.get("overall_slip_days"):
        snapshot.append(f"schedulepilot: trễ {schedulepilot['overall_slip_days']} ngày")
    if submittals.get("revise_resubmit_count"):
        snapshot.append(f"submittals: {submittals['revise_resubmit_count']} cần làm lại")
    if dailylog.get("high_severity_observation_count"):
        snapshot.append(f"dailylog: {dailylog['high_severity_observation_count']} quan sát mức cao")
    if changeorder.get("pending_candidates"):
        snapshot.append(f"changeorder: {changeorder['pending_candidates']} candidate AI chờ duyệt")
    if punchlist.get("high_severity_open_items"):
        snapshot.append(f"punchlist: {punchlist['high_severity_open_items']} item mức cao chưa xử lý")

    parts.append(
        f"Snapshot {project.get('name', 'this project')}: "
        + (" · ".join(snapshot) if snapshot else "no module signal")
        + f". Recent activity: {len(context.get('recent_activity') or [])} events in last 7 days."
    )
    return "\n\n".join(parts)


def _default_sources(project_id: UUID, context: dict[str, Any]) -> list[AssistantSource]:
    """Build clickable in-app citations from the context modules that
    have non-empty signal. Front-end renders these as a strip under the
    answer, so users can drill into the source data.

    Each branch is gated on a "this module has non-zero signal" check —
    a project that's still in the bidding phase doesn't need a Punchlist
    citation, and surfacing every module unconditionally would dilute
    the strip into noise. The threshold is intentionally generous (any
    non-zero count counts), so a single open RFI still earns a chip.
    """
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

    # ---- Phase 6: 9 additional module citations. Same gating pattern —
    # only render a chip when there's signal worth showing. ----

    winwork = context.get("winwork", {})
    if winwork.get("proposal_id"):
        sources.append(
            AssistantSource(
                module="winwork",
                label=f"Proposal: {winwork.get('proposal_status', 'unknown')}",
                route=f"/winwork/proposals/{winwork['proposal_id']}",
            )
        )
    costpulse = context.get("costpulse", {})
    if costpulse.get("estimate_count") or costpulse.get("approved_count"):
        sources.append(
            AssistantSource(
                module="costpulse",
                label=(f"{costpulse.get('estimate_count', 0)} dự toán · {costpulse.get('approved_count', 0)} đã duyệt"),
                route=f"/costpulse/estimates?project_id={p}",
            )
        )
    codeguard = context.get("codeguard", {})
    if codeguard.get("compliance_check_count") or codeguard.get("permit_checklist_count"):
        sources.append(
            AssistantSource(
                module="codeguard",
                label=(
                    f"{codeguard.get('compliance_check_count', 0)} kiểm tra · "
                    f"{codeguard.get('permit_checklist_count', 0)} checklist cấp phép"
                ),
                route=f"/codeguard?project_id={p}",
            )
        )
    schedulepilot = context.get("schedulepilot", {})
    if schedulepilot.get("schedule_count") or schedulepilot.get("activity_count"):
        # Slip days is the most useful single number here — surface it
        # in the chip label so the user sees "tracking 7 days late" at
        # a glance without clicking through.
        slip = schedulepilot.get("overall_slip_days", 0)
        behind = schedulepilot.get("behind_schedule_count", 0)
        sources.append(
            AssistantSource(
                module="schedulepilot",
                label=(
                    f"{schedulepilot.get('schedule_count', 0)} schedule"
                    + (f" · slip {slip}d" if slip else "")
                    + (f" · {behind} hoạt động trễ" if behind else "")
                ),
                route=f"/schedule?project_id={p}",
            )
        )
    submittals = context.get("submittals", {})
    if submittals.get("open_count") or submittals.get("revise_resubmit_count") or submittals.get("approved_count"):
        # Show ball-in-court split — answers "who's the bottleneck?" at
        # the chip level. `designer_court` and `contractor_court`
        # together name the queue holding things up.
        designer = submittals.get("designer_court_count", 0)
        contractor = submittals.get("contractor_court_count", 0)
        sources.append(
            AssistantSource(
                module="submittals",
                label=(
                    f"{submittals.get('open_count', 0)} mở"
                    + (f" · designer {designer}" if designer else "")
                    + (f" · contractor {contractor}" if contractor else "")
                ),
                route=f"/submittals?project_id={p}",
            )
        )
    dailylog = context.get("dailylog", {})
    high_obs = dailylog.get("high_severity_observation_count", 0)
    if dailylog.get("log_count_30d") or high_obs:
        sources.append(
            AssistantSource(
                module="dailylog",
                label=(
                    f"{dailylog.get('log_count_30d', 0)} nhật ký 30d"
                    + (f" · {high_obs} quan sát mức cao" if high_obs else "")
                ),
                route=f"/dailylog?project_id={p}",
            )
        )
    changeorder = context.get("changeorder", {})
    pending = changeorder.get("pending_candidates", 0)
    if changeorder.get("total_count") or pending:
        sources.append(
            AssistantSource(
                module="changeorder",
                label=(
                    f"{changeorder.get('open_count', 0)} mở · "
                    f"{changeorder.get('approved_count', 0)} duyệt" + (f" · {pending} candidate AI" if pending else "")
                ),
                route=f"/changeorder?project_id={p}",
            )
        )
    punchlist = context.get("punchlist", {})
    if punchlist.get("list_count") or punchlist.get("total_items"):
        high_open = punchlist.get("high_severity_open_items", 0)
        sources.append(
            AssistantSource(
                module="punchlist",
                label=(
                    f"{punchlist.get('list_count', 0)} list · "
                    f"{punchlist.get('open_items', 0)}/{punchlist.get('total_items', 0)} mở"
                    + (f" · {high_open} cao chưa xử lý" if high_open else "")
                ),
                route=f"/punchlist?project_id={p}",
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
