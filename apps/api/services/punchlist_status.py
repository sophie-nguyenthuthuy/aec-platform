"""Punchlist status state machine (cycle AA3).

Closed status set + frozen transition map for the punchlist
workflow. Today the punchlist endpoint validates status
transitions inline; the audit verification trail's "stuck item"
detector duplicates the terminal-status check; a future Slack
digest grouping items by stuck status will need a third copy.

  STATUSES                — frozen set of valid statuses
  TERMINAL_STATUSES       — verified / closed (no further transitions)
  ALLOWED_TRANSITIONS     — frozen map: from → frozenset(to)
  is_valid_status(s)      — bool
  is_terminal(s)          — bool
  can_transition(a, b)    — bool
  next_allowed(s)         — frozenset[str] of valid next states

Workflow:
  open        → in_progress / closed (skip if duplicate)
  in_progress → resolved
  resolved    → verified / in_progress (rework requested)
  verified    → closed
  closed      → (terminal)

Critical invariants pinned by tests:
  * `open → resolved` is FORBIDDEN. An item must pass through
    in_progress before being marked resolved.
  * No status self-loop is allowed (`x → x` always False).
  * `closed` has zero outbound transitions (true terminal).
  * `resolved → in_progress` IS allowed (rework requested).
"""

from __future__ import annotations

# Closed set of punchlist statuses. Adding a 6th status requires
# touching the frontend status filter chip set, the audit
# verification trail's stuck-item rule, and the Slack digest
# grouping — pin so a sneaky add doesn't slip past three-way review.
STATUSES: frozenset[str] = frozenset(
    {
        "open",
        "in_progress",
        "resolved",
        "verified",
        "closed",
    }
)


# Statuses with no outbound transitions. The audit verification
# trail's stuck-item detector flags items in non-terminal statuses
# for >7 days; pin the closed set here so the detector doesn't
# silently drop a status if a refactor adds one.
TERMINAL_STATUSES: frozenset[str] = frozenset({"verified", "closed"})


# from-status → set of valid to-statuses. Every key in STATUSES
# appears here (test pins exhaustiveness); every target is a
# member of STATUSES (test pins target-validity).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"in_progress", "closed"}),
    "in_progress": frozenset({"resolved"}),
    "resolved": frozenset({"verified", "in_progress"}),
    "verified": frozenset({"closed"}),
    "closed": frozenset(),
}


def is_valid_status(status: str | None) -> bool:
    """True iff the input is a member of STATUSES.

    Used by the endpoint's request validator to reject hand-edited
    status values from a stale client. Case-sensitive — `OPEN`
    returns False so a refactor to lowercase normalisation has to
    happen explicitly.
    """
    return status in STATUSES


def is_terminal(status: str | None) -> bool:
    """True iff the status has no outbound transitions.

    Used by the audit verification trail's stuck-item detector
    (a punchlist item in a non-terminal status for >7 days surfaces
    in the ops dashboard) and a future Slack digest grouping items
    by stuck status.
    """
    return status in TERMINAL_STATUSES


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

    Used by the punchlist UI to render action buttons (only show
    "Mark resolved" if `resolved in next_allowed(item.status)`).
    Unknown / None → empty set (the row renders read-only).
    """
    if status not in STATUSES:
        return frozenset()
    return ALLOWED_TRANSITIONS.get(status, frozenset())
