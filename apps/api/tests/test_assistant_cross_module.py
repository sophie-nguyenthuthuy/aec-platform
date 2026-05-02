"""Phase 6: cross-module assistant context tests.

`build_project_context` was extended from a 4-module roll-up
(pulse / drawbridge / handover / siteeye) to all 14 modules. These
tests pin two contracts:

  1. The returned dict includes a top-level key for every module the
     LLM's system prompt references — so questions like "what's
     blocking handover on Tower A?" can be answered by inspecting
     `context["punchlist"]["high_severity_open_items"]` etc.

  2. `_default_sources` produces a citation chip for every module
     that has non-zero signal. A regression here would silently
     drop the user's "click through to the source" affordance.

We don't go through the LangChain stack — that's Tier 4 / `make
eval-codeguard` territory. Here we drive `build_project_context`
directly against a stubbed `AsyncSession` and assert structurally on
the dict.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


# ---------- Stub session that pops execute() results in order. ----------


class _FakeSession:
    """Minimal async-session stand-in. Each `execute()` call pops the
    next entry from the queue and wraps it in a Result-shaped MagicMock
    that handles `.scalar_one()`, `.mappings().first()`, and
    `.mappings().all()` — the three shapes `build_project_context`
    actually uses."""

    def __init__(self, results: list):
        self._results = list(results)

    async def execute(self, *_a, **_kw):
        nxt = self._results.pop(0) if self._results else None
        result = MagicMock()
        # scalar_one() — used for COUNT(*) helpers.
        result.scalar_one.return_value = nxt if not isinstance(nxt, dict | list) else 0
        # mappings().first() — used for one-row aggregate SELECTs.
        # mappings().all()   — used for the activity feed UNION ALL.
        mappings = MagicMock()
        if isinstance(nxt, list):
            mappings.first.return_value = nxt[0] if nxt else None
            mappings.all.return_value = nxt
        elif isinstance(nxt, dict):
            mappings.first.return_value = nxt
            mappings.all.return_value = [nxt]
        else:
            mappings.first.return_value = None
            mappings.all.return_value = []
        result.mappings.return_value = mappings
        return result


# ---------- Fixtures ----------


@pytest.fixture
def project_id():
    return uuid4()


@pytest.fixture
def org_id():
    return uuid4()


@pytest.fixture
def project_row(project_id, org_id):
    """Stand-in for a `models.core.Project` ORM row. SimpleNamespace is
    enough — `build_project_context` only reads attributes, never
    invokes session-bound methods."""
    return SimpleNamespace(
        id=project_id,
        organization_id=org_id,
        name="Tower A",
        type="commercial",
        status="construction",
        budget_vnd=50_000_000_000,
        area_sqm=12_500.0,
        floors=18,
        address={"city": "HCMC"},
        start_date=date(2026, 1, 1),
        end_date=date(2027, 6, 30),
    )


def _expected_query_queue(project_row, *, with_signal: bool):
    """Mirrors the order of `session.execute()` calls in
    `build_project_context`. If a future refactor reorders the helpers,
    adjust this list — the test failure will name which scalar shifted.
    """
    if with_signal:
        return [
            project_row,  # SELECT Project
            [  # activity feed UNION ALL → mappings().all()
                {
                    "module": "pulse",
                    "event_type": "task_completed",
                    "title": "Task done: Pour slab",
                    "timestamp": datetime(2026, 4, 25, tzinfo=UTC),
                },
                {
                    "module": "punchlist",
                    "event_type": "list_signed_off",
                    "title": "Punch list signed off: Lobby",
                    "timestamp": datetime(2026, 4, 24, tzinfo=UTC),
                },
            ],
            12,  # pulse_open_tasks
            3,  # pulse_open_cos
            5,  # drawbridge_open_rfis
            1,  # drawbridge_unresolved_conflicts
            7,  # handover_open_defects
            2,  # siteeye_open_incidents
            4,  # costpulse_estimate_count
            1,  # costpulse_approved_count
            {"id": uuid4(), "total_vnd": 48_000_000_000},  # costpulse_latest
            {"id": uuid4(), "status": "won", "total_fee_vnd": 5_500_000_000},  # winwork_row
            6,  # codeguard_check_count
            2,  # codeguard_checklist_count
            3,  # schedulepilot_schedule_count
            {"behind": 4, "max_slip": 7, "avg_pct": 47.5, "activity_count": 22},  # schedulepilot_row
            {
                "open_count": 8,
                "revise_count": 2,
                "approved_count": 14,
                "designer_court": 3,
                "contractor_court": 5,
            },  # submittals_row
            18,  # dailylog_log_count
            {"open_count": 11, "high_count": 4},  # dailylog_obs_row
            {
                "total_count": 9,
                "open_count": 3,
                "approved_count": 5,
                "total_cost": 320_000_000,
                "total_days": 6,
            },  # changeorder_row
            2,  # changeorder_pending_candidates
            {"list_count": 3, "open_list_count": 1, "signed_off_count": 2},  # punchlist_list_row
            {"total_items": 47, "open_items": 12, "verified_items": 30, "high_open": 4},  # punchlist_item_row
        ]
    # No-signal case: every module returns zeros / Nones.
    return [
        project_row,
        [],  # activity feed empty
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        None,
        None,  # winwork_row None
        0,
        0,
        0,
        None,
        None,  # submittals_row None
        0,
        None,
        None,  # changeorder_row None
        0,
        None,
        None,
    ]


# ---------- Tests ----------


async def test_build_project_context_includes_all_14_module_keys(project_row, project_id, org_id):
    """Pin: every module the LLM's system prompt references appears as
    a top-level key in the returned dict."""
    from services.assistant import build_project_context

    session = _FakeSession(_expected_query_queue(project_row, with_signal=True))
    # Patch the project lookup to return our SimpleNamespace.
    session._results.insert(0, project_row)  # one extra: select(Project)
    # The first list entry is consumed by the SELECT Project — pop the
    # duplicate we just inserted so the queue lines up.
    session._results.pop(1)

    ctx = await build_project_context(
        session,  # type: ignore[arg-type]
        organization_id=org_id,
        project_id=project_id,
    )

    # Top-level shape — one key per module + project + activity feed.
    expected_keys = {
        "project",
        "winwork",
        "costpulse",
        "pulse",
        "drawbridge",
        "handover",
        "siteeye",
        "codeguard",
        "schedulepilot",
        "submittals",
        "dailylog",
        "changeorder",
        "punchlist",
        "recent_activity",
    }
    assert expected_keys.issubset(set(ctx.keys())), f"missing keys: {expected_keys - set(ctx.keys())}"

    # Spot-check a value from each new module so we know we're not
    # just emitting empty stubs.
    assert ctx["pulse"]["open_tasks"] == 12
    assert ctx["winwork"]["proposal_status"] == "won"
    assert ctx["costpulse"]["latest_total_vnd"] == 48_000_000_000
    assert ctx["codeguard"]["compliance_check_count"] == 6
    assert ctx["schedulepilot"]["overall_slip_days"] == 7
    assert ctx["schedulepilot"]["behind_schedule_count"] == 4
    assert ctx["submittals"]["revise_resubmit_count"] == 2
    assert ctx["submittals"]["contractor_court_count"] == 5
    assert ctx["dailylog"]["high_severity_observation_count"] == 4
    assert ctx["changeorder"]["pending_candidates"] == 2
    assert ctx["changeorder"]["total_cost_impact_vnd"] == 320_000_000
    assert ctx["punchlist"]["high_severity_open_items"] == 4
    assert ctx["punchlist"]["verified_items"] == 30

    # Activity feed includes the new event types.
    assert any(a["event_type"] == "list_signed_off" for a in ctx["recent_activity"])


async def test_default_sources_emits_chip_per_active_module(project_id):
    """Pin: every module with non-zero signal yields one citation chip.

    A regression that drops a chip would silently degrade the user's
    "click through to source" affordance — they'd lose the ability to
    drill from an answer down into (e.g.) the punch list page.
    """
    from services.assistant import _default_sources

    # Synthetic context with signal in every Phase 6 module so each
    # chip's branch fires.
    ctx = {
        "project": {"id": str(project_id), "name": "Tower A"},
        "winwork": {"proposal_id": str(uuid4()), "proposal_status": "won"},
        "costpulse": {"estimate_count": 4, "approved_count": 1},
        "pulse": {"open_tasks": 12, "open_change_orders": 3},
        "drawbridge": {"open_rfi_count": 5, "unresolved_conflict_count": 1},
        "handover": {"open_defect_count": 7},
        "siteeye": {"open_safety_incident_count": 2},
        "codeguard": {"compliance_check_count": 6, "permit_checklist_count": 2},
        "schedulepilot": {
            "schedule_count": 3,
            "activity_count": 22,
            "behind_schedule_count": 4,
            "overall_slip_days": 7,
        },
        "submittals": {
            "open_count": 8,
            "revise_resubmit_count": 2,
            "approved_count": 14,
            "designer_court_count": 3,
            "contractor_court_count": 5,
        },
        "dailylog": {
            "log_count_30d": 18,
            "open_observation_count": 11,
            "high_severity_observation_count": 4,
        },
        "changeorder": {
            "total_count": 9,
            "open_count": 3,
            "approved_count": 5,
            "pending_candidates": 2,
            "total_cost_impact_vnd": 320_000_000,
            "total_schedule_impact_days": 6,
        },
        "punchlist": {
            "list_count": 3,
            "open_list_count": 1,
            "signed_off_list_count": 2,
            "total_items": 47,
            "open_items": 12,
            "verified_items": 30,
            "high_severity_open_items": 4,
        },
        "recent_activity": [{"module": "pulse", "event_type": "x", "title": "y", "timestamp": None}],
    }

    sources = _default_sources(project_id, ctx)
    modules = [s.module for s in sources]

    # Every expected module produces a chip.
    expected = {
        "pulse",
        "drawbridge",
        "handover",
        "siteeye",
        "winwork",
        "costpulse",
        "codeguard",
        "schedulepilot",
        "submittals",
        "dailylog",
        "changeorder",
        "punchlist",
        "activity",
    }
    assert set(modules) == expected, f"diff: {expected ^ set(modules)}"

    # Spot-check a chip label that depends on Phase-6 logic — the
    # schedulepilot chip should mention slip and behind-count.
    sched_chip = next(s for s in sources if s.module == "schedulepilot")
    assert "slip 7d" in sched_chip.label
    assert "4 hoạt động trễ" in sched_chip.label

    # The submittals chip should mention ball-in-court.
    sub_chip = next(s for s in sources if s.module == "submittals")
    assert "designer 3" in sub_chip.label
    assert "contractor 5" in sub_chip.label


async def test_default_sources_skips_modules_with_zero_signal(project_id):
    """Inverse contract — no signal, no chip. A bidding-phase project
    shouldn't have a Punchlist chip cluttering the citation strip."""
    from services.assistant import _default_sources

    ctx = {
        "project": {"id": str(project_id), "name": "Tower A"},
        # Only winwork has signal — everything else is empty/zero.
        "winwork": {"proposal_id": str(uuid4()), "proposal_status": "submitted"},
        "costpulse": {"estimate_count": 0, "approved_count": 0},
        "pulse": {"open_tasks": 0, "open_change_orders": 0},
        "drawbridge": {"open_rfi_count": 0, "unresolved_conflict_count": 0},
        "handover": {"open_defect_count": 0},
        "siteeye": {"open_safety_incident_count": 0},
        "codeguard": {"compliance_check_count": 0, "permit_checklist_count": 0},
        "schedulepilot": {"schedule_count": 0, "activity_count": 0},
        "submittals": {"open_count": 0, "revise_resubmit_count": 0, "approved_count": 0},
        "dailylog": {"log_count_30d": 0, "high_severity_observation_count": 0},
        "changeorder": {"total_count": 0, "pending_candidates": 0},
        "punchlist": {"list_count": 0, "total_items": 0},
        "recent_activity": [],
    }

    modules = [s.module for s in _default_sources(project_id, ctx)]
    # Only winwork chip should appear — the proposal exists, even
    # though the project hasn't kicked off any work yet.
    assert modules == ["winwork"]
