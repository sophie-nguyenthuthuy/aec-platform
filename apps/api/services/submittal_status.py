"""Submittal review state machine (cycle BB1).

Closed status set + frozen transition map for the submittal
review workflow. Parallel structure to `services.punchlist_status`
but for a different shape: the submittal flow has a resubmission
loop (`revision_requested → submitted`) where punchlist's `resolved`
loops to `in_progress`.

  STATUSES                 — frozen set of valid statuses (6)
  TERMINAL_STATUSES        — approved / rejected (no further transitions)
  ALLOWED_TRANSITIONS      — frozen map: from → frozenset(to)
  is_valid_status(s)       — bool
  is_terminal(s)           — bool
  can_transition(a, b)     — bool
  next_allowed(s)          — frozenset[str]

Workflow:
  draft               → submitted
  submitted           → under_review
  under_review        → approved / revision_requested / rejected
  revision_requested  → submitted (author resubmits with changes)
  approved            → (terminal)
  rejected            → (terminal)

Critical invariants pinned by tests:
  * `draft → approved` is FORBIDDEN. Submission + review steps
    can't be skipped.
  * `revision_requested → submitted` IS allowed (the resubmission
    loop — without it, every revision creates a new submittal,
    which would scatter the audit trail).
  * `under_review → submitted` is FORBIDDEN. A reviewer must
    commit to a decision (approve / revision / reject) — pin so
    a refactor that adds a "save draft" reviewer action doesn't
    accidentally reset the workflow.
  * `approved` and `rejected` are strict no-outbound terminals.
"""

from __future__ import annotations

# Closed set of submittal statuses. Adding a 7th (e.g. "withdrawn")
# requires touching the frontend status filter, the audit
# verification trail's stuck-review detector, and the deadline-
# overrun Slack alert — pin so a sneaky add doesn't slip past
# three-way review.
STATUSES: frozenset[str] = frozenset(
    {
        "draft",
        "submitted",
        "under_review",
        "revision_requested",
        "approved",
        "rejected",
    }
)


# Strict no-outbound terminals. The audit verification trail's
# stuck-review detector flags submittals that haven't reached one
# of these in >14 days; pin the closed set here so the detector
# doesn't silently shift if a refactor adds a status.
TERMINAL_STATUSES: frozenset[str] = frozenset({"approved", "rejected"})


# from-status → set of valid to-statuses. Every key in STATUSES
# appears here (test pins exhaustiveness); every target is a
# member of STATUSES (test pins target-validity).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted"}),
    "submitted": frozenset({"under_review"}),
    "under_review": frozenset({"approved", "revision_requested", "rejected"}),
    "revision_requested": frozenset({"submitted"}),
    "approved": frozenset(),
    "rejected": frozenset(),
}


def is_valid_status(status: str | None) -> bool:
    """True iff the input is a member of STATUSES.

    Used by the endpoint's request validator to reject hand-edited
    status values from a stale client. Case-sensitive — `DRAFT`
    returns False so a refactor to lowercase normalisation has to
    happen explicitly.
    """
    return status in STATUSES


def is_terminal(status: str | None) -> bool:
    """True iff the status has no outbound transitions.

    Used by the audit verification trail's stuck-review detector
    (a submittal in a non-terminal status for >14 days surfaces in
    the ops dashboard) and a future deadline-overrun Slack alert.
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

    Used by the submittal UI to render action buttons (only show
    "Approve" if `approved in next_allowed(submittal.status)`).
    Unknown / None → empty set (the row renders read-only).
    """
    if status not in STATUSES:
        return frozenset()
    return ALLOWED_TRANSITIONS.get(status, frozenset())
