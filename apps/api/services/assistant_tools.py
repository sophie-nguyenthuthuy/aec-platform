"""Tool definitions for the AI assistant's tool-use loop.

Instead of stuffing every module's roll-up into a single system prompt
(the v1 approach in `services/assistant.py`), we expose a handful of
typed tools the model can call on demand. The model decides *which*
data is worth fetching for the question at hand — saving tokens and
producing sharper, less-hallucinated answers.

Each tool:
  * Has a JSON schema describing its inputs (passed to Anthropic's
    Messages API as `tools=[...]`).
  * Has an async Python implementation taking `(session, organization_id,
    project_id, **inputs)` → JSON-serialisable result.
  * Is registered in `TOOLS` below so the loop can dispatch by name.

Adding a new tool is two edits: write the impl (with a docstring +
schema) and append to `TOOLS`.

NOTE: tools are *project-scoped* — every implementation requires
`organization_id` + `project_id` and filters its query by them, so the
model can't accidentally read another tenant's data even if it
hallucinates a cross-tenant ID in its tool call.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


ToolImpl = Callable[..., Awaitable[Any]]


# ---------- Tool implementations ----------


async def get_open_change_orders(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    limit: int = 20,
) -> dict[str, Any]:
    """Return open change orders (status IN draft / submitted) with
    cost/schedule impact + initiator. Useful when the user asks "what
    cost changes are pending?" or "is there a budget creep?"."""
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT number, title, status, initiator,
                           cost_impact_vnd, schedule_impact_days, created_at
                    FROM change_orders
                    WHERE organization_id = :org AND project_id = :pid
                      AND status IN ('draft', 'submitted')
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"org": str(organization_id), "pid": str(project_id), "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return {
        "count": len(rows),
        "items": [
            {
                "number": r["number"],
                "title": r["title"],
                "status": r["status"],
                "initiator": r["initiator"],
                "cost_impact_vnd": r["cost_impact_vnd"],
                "schedule_impact_days": r["schedule_impact_days"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


async def get_open_rfis(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    limit: int = 20,
) -> dict[str, Any]:
    """Open RFIs (status open or answered). 'Answered' counts as still-
    relevant because the issue isn't closed yet."""
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT number, subject, status, priority,
                           due_date, created_at
                    FROM rfis
                    WHERE organization_id = :org AND project_id = :pid
                      AND status IN ('open', 'answered')
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"org": str(organization_id), "pid": str(project_id), "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return {
        "count": len(rows),
        "items": [
            {
                "number": r["number"],
                "subject": r["subject"],
                "status": r["status"],
                "priority": r["priority"],
                "due_date": r["due_date"].isoformat() if r["due_date"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


async def get_recent_safety_incidents(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    days: int = 30,
    limit: int = 20,
) -> dict[str, Any]:
    """Safety incidents detected in the last `days` days. Severity-sorted
    so the highest-priority items appear first."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT incident_type, severity, status,
                           ai_description, detected_at
                    FROM safety_incidents
                    WHERE organization_id = :org AND project_id = :pid
                      AND detected_at >= :since
                    ORDER BY
                        CASE severity
                            WHEN 'critical' THEN 1
                            WHEN 'high'     THEN 2
                            WHEN 'medium'   THEN 3
                            WHEN 'low'      THEN 4
                            ELSE 5
                        END,
                        detected_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "org": str(organization_id),
                    "pid": str(project_id),
                    "since": since,
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return {
        "count": len(rows),
        "items": [
            {
                "incident_type": r["incident_type"],
                "severity": r["severity"],
                "status": r["status"],
                "description": r["ai_description"],
                "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
            }
            for r in rows
        ],
    }


async def get_open_defects(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    limit: int = 20,
) -> dict[str, Any]:
    """Handover defects in open / assigned / in_progress states.
    Priority-sorted (critical → low)."""
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT title, description, status, priority, reported_at
                    FROM defects
                    WHERE organization_id = :org AND project_id = :pid
                      AND status IN ('open', 'assigned', 'in_progress')
                    ORDER BY
                        CASE priority
                            WHEN 'critical' THEN 1
                            WHEN 'high'     THEN 2
                            WHEN 'medium'   THEN 3
                            WHEN 'low'      THEN 4
                            ELSE 5
                        END,
                        reported_at DESC
                    LIMIT :limit
                    """
                ),
                {"org": str(organization_id), "pid": str(project_id), "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return {
        "count": len(rows),
        "items": [
            {
                "title": r["title"],
                "description": r["description"],
                "status": r["status"],
                "priority": r["priority"],
                "reported_at": r["reported_at"].isoformat() if r["reported_at"] else None,
            }
            for r in rows
        ],
    }


async def get_latest_estimate(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
) -> dict[str, Any]:
    """The most recent COSTPULSE estimate for the project. Lets the
    assistant answer "what's the current budget" / "how much have we
    estimated for materials?" with concrete numbers instead of "see
    the CostPulse page"."""
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, name, version, status, total_vnd,
                           confidence, method, created_at
                    FROM estimates
                    WHERE organization_id = :org AND project_id = :pid
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"org": str(organization_id), "pid": str(project_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return {"found": False}
    return {
        "found": True,
        "id": str(row["id"]),
        "name": row["name"],
        "version": row["version"],
        "status": row["status"],
        "total_vnd": row["total_vnd"],
        "confidence": row["confidence"],
        "method": row["method"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


# ---------- Tool registry ----------


# Anthropic Messages-API-shaped tool definitions. Names + schemas are the
# contract the model sees; `impl` is invoked when it picks one.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_open_change_orders",
        "description": (
            "Return change orders that are still open (draft or submitted) "
            "for the current project, with cost/schedule impact and who "
            "initiated them. Use this when the user asks about pending "
            "budget changes, cost creep, or who's pushing scope changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max items to return (default 20).",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
        "impl": get_open_change_orders,
    },
    {
        "name": "get_open_rfis",
        "description": (
            "Return open / awaiting-response RFIs for the current project "
            "with priority and due date. Use when the user asks about "
            "design clarifications, what's blocking the contractor, or "
            "what needs an answer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
        "impl": get_open_rfis,
    },
    {
        "name": "get_recent_safety_incidents",
        "description": (
            "Return safety incidents detected in the last N days, "
            "severity-sorted. Use when the user asks about site safety, "
            "PPE issues, or accident trends."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Lookback window in days (default 30).",
                    "minimum": 1,
                    "maximum": 365,
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
        "impl": get_recent_safety_incidents,
    },
    {
        "name": "get_open_defects",
        "description": (
            "Return open handover defects (priority-sorted). Use when the "
            "user asks about quality issues, snag-list items, or what's "
            "blocking handover."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
        "impl": get_open_defects,
    },
    {
        "name": "get_latest_estimate",
        "description": (
            "Return the most recent CostPulse estimate (version, status, "
            "total VND). Use when the user asks about the current budget, "
            "estimate confidence, or who approved it."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "impl": get_latest_estimate,
    },
]


def get_tool_definitions_for_anthropic() -> list[dict[str, Any]]:
    """Strip the Python `impl` keys — the Anthropic SDK doesn't want them."""
    return [{k: v for k, v in tool.items() if k != "impl"} for tool in TOOLS]


def get_tool_impl(name: str) -> ToolImpl | None:
    """Look up a tool's Python implementation by name. Returns None when
    the model hallucinates an unknown tool — caller should respond with
    a `tool_result` carrying an error so the model can self-correct."""
    for tool in TOOLS:
        if tool["name"] == name:
            return tool["impl"]
    return None


async def execute_tool_call(
    name: str,
    inputs: dict[str, Any],
    *,
    session: AsyncSession,
    organization_id: UUID,
    project_id: UUID,
) -> dict[str, Any]:
    """Dispatch a single tool call. Catches exceptions so a buggy tool
    doesn't tank the whole conversation — the model sees an error
    `tool_result` and can either retry, pick a different tool, or
    apologise to the user."""
    impl = get_tool_impl(name)
    if impl is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return await impl(
            session,
            organization_id=organization_id,
            project_id=project_id,
            **inputs,
        )
    except TypeError as exc:
        # Model called the tool with bad args; surface the error so it
        # can correct on the next turn.
        return {"error": f"Bad arguments to {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("tool %s failed", name)
        return {"error": f"{name} failed: {type(exc).__name__}"}
