"""Unit tests for SchedulePilot's pure-Python CPM core.

The LLM narration is intentionally NOT covered here — those tests would
need network/API-key plumbing. The CPM forward+backward pass is the
piece that has actual algorithmic risk, so it's the piece to lock down.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest

from ml.pipelines.schedulepilot import compute_critical_path, run_risk_assessment


def _act(
    aid: str,
    code: str,
    *,
    start: date | None = None,
    finish: date | None = None,
    duration: int | None = None,
    pct: float = 0.0,
    status: str = "not_started",
    baseline_finish: date | None = None,
    actual_finish: date | None = None,
):
    return {
        "id": UUID(aid),
        "code": code,
        "name": code,
        "activity_type": "task",
        "planned_start": start,
        "planned_finish": finish,
        "planned_duration_days": duration,
        "baseline_start": None,
        "baseline_finish": baseline_finish or finish,
        "actual_start": None,
        "actual_finish": actual_finish,
        "percent_complete": pct,
        "status": status,
    }


def _dep(pred: str, succ: str, *, lag: int = 0, kind: str = "fs"):
    return {
        "predecessor_id": UUID(pred),
        "successor_id": UUID(succ),
        "relationship_type": kind,
        "lag_days": lag,
    }


def test_empty_schedule_returns_empty_path():
    out = compute_critical_path([], [])
    assert out["critical_path_codes"] == []
    assert out["overall_slip_days"] == 0
    assert out["input_summary"] == {"activity_count": 0}


def test_linear_chain_marks_every_activity_critical():
    """A → B → C, all FS, all 5-day, no slack possible."""
    a = "00000000-0000-0000-0000-000000000001"
    b = "00000000-0000-0000-0000-000000000002"
    c = "00000000-0000-0000-0000-000000000003"
    activities = [
        _act(a, "A", duration=5),
        _act(b, "B", duration=5),
        _act(c, "C", duration=5),
    ]
    deps = [_dep(a, b), _dep(b, c)]
    out = compute_critical_path(activities, deps)
    assert out["critical_path_codes"] == ["A", "B", "C"]
    assert out["input_summary"]["project_duration_days"] == 15
    assert out["input_summary"]["dependency_count"] == 2


def test_diamond_picks_longer_arm_as_critical():
    """A splits to B (3d) and C (10d), both join D. Only A,C,D should be critical."""
    a = "00000000-0000-0000-0000-000000000001"
    b = "00000000-0000-0000-0000-000000000002"
    c = "00000000-0000-0000-0000-000000000003"
    d = "00000000-0000-0000-0000-000000000004"
    activities = [
        _act(a, "A", duration=2),
        _act(b, "B", duration=3),
        _act(c, "C", duration=10),
        _act(d, "D", duration=2),
    ]
    deps = [_dep(a, b), _dep(a, c), _dep(b, d), _dep(c, d)]
    out = compute_critical_path(activities, deps)
    # Order is topological — A first, then C (longer arm), then D.
    assert out["critical_path_codes"] == ["A", "C", "D"]
    # B has 7 days of slack so it must NOT be on the path.
    assert "B" not in out["critical_path_codes"]
    # Project duration = max EF = A(2) + C(10) + D(2) = 14
    assert out["input_summary"]["project_duration_days"] == 14


def test_lag_widens_predecessor_finish():
    """A (5d) FS+3 → B (5d): start of B is at day 8, end at 13."""
    a = "00000000-0000-0000-0000-000000000001"
    b = "00000000-0000-0000-0000-000000000002"
    activities = [_act(a, "A", duration=5), _act(b, "B", duration=5)]
    deps = [_dep(a, b, lag=3)]
    out = compute_critical_path(activities, deps)
    assert out["critical_path_codes"] == ["A", "B"]
    assert out["input_summary"]["project_duration_days"] == 13


def test_orphan_dependency_is_ignored():
    """Dep references an activity that doesn't exist — should be silently skipped
    (e.g., activity was deleted before the dep was cleaned up)."""
    a = "00000000-0000-0000-0000-000000000001"
    ghost = "00000000-0000-0000-0000-000000000099"
    activities = [_act(a, "A", duration=5)]
    deps = [_dep(a, ghost)]
    out = compute_critical_path(activities, deps)
    assert out["critical_path_codes"] == ["A"]
    assert out["input_summary"]["dependency_count"] == 1


def test_status_counters_count_correctly():
    a = "00000000-0000-0000-0000-000000000001"
    b = "00000000-0000-0000-0000-000000000002"
    c = "00000000-0000-0000-0000-000000000003"
    activities = [
        _act(a, "A", duration=5, status="complete", pct=100),
        _act(b, "B", duration=5, status="in_progress", pct=40),
        _act(c, "C", duration=5, status="not_started"),
    ]
    out = compute_critical_path(activities, [_dep(a, b), _dep(b, c)])
    assert out["input_summary"]["complete"] == 1
    assert out["input_summary"]["in_progress"] == 1


@pytest.mark.asyncio
async def test_run_risk_assessment_skips_llm_for_empty_progress():
    """No in-progress activities + force=False → no LLM call, deterministic empty narration."""
    a = "00000000-0000-0000-0000-000000000001"
    activities = [_act(a, "A", duration=5, status="not_started")]
    out = await run_risk_assessment(activities, [], force=False)
    assert out["top_risks"] == []
    assert "No in-progress" in (out["notes"] or "")
    assert out["critical_path_codes"] == ["A"]


@pytest.mark.asyncio
async def test_run_risk_assessment_returns_input_summary():
    out = await run_risk_assessment([], [])
    assert out["overall_slip_days"] == 0
    assert out["critical_path_codes"] == []
    assert out["input_summary"] == {"activity_count": 0}
