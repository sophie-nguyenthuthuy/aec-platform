"""Submittal review state machine (cycle BB1).

Pinned seams:
  1. STATUSES has exactly 6 members (closed set).
  2. TERMINAL_STATUSES = {approved, rejected}.
  3. draft → approved is FORBIDDEN (must go through submission).
  4. revision_requested → submitted IS allowed (resubmission loop).
  5. under_review → submitted is FORBIDDEN (reviewer must commit).
  6. approved and rejected are strict no-outbound terminals.
  7. No status self-loop.
  8. ALLOWED_TRANSITIONS exhaustive over STATUSES.
"""

from __future__ import annotations

from services.submittal_status import (
    ALLOWED_TRANSITIONS,
    STATUSES,
    TERMINAL_STATUSES,
    can_transition,
    is_terminal,
    is_valid_status,
    next_allowed,
)


# ---------- STATUSES ----------


def test_statuses_has_exactly_six_members():
    """The submittal workflow has exactly 6 statuses. Adding a
    7th (e.g. "withdrawn") requires touching the frontend filter
    + the stuck-review detector + the deadline-overrun Slack
    alert. Pin so a sneaky add doesn't slip past three-way review."""
    assert len(STATUSES) == 6
    assert STATUSES == frozenset(
        {
            "draft",
            "submitted",
            "under_review",
            "revision_requested",
            "approved",
            "rejected",
        }
    )


def test_statuses_is_frozen():
    assert isinstance(STATUSES, frozenset)


# ---------- TERMINAL_STATUSES ----------


def test_terminal_statuses_canonical_set():
    """Only approved and rejected are terminal. Revision_requested
    is NOT terminal — author can resubmit."""
    assert TERMINAL_STATUSES == frozenset({"approved", "rejected"})


def test_terminal_statuses_is_subset_of_statuses():
    assert TERMINAL_STATUSES.issubset(STATUSES)


def test_terminal_statuses_is_frozen():
    assert isinstance(TERMINAL_STATUSES, frozenset)


# ---------- is_valid_status ----------


def test_is_valid_status_true_for_known():
    for s in [
        "draft",
        "submitted",
        "under_review",
        "revision_requested",
        "approved",
        "rejected",
    ]:
        assert is_valid_status(s) is True


def test_is_valid_status_false_for_unknown_or_none():
    assert is_valid_status("withdrawn") is False
    assert is_valid_status("DRAFT") is False  # case-sensitive
    assert is_valid_status(None) is False
    assert is_valid_status("") is False


# ---------- is_terminal ----------


def test_is_terminal_true_for_approved_and_rejected():
    assert is_terminal("approved") is True
    assert is_terminal("rejected") is True


def test_is_terminal_false_for_revision_requested():
    """revision_requested is NOT terminal — author can resubmit.
    Pin so a refactor that treats revision_requested as "done"
    doesn't break the resubmission loop OR the stuck-review
    detector."""
    assert is_terminal("revision_requested") is False


def test_is_terminal_false_for_active_states():
    assert is_terminal("draft") is False
    assert is_terminal("submitted") is False
    assert is_terminal("under_review") is False


def test_is_terminal_false_for_unknown_or_none():
    assert is_terminal(None) is False
    assert is_terminal("") is False
    assert is_terminal("withdrawn") is False


# ---------- can_transition ----------


def test_draft_can_go_to_submitted():
    assert can_transition("draft", "submitted") is True


def test_draft_cannot_skip_to_under_review():
    """Reviewer can't pull a draft directly into review. Pin the
    submission step as required."""
    assert can_transition("draft", "under_review") is False


def test_draft_cannot_skip_to_approved():
    """The cardinal forbidden transition. A draft cannot leap to
    approved without passing through submission + review — pin
    so an admin-side shortcut doesn't bypass the workflow."""
    assert can_transition("draft", "approved") is False


def test_draft_cannot_skip_to_rejected():
    """Symmetric: a draft cannot be rejected without being
    submitted first."""
    assert can_transition("draft", "rejected") is False


def test_submitted_can_go_to_under_review():
    assert can_transition("submitted", "under_review") is True


def test_submitted_cannot_skip_to_approved():
    """Reviewer must explicitly enter under_review before
    approving — pin so a "rubber stamp" admin shortcut doesn't
    bypass the under_review state (which the audit trail uses
    to measure review duration)."""
    assert can_transition("submitted", "approved") is False


def test_under_review_can_go_to_approved():
    assert can_transition("under_review", "approved") is True


def test_under_review_can_go_to_revision_requested():
    assert can_transition("under_review", "revision_requested") is True


def test_under_review_can_go_to_rejected():
    assert can_transition("under_review", "rejected") is True


def test_under_review_cannot_go_back_to_submitted():
    """A reviewer in under_review must commit to one of the three
    decisions — they can't reset the workflow back to submitted.
    Pin so a refactor that adds a "save draft review" reviewer
    action doesn't accidentally bypass the decision step."""
    assert can_transition("under_review", "submitted") is False


def test_under_review_cannot_go_back_to_draft():
    assert can_transition("under_review", "draft") is False


def test_revision_requested_can_go_to_submitted():
    """The resubmission loop. Without this, every revision would
    create a NEW submittal — scattering the audit trail across
    multiple records. Pin so a refactor that locks
    revision_requested as forward-only breaks here."""
    assert can_transition("revision_requested", "submitted") is True


def test_revision_requested_cannot_skip_to_under_review():
    """Resubmission must pass through `submitted` (not directly
    back to under_review) — so the reviewer queue picks it up
    fresh. Pin so an "auto-route to same reviewer" shortcut
    doesn't bypass the queue."""
    assert can_transition("revision_requested", "under_review") is False


def test_revision_requested_cannot_skip_to_approved():
    assert can_transition("revision_requested", "approved") is False


def test_approved_is_truly_terminal():
    """Approved has zero outbound transitions. A re-opened
    submittal becomes a NEW submittal."""
    for to in STATUSES:
        assert can_transition("approved", to) is False


def test_rejected_is_truly_terminal():
    """Rejected has zero outbound transitions."""
    for to in STATUSES:
        assert can_transition("rejected", to) is False


def test_no_status_self_loops():
    """No `x → x` transition is allowed. Self-loops would inflate
    the audit trail with no-op events."""
    for status in STATUSES:
        assert can_transition(status, status) is False


def test_can_transition_false_for_unknown_inputs():
    """Defensive: None / unknown status → False, no raise."""
    assert can_transition(None, "draft") is False
    assert can_transition("draft", None) is False
    assert can_transition("withdrawn", "draft") is False
    assert can_transition("draft", "withdrawn") is False
    assert can_transition(None, None) is False


# ---------- next_allowed ----------


def test_next_allowed_draft():
    assert next_allowed("draft") == frozenset({"submitted"})


def test_next_allowed_submitted():
    assert next_allowed("submitted") == frozenset({"under_review"})


def test_next_allowed_under_review_has_three_options():
    """The reviewer's three explicit decisions. Pin so a refactor
    that collapses any pair (e.g. dropping the explicit "rejected"
    in favour of "revision_requested → close-without-resubmit")
    surfaces here."""
    assert next_allowed("under_review") == frozenset(
        {
            "approved",
            "revision_requested",
            "rejected",
        }
    )


def test_next_allowed_revision_requested():
    assert next_allowed("revision_requested") == frozenset({"submitted"})


def test_next_allowed_approved_is_empty():
    assert next_allowed("approved") == frozenset()


def test_next_allowed_rejected_is_empty():
    assert next_allowed("rejected") == frozenset()


def test_next_allowed_unknown_returns_empty():
    assert next_allowed("withdrawn") == frozenset()
    assert next_allowed(None) == frozenset()
    assert next_allowed("") == frozenset()


# ---------- ALLOWED_TRANSITIONS map invariants ----------


def test_allowed_transitions_covers_every_status():
    """Every status appears as a key in ALLOWED_TRANSITIONS — the
    map is exhaustive over the closed status set."""
    assert frozenset(ALLOWED_TRANSITIONS.keys()) == STATUSES


def test_allowed_transitions_targets_are_valid_statuses():
    """Every target status is a member of STATUSES — no map
    entry references a status outside the closed set."""
    for from_status, targets in ALLOWED_TRANSITIONS.items():
        for to in targets:
            assert to in STATUSES, f"{from_status} → {to} targets unknown status"


def test_terminal_statuses_have_no_outbound_transitions():
    """Approved and rejected each have an empty target set —
    pin so a refactor that adds e.g. `approved → archived`
    without updating TERMINAL_STATUSES surfaces here."""
    for status in TERMINAL_STATUSES:
        assert ALLOWED_TRANSITIONS[status] == frozenset()


def test_non_terminal_statuses_have_outbound_transitions():
    """Every non-terminal status has at least one outbound
    transition (else it'd be a stuck status not in
    TERMINAL_STATUSES — a workflow bug)."""
    for status in STATUSES - TERMINAL_STATUSES:
        assert len(ALLOWED_TRANSITIONS[status]) > 0, f"non-terminal status {status} has no outbound transitions"
