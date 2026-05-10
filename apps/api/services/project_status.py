"""Project status state machine (cycle YY1).

Completes the workflow QUARTET — AA3 (punchlist) + BB1 (submittal)
+ CC1 (change order) + YY1 (project). Same shape as the prior
three; same pinning patterns.

  STATUSES                 — frozen 6-status set
  TERMINAL_STATUSES        — {archived, cancelled}
  ACTIVE_STATUSES          — {planned, in_progress}
  ALLOWED_TRANSITIONS      — frozen map: from → frozenset(to)
  is_valid_status(s)       — bool
  is_terminal(s)           — bool
  is_active(s)             — bool ("currently working" filter)
  can_transition(a, b)     — bool
  next_allowed(s)          — frozenset[str]

Workflow:
  planned      → in_progress / cancelled
  in_progress  → on_hold / completed / cancelled
  on_hold      → in_progress (resume) / cancelled
  completed    → archived
  archived     → (terminal)
  cancelled    → (terminal)

Critical invariants pinned by tests:
  * `archived → in_progress` FORBIDDEN — archival is final,
    no unarchive (re-opening = create new project).
  * `on_hold → in_progress` IS allowed (resume after pause).
  * `on_hold → completed` is FORBIDDEN (must resume first —
    completing from on-hold without an active phase would
    leave the project's actual-work tracking incomplete).
  * `completed → in_progress` FORBIDDEN (completed is one-way
    too; mistake-correction = create amendment).
  * `cancelled` is exit-early (no resume).
  * 6 statuses exact, matches AA3/BB1/CC1 family pattern.

Pure stdlib.
"""

from __future__ import annotations

STATUSES: frozenset[str] = frozenset(
    {
        "planned",
        "in_progress",
        "on_hold",
        "completed",
        "archived",
        "cancelled",
    }
)


# Strict no-outbound terminals. The audit verification trail's
# stuck-project detector flags non-terminal projects with no
# activity in >180 days.
TERMINAL_STATUSES: frozenset[str] = frozenset({"archived", "cancelled"})


# "Currently working" set — used by the dashboard's active-projects
# count and the project list's default filter.
ACTIVE_STATUSES: frozenset[str] = frozenset({"planned", "in_progress"})


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"in_progress", "cancelled"}),
    "in_progress": frozenset({"on_hold", "completed", "cancelled"}),
    "on_hold": frozenset({"in_progress", "cancelled"}),
    "completed": frozenset({"archived"}),
    "archived": frozenset(),
    "cancelled": frozenset(),
}


def is_valid_status(status: str | None) -> bool:
    """True iff the input is a member of STATUSES."""
    return status in STATUSES


def is_terminal(status: str | None) -> bool:
    """True iff the status has no outbound transitions."""
    return status in TERMINAL_STATUSES


def is_active(status: str | None) -> bool:
    """True iff the project is in an "active work" status.

    Used by the dashboard's "active projects" KPI and the
    project list's default filter chip.
    """
    return status in ACTIVE_STATUSES


def can_transition(
    from_status: str | None,
    to_status: str | None,
) -> bool:
    """True iff `from → to` is in ALLOWED_TRANSITIONS."""
    if from_status not in STATUSES or to_status not in STATUSES:
        return False
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


def next_allowed(status: str | None) -> frozenset[str]:
    """Set of valid next statuses from the current status."""
    if status not in STATUSES:
        return frozenset()
    return ALLOWED_TRANSITIONS.get(status, frozenset())
