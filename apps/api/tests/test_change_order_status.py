"""Change order status state machine (cycle CC1).

Pinned seams:
  1. STATUSES has exactly 6 members (closed set).
  2. TERMINAL_STATUSES = {signed, rejected}.
  3. COMMITTED_STATUSES = {signed} (only signed counts in rollup).
  4. submitted → signed is FORBIDDEN (must enter reviewing).
  5. reviewing → signed is FORBIDDEN (must transit pending_signature).
  6. pending_signature → rejected is FORBIDDEN (withdrawal = new order).
  7. No status self-loop.
  8. ALLOWED_TRANSITIONS exhaustive over STATUSES.
"""

from __future__ import annotations

from services.change_order_status import (
    ALLOWED_TRANSITIONS,
    COMMITTED_STATUSES,
    STATUSES,
    TERMINAL_STATUSES,
    can_transition,
    is_committed,
    is_terminal,
    is_valid_status,
    next_allowed,
)


# ---------- STATUSES ----------


def test_statuses_has_exactly_six_members():
    """The change order workflow has exactly 6 statuses. Adding a
    7th requires touching the frontend filter, the stuck-order
    detector, the cost rollup, and the financial-impact Slack
    alert — pin so a sneaky add doesn't slip past four-way review."""
    assert len(STATUSES) == 6
    assert STATUSES == frozenset({
        "draft",
        "submitted",
        "reviewing",
        "pending_signature",
        "signed",
        "rejected",
    })


def test_statuses_is_frozen():
    assert isinstance(STATUSES, frozenset)


# ---------- TERMINAL_STATUSES ----------


def test_terminal_statuses_canonical_set():
    """Only signed and rejected are terminal. Pending_signature
    is NOT terminal — it has an outbound transition to signed."""
    assert TERMINAL_STATUSES == frozenset({"signed", "rejected"})


def test_terminal_statuses_is_subset_of_statuses():
    assert TERMINAL_STATUSES.issubset(STATUSES)


def test_terminal_statuses_is_frozen():
    assert isinstance(TERMINAL_STATUSES, frozenset)


# ---------- COMMITTED_STATUSES ----------


def test_committed_statuses_only_signed():
    """Today only `signed` counts in the cost rollup. Pin so a
    refactor that adds e.g. "tentatively_committed" doesn't
    silently inflate the committed-cost number."""
    assert COMMITTED_STATUSES == frozenset({"signed"})


def test_committed_statuses_is_subset_of_terminal():
    """A committed status must also be terminal — once committed,
    no further transitions. Pin so a refactor that flags a
    non-terminal as committed surfaces here."""
    assert COMMITTED_STATUSES.issubset(TERMINAL_STATUSES)


def test_committed_statuses_is_frozen():
    assert isinstance(COMMITTED_STATUSES, frozenset)


# ---------- is_valid_status ----------


def test_is_valid_status_true_for_known():
    for s in [
        "draft",
        "submitted",
        "reviewing",
        "pending_signature",
        "signed",
        "rejected",
    ]:
        assert is_valid_status(s) is True


def test_is_valid_status_false_for_unknown_or_none():
    assert is_valid_status("approved") is False  # not in this workflow
    assert is_valid_status("DRAFT") is False  # case-sensitive
    assert is_valid_status(None) is False
    assert is_valid_status("") is False


# ---------- is_terminal ----------


def test_is_terminal_true_for_signed_and_rejected():
    assert is_terminal("signed") is True
    assert is_terminal("rejected") is True


def test_is_terminal_false_for_pending_signature():
    """Pending_signature is NOT terminal — has outbound transition
    to signed. Pin so a refactor that treats pending_signature
    as "done" doesn't break the SLA timer."""
    assert is_terminal("pending_signature") is False


def test_is_terminal_false_for_active_states():
    assert is_terminal("draft") is False
    assert is_terminal("submitted") is False
    assert is_terminal("reviewing") is False


def test_is_terminal_false_for_unknown_or_none():
    assert is_terminal(None) is False
    assert is_terminal("") is False


# ---------- is_committed ----------


def test_is_committed_true_for_signed():
    assert is_committed("signed") is True


def test_is_committed_false_for_rejected():
    """Rejected is terminal but NOT committed — doesn't count in
    the cost rollup. Pin so a refactor that conflates "terminal"
    with "committed" surfaces here."""
    assert is_committed("rejected") is False


def test_is_committed_false_for_pending_signature():
    """Pending_signature is the pre-commitment state — explicitly
    NOT committed until signed. Pin so a refactor that treats
    "approved" (pending_signature) as committed doesn't inflate
    the rollup."""
    assert is_committed("pending_signature") is False


def test_is_committed_false_for_active_and_unknown():
    assert is_committed("draft") is False
    assert is_committed("submitted") is False
    assert is_committed("reviewing") is False
    assert is_committed(None) is False


# ---------- can_transition ----------


def test_draft_can_go_to_submitted():
    assert can_transition("draft", "submitted") is True


def test_draft_cannot_skip_to_reviewing():
    assert can_transition("draft", "reviewing") is False


def test_draft_cannot_skip_to_signed():
    """Cardinal forbidden transition. A draft cannot leap to
    signed — the entire review + signature flow is required."""
    assert can_transition("draft", "signed") is False


def test_submitted_can_go_to_reviewing():
    assert can_transition("submitted", "reviewing") is True


def test_submitted_cannot_skip_to_signed():
    """The reviewer must explicitly enter `reviewing` so the SLA
    timer starts. Pin so a "rubber stamp" admin shortcut doesn't
    bypass the reviewing-duration metric."""
    assert can_transition("submitted", "signed") is False


def test_submitted_cannot_skip_to_pending_signature():
    assert can_transition("submitted", "pending_signature") is False


def test_reviewing_can_go_to_pending_signature():
    assert can_transition("reviewing", "pending_signature") is True


def test_reviewing_can_go_to_rejected():
    assert can_transition("reviewing", "rejected") is True


def test_reviewing_cannot_skip_to_signed():
    """Approval must transit `pending_signature` so the second-
    party signature is explicit. Pin so an "auto-sign on approve"
    refactor doesn't silently bypass the signature requirement
    (which would be a contractual / legal regression)."""
    assert can_transition("reviewing", "signed") is False


def test_reviewing_cannot_go_back_to_submitted():
    """Once in reviewing, the reviewer must commit to a decision
    (pending_signature or rejected) — can't reset to submitted.
    Pin so a "save draft review" feature doesn't bypass the
    decision step."""
    assert can_transition("reviewing", "submitted") is False


def test_pending_signature_can_go_to_signed():
    assert can_transition("pending_signature", "signed") is True


def test_pending_signature_cannot_go_to_rejected():
    """A withdrawn signature creates a NEW change order — pin so
    a refactor that adds pending_signature → rejected (which would
    look natural) doesn't conflate the audit trails. Withdrawal
    is operationally distinct from rejection."""
    assert can_transition("pending_signature", "rejected") is False


def test_pending_signature_cannot_go_back_to_reviewing():
    """Once approval is granted, the reviewer can't pull it back —
    a new review cycle requires a new change order. Pin so a
    refactor doesn't silently allow rollback."""
    assert can_transition("pending_signature", "reviewing") is False


def test_signed_is_truly_terminal():
    """Signed has zero outbound transitions. A re-opened change
    order becomes a NEW change order."""
    for to in STATUSES:
        assert can_transition("signed", to) is False


def test_rejected_is_truly_terminal():
    for to in STATUSES:
        assert can_transition("rejected", to) is False


def test_no_status_self_loops():
    """No `x → x` transition is allowed."""
    for status in STATUSES:
        assert can_transition(status, status) is False


def test_can_transition_false_for_unknown_inputs():
    """Defensive: None / unknown status → False, no raise."""
    assert can_transition(None, "draft") is False
    assert can_transition("draft", None) is False
    assert can_transition("approved", "draft") is False  # not in this workflow
    assert can_transition(None, None) is False


# ---------- next_allowed ----------


def test_next_allowed_draft():
    assert next_allowed("draft") == frozenset({"submitted"})


def test_next_allowed_submitted():
    assert next_allowed("submitted") == frozenset({"reviewing"})


def test_next_allowed_reviewing_has_two_options():
    """The reviewer's two explicit decisions: approve (move to
    pending_signature) or reject."""
    assert next_allowed("reviewing") == frozenset({
        "pending_signature",
        "rejected",
    })


def test_next_allowed_pending_signature_has_one_option():
    """The second-party can only sign — can't reject from this
    state (withdrawal = new order). Pin the single-target
    constraint."""
    assert next_allowed("pending_signature") == frozenset({"signed"})


def test_next_allowed_signed_is_empty():
    assert next_allowed("signed") == frozenset()


def test_next_allowed_rejected_is_empty():
    assert next_allowed("rejected") == frozenset()


def test_next_allowed_unknown_returns_empty():
    assert next_allowed("approved") == frozenset()
    assert next_allowed(None) == frozenset()


# ---------- ALLOWED_TRANSITIONS map invariants ----------


def test_allowed_transitions_covers_every_status():
    assert frozenset(ALLOWED_TRANSITIONS.keys()) == STATUSES


def test_allowed_transitions_targets_are_valid_statuses():
    for from_status, targets in ALLOWED_TRANSITIONS.items():
        for to in targets:
            assert to in STATUSES, f"{from_status} → {to} targets unknown status"


def test_terminal_statuses_have_no_outbound_transitions():
    for status in TERMINAL_STATUSES:
        assert ALLOWED_TRANSITIONS[status] == frozenset()


def test_non_terminal_statuses_have_outbound_transitions():
    for status in STATUSES - TERMINAL_STATUSES:
        assert len(ALLOWED_TRANSITIONS[status]) > 0, (
            f"non-terminal status {status} has no outbound transitions"
        )
