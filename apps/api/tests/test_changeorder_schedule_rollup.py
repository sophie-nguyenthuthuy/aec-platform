"""Unit tests for the ChangeOrder → SchedulePilot rollup service."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from services.changeorder_schedule_rollup import apply_change_order_to_schedule

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")


class _Session:
    def __init__(self) -> None:
        self.executes: list[tuple[str, dict]] = []
        self._queue: list[Any] = []

    def push(self, result: Any) -> None:
        self._queue.append(result)

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        self.executes.append((str(stmt), params or {}))
        if self._queue:
            return self._queue.pop(0)
        r = MagicMock()
        r.one_or_none.return_value = None
        r.scalar_one.return_value = 0
        r.all.return_value = []
        return r


def _row(**fields: Any) -> SimpleNamespace:
    return SimpleNamespace(_mapping=fields)


def _result(row: SimpleNamespace | None = None, rows: list | None = None) -> MagicMock:
    r = MagicMock()
    r.one.return_value = row
    r.one_or_none.return_value = row
    r.first.return_value = row
    r.all.return_value = rows or ([row] if row is not None else [])
    return r


# ============================================================================


async def test_404_when_co_missing():
    s = _Session()
    s.push(_result(None))
    with pytest.raises(ValueError, match="not found"):
        await apply_change_order_to_schedule(s, organization_id=ORG_ID, change_order_id=uuid4())


async def test_rejects_co_in_unsupported_status():
    s = _Session()
    s.push(_result(_row(id=uuid4(), status="draft", project_id=uuid4())))
    with pytest.raises(ValueError, match="status=draft"):
        await apply_change_order_to_schedule(s, organization_id=ORG_ID, change_order_id=uuid4())


async def test_no_line_items_returns_zero_counters():
    """A CO with no schedule-impact line items short-circuits without
    inserting an audit row."""
    s = _Session()
    co_id = uuid4()
    s.push(_result(_row(id=co_id, status="executed", project_id=uuid4())))
    s.push(_result(rows=[]))  # no line items

    out = await apply_change_order_to_schedule(s, organization_id=ORG_ID, change_order_id=co_id)
    assert out["activities_updated"] == 0
    assert out["line_items_seen"] == 0
    # No audit insert happened — only 2 statements ran (SELECT co + SELECT lines).
    assert len(s.executes) == 2


async def test_idempotent_when_audit_row_already_exists():
    s = _Session()
    co_id, aid, li_id = uuid4(), uuid4(), uuid4()
    s.push(_result(_row(id=co_id, status="executed", project_id=uuid4())))
    s.push(
        _result(
            rows=[
                _row(id=li_id, schedule_activity_id=aid, schedule_impact_days=5, description="Add curtain wall section")
            ]
        )
    )
    # Idempotency check — exists.
    s.push(_result(_row(exists=1)))

    out = await apply_change_order_to_schedule(s, organization_id=ORG_ID, change_order_id=co_id)
    assert out["activities_updated"] == 0
    assert out["skipped"] == [{"reason": "already_applied", "line_item_id": None}]


async def test_applies_impact_to_each_activity_and_records_audit():
    s = _Session()
    co_id = uuid4()
    aid_a, aid_b = uuid4(), uuid4()
    li_a, li_b = uuid4(), uuid4()

    # 1: SELECT co; 2: SELECT line items
    s.push(_result(_row(id=co_id, status="executed", project_id=uuid4())))
    s.push(
        _result(
            rows=[
                _row(id=li_a, schedule_activity_id=aid_a, schedule_impact_days=5, description="Beam upgrade"),
                _row(id=li_b, schedule_activity_id=aid_b, schedule_impact_days=3, description="Curtain-wall scope"),
            ]
        )
    )
    # 3: idempotency SELECT — none
    s.push(_result(None))

    # For each line item, the helper does:
    #   4: SELECT activity row
    #   5: UPDATE activity
    s.push(
        _result(
            _row(
                id=aid_a,
                planned_finish=date(2026, 5, 15),
                planned_duration_days=20,
                baseline_finish=date(2026, 5, 15),
                baseline_set_at=None,
            )
        )
    )
    s.push(_result(None))  # UPDATE activity_a
    s.push(
        _result(
            _row(
                id=aid_b,
                planned_finish=date(2026, 6, 1),
                planned_duration_days=10,
                baseline_finish=date(2026, 6, 1),
                baseline_set_at=None,
            )
        )
    )
    s.push(_result(None))  # UPDATE activity_b
    # Final: INSERT into change_order_approvals (audit row)
    s.push(_result(None))

    out = await apply_change_order_to_schedule(s, organization_id=ORG_ID, change_order_id=co_id, actor_id=uuid4())
    assert out["activities_updated"] == 2
    assert out["line_items_seen"] == 2
    assert out["skipped"] == []

    # Audit row should land with to_status='executed_schedule'.
    audit_inserts = [(sql, p) for (sql, p) in s.executes if "INSERT INTO change_order_approvals" in sql]
    assert len(audit_inserts) == 1
    assert "executed_schedule" in audit_inserts[0][0]


async def test_orphan_line_item_skipped_with_reason():
    """A line item pointing at a deleted activity is skipped, NOT exploded."""
    s = _Session()
    co_id = uuid4()
    li = uuid4()
    ghost = uuid4()

    s.push(_result(_row(id=co_id, status="approved", project_id=uuid4())))
    s.push(_result(rows=[_row(id=li, schedule_activity_id=ghost, schedule_impact_days=2, description="Orphan")]))
    s.push(_result(None))  # idempotency none
    s.push(_result(None))  # SELECT activity returns None
    s.push(_result(None))  # audit insert

    out = await apply_change_order_to_schedule(s, organization_id=ORG_ID, change_order_id=co_id)
    assert out["activities_updated"] == 0
    assert out["skipped"] == [{"reason": "activity_missing", "line_item_id": str(li)}]
