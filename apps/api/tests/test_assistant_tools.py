"""Service-layer tests for the AI assistant's tool-use helpers.

Tools are project-scoped — every implementation requires
`organization_id` + `project_id` and filters by them. We assert:
  (a) the right WHERE clause shape (org + project, plus state filters)
  (b) the result is correctly normalised into JSON-serialisable dicts
  (c) the registry round-trips by name, with bad names → error result
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")


class FakeAsyncSession:
    """Minimal session — each `execute()` call pops the next queued result."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.mappings.return_value.all.return_value = []
        r.mappings.return_value.first.return_value = None
        return r


def _mappings_all(rows: list[dict]) -> MagicMock:
    r = MagicMock()
    r.mappings.return_value.all.return_value = rows
    return r


def _mappings_first(row: dict | None) -> MagicMock:
    r = MagicMock()
    r.mappings.return_value.first.return_value = row
    return r


# ---------- Tool implementations ----------


async def test_get_open_change_orders_returns_normalised_items():
    from services.assistant_tools import get_open_change_orders

    session = FakeAsyncSession()
    rows = [
        {
            "number": "CO-001",
            "title": "Slab thickness change",
            "status": "submitted",
            "initiator": "designer",
            "cost_impact_vnd": 50_000_000,
            "schedule_impact_days": 3,
            "created_at": datetime(2026, 4, 25, tzinfo=UTC),
        },
    ]
    session.push(_mappings_all(rows))

    result = await get_open_change_orders(session, organization_id=ORG_ID, project_id=PROJECT_ID)
    assert result["count"] == 1
    item = result["items"][0]
    assert item["number"] == "CO-001"
    assert item["cost_impact_vnd"] == 50_000_000
    assert item["created_at"].startswith("2026-04-25")
    # WHERE clause should bind both org and project — without those,
    # the model could drag rows from the wrong tenant.
    params = session.calls[0][1]
    assert params["org"] == str(ORG_ID)
    assert params["pid"] == str(PROJECT_ID)


async def test_get_open_change_orders_respects_limit_arg():
    from services.assistant_tools import get_open_change_orders

    session = FakeAsyncSession()
    session.push(_mappings_all([]))

    await get_open_change_orders(session, organization_id=ORG_ID, project_id=PROJECT_ID, limit=5)
    assert session.calls[0][1]["limit"] == 5


async def test_get_recent_safety_incidents_uses_lookback_window():
    from services.assistant_tools import get_recent_safety_incidents

    session = FakeAsyncSession()
    session.push(_mappings_all([]))

    await get_recent_safety_incidents(session, organization_id=ORG_ID, project_id=PROJECT_ID, days=7)
    # The "since" param should be ~7 days ago, not 30.
    since = session.calls[0][1]["since"]
    delta_days = (datetime.now(UTC) - since).days
    assert 6 <= delta_days <= 8


async def test_get_latest_estimate_returns_found_false_when_empty():
    from services.assistant_tools import get_latest_estimate

    session = FakeAsyncSession()
    session.push(_mappings_first(None))

    result = await get_latest_estimate(session, organization_id=ORG_ID, project_id=PROJECT_ID)
    assert result == {"found": False}


async def test_get_latest_estimate_returns_normalised_row_when_found():
    from services.assistant_tools import get_latest_estimate

    session = FakeAsyncSession()
    eid = uuid4()
    session.push(
        _mappings_first(
            {
                "id": eid,
                "name": "Tower A detailed",
                "version": 2,
                "status": "approved",
                "total_vnd": 1_200_000_000,
                "confidence": "detailed",
                "method": "ai_generated",
                "created_at": datetime(2026, 4, 20, tzinfo=UTC),
            }
        )
    )

    result = await get_latest_estimate(session, organization_id=ORG_ID, project_id=PROJECT_ID)
    assert result["found"] is True
    assert result["id"] == str(eid)
    assert result["status"] == "approved"
    assert result["total_vnd"] == 1_200_000_000


# ---------- Registry / dispatch ----------


def test_tool_definitions_strip_impl_for_anthropic():
    """The Anthropic Messages API rejects unknown keys on tools."""
    from services.assistant_tools import get_tool_definitions_for_anthropic

    defs = get_tool_definitions_for_anthropic()
    assert len(defs) > 0
    for d in defs:
        assert "impl" not in d
        # Required keys for Anthropic Messages tools:
        assert "name" in d
        assert "description" in d
        assert "input_schema" in d


async def test_execute_tool_call_dispatches_by_name():
    from services.assistant_tools import execute_tool_call

    session = FakeAsyncSession()
    session.push(_mappings_all([]))

    result = await execute_tool_call(
        "get_open_change_orders",
        {"limit": 3},
        session=session,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
    )
    assert result == {"count": 0, "items": []}
    assert session.calls[0][1]["limit"] == 3


async def test_execute_tool_call_returns_error_for_unknown_tool():
    """Hallucinated tool name → graceful error result so the model can
    self-correct on the next turn."""
    from services.assistant_tools import execute_tool_call

    session = FakeAsyncSession()
    result = await execute_tool_call(
        "this_tool_does_not_exist",
        {},
        session=session,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
    )
    assert "error" in result
    assert "Unknown tool" in result["error"]


async def test_execute_tool_call_returns_error_on_bad_args():
    """Bad inputs (e.g. wrong types) → error result, not exception."""
    from services.assistant_tools import execute_tool_call

    session = FakeAsyncSession()
    result = await execute_tool_call(
        "get_open_change_orders",
        {"unknown_param": "bad"},
        session=session,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
    )
    assert "error" in result
