"""Audit row recipient resolver (cycle BBB3).

Given an audit event + a list of org members with their
notification preferences and roles, return the ordered tuple
of (member_id, channels) for delivery. Today the notification
dispatcher, the Slack alert router, and the email digest
scheduler each iterate members + apply the filters inline with
subtly different ordering and a subtly different role-bar.
This module is the single source of truth.

  AuditMember                                     — frozen
  Recipient                                       — frozen
  resolve_recipients(ctx, event_type, members)    — tuple[Recipient, ...]

Composes (capstone for the audit notification subsystem):
  * CC2 (`notification_match.match_event`) — pattern + mute +
    channel intersection logic. Each member's preference is run
    through CC2 to decide deliverability.
  * DD1 (`role_permissions.can`) — role-based audit access:
    members must have `audit.read` permission to receive ANY
    audit notification (a viewer with `audit.read` permission
    does qualify; a `None`-role member does not).
  * ZZ3 (`audit_context.AuditContext`) — context carries
    `org_id` cross-tenant guard. The resolver does NOT itself
    re-check tenant — but the test pin verifies a `ctx` with
    empty `org_id` cannot be constructed in the first place
    (composes via ZZ3's `from_request` factory).

Pinned invariants:
  * Members ordered by `member_id` ascending in the result.
    A refactor that returns insertion order would break the
    audit log's "who got notified" determinism across re-runs.
  * Filter order: role check → CC2 match. A member whose role
    lacks `audit.read` is excluded BEFORE consulting CC2 (a
    refactor that flips this order would call CC2 unnecessarily
    on filtered members, surfacing in benchmark drift).
  * Muted members excluded (CC2 returns `should_deliver=False`).
  * Empty members tuple → empty result.
  * Each Recipient's `channels` is a non-empty frozenset.
  * Result is a `tuple` (immutable — pin so a refactor returning
    a list doesn't silently allow caller mutation that would
    affect dedup across multiple recipients passes).

Pure stdlib + CC2 + DD1 + ZZ3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from services.audit_context import AuditContext
from services.notification_match import (
    NotificationPreference,
    match_event,
)
from services.role_permissions import can

# The audit-read permission gate. Pin the action key so a refactor
# of DD1's action matrix that renames this key surfaces here.
AUDIT_READ_ACTION = "audit.read"


@dataclass(frozen=True)
class AuditMember:
    """An org member's audit-notification snapshot.

    Fields:
      * `member_id`  — stable identifier; result is sorted by this.
      * `role`       — one of DD1's ROLES (or unknown → filtered out).
      * `prefs`      — CC2 NotificationPreference snapshot.
    """

    member_id: str
    role: str
    prefs: NotificationPreference


@dataclass(frozen=True)
class Recipient:
    """A resolved delivery target.

    `channels` is the CC2-validated, non-empty channel set.
    """

    member_id: str
    channels: frozenset[str]


def resolve_recipients(
    ctx: AuditContext,
    event_type: str,
    members: tuple[AuditMember, ...],
    now: datetime,
) -> tuple[Recipient, ...]:
    """Return ordered recipients for an audit event.

    Algorithm:
      1. For each member:
         a. If `can(role, AUDIT_READ_ACTION)` is False → skip.
         b. Run CC2 `match_event(prefs, event_type, now)`.
         c. If `should_deliver` → emit Recipient(member_id, channels).
      2. Sort result by `member_id` ascending (deterministic).

    Args:
      ctx: ZZ3 audit context (carries `org_id`). The cross-tenant
        guard is enforced at ZZ3 construction time — pass-through
        here for capstone composition.
      event_type: the audit event being delivered (e.g.
        `pulse.change_order.approve`).
      members: org-member snapshot for the same `ctx.org_id`.
        Caller is responsible for the join (this is a pure helper).
      now: wall clock for CC2 mute-expiry comparison.

    Returns: tuple of Recipient sorted by `member_id`.
    """
    # Defensive: ctx must be a real AuditContext (carries cross-
    # tenant org_id). If org_id is empty it shouldn't be here —
    # the ZZ3 factory blocks empty at construction. Pin via a
    # guard so a future refactor that bypasses the factory still
    # fails closed.
    if not ctx.org_id:
        raise ValueError("ctx.org_id is required (cross-tenant guard)")

    recipients: list[Recipient] = []
    for m in members:
        # Order: role check first (cheap), then CC2 (more work).
        if not can(m.role, AUDIT_READ_ACTION):
            continue
        result = match_event(m.prefs, event_type, now)
        if not result.should_deliver:
            continue
        recipients.append(Recipient(member_id=m.member_id, channels=result.channels))

    recipients.sort(key=lambda r: r.member_id)
    return tuple(recipients)
