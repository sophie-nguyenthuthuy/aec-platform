"""Punchlist status state machine (cycle AA3).

Pinned seams:
  1. STATUSES has exactly 5 members (closed set).
  2. TERMINAL_STATUSES = {verified, closed}.
  3. open → resolved is FORBIDDEN (must pass through in_progress).
  4. No status self-loop (x → x always False).
  5. closed has zero outbound transitions (true terminal).
  6. resolved → in_progress is ALLOWED (rework requested).
  7. Frozen sets — no mutation.
  8. ALLOWED_TRANSITIONS exhaustive over STATUSES (no missing keys).
"""

from __future__ import annotations

from services.punchlist_status import (
    ALLOWED_TRANSITIONS,
    STATUSES,
    TERMINAL_STATUSES,
    can_transition,
    is_terminal,
    is_valid_status,
    next_allowed,
)

# ---------- STATUSES ----------


def test_statuses_has_exactly_five_members():
    """The punchlist workflow has exactly 5 statuses. Adding a
    6th requires touching the frontend status filter, the audit
    verification trail's stuck-item rule, and the Slack digest
    grouping — pin so a sneaky add doesn't slip past three-way
    review."""
    assert len(STATUSES) == 5
    assert (
        frozenset(
            {
                "open",
                "in_progress",
                "resolved",
                "verified",
                "closed",
            }
        )
        == STATUSES
    )


def test_statuses_is_frozen():
    """frozenset so a refactor can't `STATUSES.add('archived')`
    and silently extend the closed set."""
    assert isinstance(STATUSES, frozenset)


# ---------- TERMINAL_STATUSES ----------


def test_terminal_statuses_canonical_set():
    """Only verified and closed are terminal. Resolved is NOT
    terminal — an item can be reworked back to in_progress."""
    assert frozenset({"verified", "closed"}) == TERMINAL_STATUSES


def test_terminal_statuses_is_subset_of_statuses():
    assert TERMINAL_STATUSES.issubset(STATUSES)


def test_terminal_statuses_is_frozen():
    assert isinstance(TERMINAL_STATUSES, frozenset)


# ---------- is_valid_status ----------


def test_is_valid_status_true_for_known():
    for s in ["open", "in_progress", "resolved", "verified", "closed"]:
        assert is_valid_status(s) is True


def test_is_valid_status_false_for_unknown_or_none():
    assert is_valid_status("archived") is False
    assert is_valid_status(None) is False
    assert is_valid_status("") is False


def test_is_valid_status_is_case_sensitive():
    """Pin: 'OPEN' is rejected. A refactor that lowercases input
    silently would surface here — case normalisation should be an
    explicit decision, not a quiet helper change."""
    assert is_valid_status("OPEN") is False
    assert is_valid_status("Open") is False


# ---------- is_terminal ----------


def test_is_terminal_true_for_verified_and_closed():
    assert is_terminal("verified") is True
    assert is_terminal("closed") is True


def test_is_terminal_false_for_resolved():
    """Resolved is NOT terminal — an item can be reworked back
    to in_progress. Pin so a refactor that treats resolved as
    "done" doesn't break the rework workflow OR the stuck-item
    detector (which wouldn't surface stuck-resolved items)."""
    assert is_terminal("resolved") is False


def test_is_terminal_false_for_open_and_in_progress():
    assert is_terminal("open") is False
    assert is_terminal("in_progress") is False


def test_is_terminal_false_for_unknown_or_none():
    assert is_terminal("archived") is False
    assert is_terminal(None) is False
    assert is_terminal("") is False


# ---------- can_transition ----------


def test_open_can_go_to_in_progress_or_closed():
    assert can_transition("open", "in_progress") is True
    assert can_transition("open", "closed") is True


def test_open_cannot_skip_to_resolved():
    """The cardinal forbidden transition. An item must pass
    through in_progress before being marked resolved — pin so
    a "quick close" shortcut doesn't slip past."""
    assert can_transition("open", "resolved") is False


def test_open_cannot_skip_to_verified():
    """Even worse skip. Verified requires resolved first."""
    assert can_transition("open", "verified") is False


def test_in_progress_can_go_to_resolved():
    assert can_transition("in_progress", "resolved") is True


def test_in_progress_cannot_self_loop():
    """No status can transition to itself — pin to prevent a
    refactor that re-counts in_progress events as new transitions
    (would inflate the audit trail and break the time-in-status
    metric)."""
    assert can_transition("in_progress", "in_progress") is False


def test_in_progress_cannot_jump_to_verified():
    """Verified requires resolved first — a reviewer must approve
    the resolution, can't approve work mid-flight."""
    assert can_transition("in_progress", "verified") is False


def test_resolved_can_go_to_verified():
    assert can_transition("resolved", "verified") is True


def test_resolved_can_go_back_to_in_progress():
    """Rework requested — a reviewer rejected the resolution.
    Pin so a refactor that locks resolved as forward-only doesn't
    break the rework workflow."""
    assert can_transition("resolved", "in_progress") is True


def test_resolved_cannot_skip_to_closed():
    """Closed requires verified first. Pin so an admin-side
    shortcut doesn't bypass verification."""
    assert can_transition("resolved", "closed") is False


def test_verified_can_go_to_closed():
    assert can_transition("verified", "closed") is True


def test_verified_cannot_go_back_to_in_progress():
    """Once verified, an item can only close. Re-opening for
    rework requires creating a new punchlist item — pin so a
    refactor that allows verified→in_progress doesn't conflate
    the audit trails."""
    assert can_transition("verified", "in_progress") is False


def test_closed_is_truly_terminal():
    """Closed has zero outbound transitions. A re-opened item
    becomes a NEW item — pin so a refactor that allows
    closed→in_progress doesn't conflate the two."""
    for to in STATUSES:
        assert can_transition("closed", to) is False


def test_no_status_self_loops():
    """Pin: no `x → x` transition is allowed. Self-loops would
    inflate the audit trail with no-op events and break the
    time-in-status metric."""
    for status in STATUSES:
        assert can_transition(status, status) is False


def test_can_transition_false_for_unknown_inputs():
    """Defensive: None / unknown status → False, no raise."""
    assert can_transition(None, "open") is False
    assert can_transition("open", None) is False
    assert can_transition("archived", "open") is False
    assert can_transition("open", "archived") is False
    assert can_transition(None, None) is False


# ---------- next_allowed ----------


def test_next_allowed_open():
    assert next_allowed("open") == frozenset({"in_progress", "closed"})


def test_next_allowed_in_progress():
    assert next_allowed("in_progress") == frozenset({"resolved"})


def test_next_allowed_resolved():
    assert next_allowed("resolved") == frozenset({"verified", "in_progress"})


def test_next_allowed_verified():
    assert next_allowed("verified") == frozenset({"closed"})


def test_next_allowed_closed_is_empty():
    """Closed has no outbound transitions — terminal."""
    assert next_allowed("closed") == frozenset()


def test_next_allowed_unknown_returns_empty():
    assert next_allowed("archived") == frozenset()
    assert next_allowed(None) == frozenset()
    assert next_allowed("") == frozenset()


# ---------- ALLOWED_TRANSITIONS map invariants ----------


def test_allowed_transitions_covers_every_status():
    """Every status appears as a key in ALLOWED_TRANSITIONS — the
    map is exhaustive over the closed status set. A refactor that
    adds a new status to STATUSES without adding a transition
    entry would surface here."""
    assert frozenset(ALLOWED_TRANSITIONS.keys()) == STATUSES


def test_allowed_transitions_targets_are_valid_statuses():
    """Every target status is a member of STATUSES — the map
    can't reference a status outside the closed set."""
    for from_status, targets in ALLOWED_TRANSITIONS.items():
        for to in targets:
            assert to in STATUSES, f"{from_status} → {to} targets unknown status"


def test_closed_has_no_outbound_transitions():
    """`closed` is the only strict no-outbound terminal — pin so
    a refactor that adds e.g. `closed → archived` surfaces here.
    `verified` is also in TERMINAL_STATUSES (semantic "done" for
    the stuck-detector) but has one outbound (`verified → closed`)
    representing archive."""
    assert ALLOWED_TRANSITIONS["closed"] == frozenset()


def test_verified_has_only_one_outbound_to_closed():
    """`verified` has exactly one outbound transition: to `closed`.
    Pin so a refactor that adds e.g. `verified → in_progress`
    (treating verified as reworkable) surfaces here — verified
    means a reviewer has signed off; once signed, the only
    movement is into the archived state."""
    assert ALLOWED_TRANSITIONS["verified"] == frozenset({"closed"})


def test_non_terminal_statuses_have_outbound_transitions():
    """Pin the inverse: every non-terminal status has at least
    one outbound transition (else it'd be a stuck status that
    isn't in TERMINAL_STATUSES — a workflow bug)."""
    for status in STATUSES - TERMINAL_STATUSES:
        assert len(ALLOWED_TRANSITIONS[status]) > 0, f"non-terminal status {status} has no outbound transitions"
