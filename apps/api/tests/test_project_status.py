"""Project status state machine (cycle YY1).

Pinned seams:
  1. STATUSES has exactly 6 members.
  2. TERMINAL = {archived, cancelled}.
  3. ACTIVE = {planned, in_progress}.
  4. on_hold → in_progress allowed (resume).
  5. archived → in_progress FORBIDDEN.
  6. completed → in_progress FORBIDDEN (one-way).
  7. on_hold → completed FORBIDDEN (must resume first).
  8. No self-loops.
  9. ALLOWED_TRANSITIONS exhaustive over STATUSES.
"""

from __future__ import annotations

from services.project_status import (
    ACTIVE_STATUSES,
    ALLOWED_TRANSITIONS,
    STATUSES,
    TERMINAL_STATUSES,
    can_transition,
    is_active,
    is_terminal,
    is_valid_status,
    next_allowed,
)

# ---------- STATUSES ----------


def test_statuses_has_exactly_six_members():
    assert len(STATUSES) == 6
    assert (
        frozenset(
            {
                "planned",
                "in_progress",
                "on_hold",
                "completed",
                "archived",
                "cancelled",
            }
        )
        == STATUSES
    )


def test_statuses_is_frozen():
    assert isinstance(STATUSES, frozenset)


# ---------- TERMINAL_STATUSES ----------


def test_terminal_statuses_canonical():
    assert frozenset({"archived", "cancelled"}) == TERMINAL_STATUSES


def test_terminal_subset_of_statuses():
    assert TERMINAL_STATUSES.issubset(STATUSES)


# ---------- ACTIVE_STATUSES ----------


def test_active_statuses_canonical():
    """Cardinal pin: ACTIVE = planned + in_progress. Used by
    the dashboard's "active projects" KPI."""
    assert frozenset({"planned", "in_progress"}) == ACTIVE_STATUSES


def test_active_subset_of_statuses():
    assert ACTIVE_STATUSES.issubset(STATUSES)


def test_active_disjoint_from_terminal():
    """Pin: active and terminal are disjoint sets."""
    assert ACTIVE_STATUSES.isdisjoint(TERMINAL_STATUSES)


def test_on_hold_not_active():
    """Pin: on_hold is NOT active (paused, not currently working).
    Defends against dashboards counting on-hold as active."""
    assert "on_hold" not in ACTIVE_STATUSES
    assert is_active("on_hold") is False


def test_completed_not_active():
    """completed is in-flight-done but not actively-working."""
    assert is_active("completed") is False


# ---------- is_valid_status ----------


def test_valid_for_known():
    for s in [
        "planned",
        "in_progress",
        "on_hold",
        "completed",
        "archived",
        "cancelled",
    ]:
        assert is_valid_status(s) is True


def test_invalid_for_unknown():
    assert is_valid_status("draft") is False
    assert is_valid_status("PLANNED") is False  # case-sensitive
    assert is_valid_status(None) is False


# ---------- is_terminal / is_active ----------


def test_is_terminal_archived_cancelled():
    assert is_terminal("archived") is True
    assert is_terminal("cancelled") is True


def test_is_terminal_false_for_active_states():
    assert is_terminal("planned") is False
    assert is_terminal("in_progress") is False
    assert is_terminal("on_hold") is False


def test_is_terminal_false_for_completed():
    """Pin: completed is NOT terminal (has outbound to archived)."""
    assert is_terminal("completed") is False


def test_is_active_for_planned_and_in_progress():
    assert is_active("planned") is True
    assert is_active("in_progress") is True


def test_is_active_false_for_others():
    for s in ["on_hold", "completed", "archived", "cancelled"]:
        assert is_active(s) is False, f"{s} should not be active"


# ---------- can_transition — happy paths ----------


def test_planned_to_in_progress():
    assert can_transition("planned", "in_progress") is True


def test_planned_to_cancelled():
    assert can_transition("planned", "cancelled") is True


def test_in_progress_to_on_hold():
    assert can_transition("in_progress", "on_hold") is True


def test_in_progress_to_completed():
    assert can_transition("in_progress", "completed") is True


def test_in_progress_to_cancelled():
    assert can_transition("in_progress", "cancelled") is True


def test_on_hold_to_in_progress_resume():
    """Cardinal pin: resume after pause."""
    assert can_transition("on_hold", "in_progress") is True


def test_on_hold_to_cancelled():
    """Cancel from hold without resuming."""
    assert can_transition("on_hold", "cancelled") is True


def test_completed_to_archived():
    assert can_transition("completed", "archived") is True


# ---------- can_transition — forbidden ----------


def test_planned_cannot_skip_to_completed():
    """Cardinal pin: must enter in_progress before completed."""
    assert can_transition("planned", "completed") is False


def test_planned_cannot_skip_to_archived():
    assert can_transition("planned", "archived") is False


def test_planned_cannot_skip_to_on_hold():
    """Pin: can't put a not-yet-started project on hold —
    must start first."""
    assert can_transition("planned", "on_hold") is False


def test_on_hold_cannot_skip_to_completed():
    """Cardinal pin: must resume to in_progress before completing.
    Defends against completing a project from on-hold without
    an active work phase being recorded."""
    assert can_transition("on_hold", "completed") is False


def test_on_hold_cannot_skip_to_archived():
    assert can_transition("on_hold", "archived") is False


def test_completed_cannot_go_back_to_in_progress():
    """Cardinal pin: completed is one-way. Re-opening a completed
    project = create amendment, NOT reopen."""
    assert can_transition("completed", "in_progress") is False


def test_completed_cannot_go_to_cancelled():
    assert can_transition("completed", "cancelled") is False


def test_archived_is_truly_terminal():
    """Cardinal pin: archived → anything FORBIDDEN. No
    unarchive."""
    for to in STATUSES:
        assert can_transition("archived", to) is False, f"archived should not transition to {to}"


def test_cancelled_is_truly_terminal():
    for to in STATUSES:
        assert can_transition("cancelled", to) is False


def test_no_self_loops():
    for status in STATUSES:
        assert can_transition(status, status) is False


def test_can_transition_defensive():
    assert can_transition(None, "in_progress") is False
    assert can_transition("planned", None) is False
    assert can_transition("unknown", "planned") is False
    assert can_transition("planned", "unknown") is False


# ---------- next_allowed ----------


def test_next_allowed_planned():
    assert next_allowed("planned") == frozenset({"in_progress", "cancelled"})


def test_next_allowed_in_progress():
    assert next_allowed("in_progress") == frozenset(
        {
            "on_hold",
            "completed",
            "cancelled",
        }
    )


def test_next_allowed_on_hold():
    assert next_allowed("on_hold") == frozenset({"in_progress", "cancelled"})


def test_next_allowed_completed():
    assert next_allowed("completed") == frozenset({"archived"})


def test_next_allowed_archived_empty():
    assert next_allowed("archived") == frozenset()


def test_next_allowed_cancelled_empty():
    assert next_allowed("cancelled") == frozenset()


def test_next_allowed_unknown_empty():
    assert next_allowed("unknown") == frozenset()
    assert next_allowed(None) == frozenset()


# ---------- ALLOWED_TRANSITIONS invariants ----------


def test_transitions_cover_every_status():
    assert frozenset(ALLOWED_TRANSITIONS.keys()) == STATUSES


def test_transition_targets_valid():
    for from_s, targets in ALLOWED_TRANSITIONS.items():
        for to in targets:
            assert to in STATUSES, f"{from_s} → {to} targets unknown status"


def test_terminal_no_outbound():
    for status in TERMINAL_STATUSES:
        assert ALLOWED_TRANSITIONS[status] == frozenset()


def test_non_terminal_has_outbound():
    for status in STATUSES - TERMINAL_STATUSES:
        assert len(ALLOWED_TRANSITIONS[status]) > 0


# ---------- Workflow quartet alignment ----------


def test_quartet_pattern_consistency():
    """Cross-cycle pin: this module follows the same shape as
    AA3 (punchlist), BB1 (submittal), CC1 (change order). 6
    statuses; closed terminal set; closed transition map."""
    from services.change_order_status import STATUSES as CO_STATUSES
    from services.punchlist_status import STATUSES as PL_STATUSES
    from services.submittal_status import STATUSES as SM_STATUSES

    # Punchlist has 5; submittal 6; change order 6. Project (this) 6.
    # Pin: count alignment with submittal + change_order.
    assert len(STATUSES) == 6
    assert len(SM_STATUSES) == 6
    assert len(CO_STATUSES) == 6
    # Punchlist family is 5 (different shape).
    assert len(PL_STATUSES) == 5
