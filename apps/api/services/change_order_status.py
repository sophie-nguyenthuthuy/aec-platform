"""Change order status state machine (cycle CC1).

Closed status set + frozen transition map for the change order
workflow. Completes the workflow trifecta:

  * services.punchlist_status   — punchlist items
  * services.submittal_status   — submittal reviews
  * services.change_order_status — change orders (this module)

Change orders have their own shape: a `pending_signature` step
between approval and commitment, since signed change orders
affect the project's cost rollup and need an explicit second
party to attest. The `signed` status is the only "commitment-
counts-here" terminal (the financial-impact rollup distinguishes
signed from in-flight orders).

  STATUSES                 — frozen set of valid statuses (6)
  TERMINAL_STATUSES        — signed / rejected (no further transitions)
  COMMITTED_STATUSES       — signed (counts in the cost rollup)
  ALLOWED_TRANSITIONS      — frozen map: from → frozenset(to)
  is_valid_status(s)       — bool
  is_terminal(s)           — bool
  is_committed(s)          — bool
  can_transition(a, b)     — bool
  next_allowed(s)          — frozenset[str]

Workflow:
  draft              → submitted
  submitted          → reviewing
  reviewing          → pending_signature / rejected
  pending_signature  → signed
  signed             → (terminal, committed)
  rejected           → (terminal)

Critical invariants pinned by tests:
  * `submitted → signed` is FORBIDDEN. The reviewer must explicitly
    enter `reviewing` so the SLA timer starts (audit trail uses
    the reviewing-duration metric).
  * `reviewing → signed` is FORBIDDEN. Approval must transit
    `pending_signature` so the second-party signature is
    explicit, not implicit.
  * `pending_signature → rejected` is FORBIDDEN. A withdrawn
    signature creates a NEW change order (audit trail clarity).
  * `signed` and `rejected` are strict no-outbound terminals.
  * `signed` is the only member of COMMITTED_STATUSES — pin so a
    refactor that adds a "tentatively committed" status doesn't
    silently skew the cost rollup.
"""

from __future__ import annotations

STATUSES: frozenset[str] = frozenset(
    {
        "draft",
        "submitted",
        "reviewing",
        "pending_signature",
        "signed",
        "rejected",
    }
)


# Strict no-outbound terminals. The audit verification trail's
# stuck-order detector flags change orders in non-terminal statuses
# for >30 days; pin the closed set here so the detector doesn't
# silently shift if a refactor adds a status.
TERMINAL_STATUSES: frozenset[str] = frozenset({"signed", "rejected"})


# Statuses that count in the project cost rollup. Today only
# `signed` counts — pin so a refactor that adds e.g. a
# "tentatively committed" status doesn't silently inflate the
# committed-cost number on the dashboard. The financial-impact
# Slack alert and the project budget guard both depend on this.
COMMITTED_STATUSES: frozenset[str] = frozenset({"signed"})


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted"}),
    "submitted": frozenset({"reviewing"}),
    "reviewing": frozenset({"pending_signature", "rejected"}),
    "pending_signature": frozenset({"signed"}),
    "signed": frozenset(),
    "rejected": frozenset(),
}


def is_valid_status(status: str | None) -> bool:
    """True iff the input is a member of STATUSES.

    Used by the change order endpoint's request validator to
    reject hand-edited status values from a stale client.
    Case-sensitive.
    """
    return status in STATUSES


def is_terminal(status: str | None) -> bool:
    """True iff the status has no outbound transitions.

    Used by the audit verification trail's stuck-order detector
    and a future SLA-overrun Slack alert (a change order in
    `reviewing` for >7 days surfaces in the ops dashboard).
    """
    return status in TERMINAL_STATUSES


def is_committed(status: str | None) -> bool:
    """True iff the status counts in the project cost rollup.

    Today: `signed` only. Pin so the cost rollup, the project
    budget guard, and the financial-impact Slack alert agree on
    the same closed set.
    """
    return status in COMMITTED_STATUSES


def can_transition(from_status: str | None, to_status: str | None) -> bool:
    """True iff `from → to` is in ALLOWED_TRANSITIONS.

    Defensive: invalid inputs (None, unknown status) return False
    rather than raising. The caller is the endpoint's validator;
    a False return surfaces as HTTP 400 to the client.
    """
    if from_status not in STATUSES or to_status not in STATUSES:
        return False
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


def next_allowed(status: str | None) -> frozenset[str]:
    """Set of valid next statuses from the given current status.

    Used by the change order UI to render action buttons (only
    show "Approve" if `pending_signature in next_allowed(co.status)`).
    Unknown / None → empty set (the row renders read-only).
    """
    if status not in STATUSES:
        return frozenset()
    return ALLOWED_TRANSITIONS.get(status, frozenset())
