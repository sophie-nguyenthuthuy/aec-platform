"""Org member role hierarchy + permission resolver (cycle DD1).

Closed role set + frozen rank order + permission matrix. Today
every endpoint's auth decorator does role checks inline with
subtly different bar-heights (one route says "admin", another
says "any non-viewer"); the audit row's "who can see this"
filter duplicates this; the org-settings UI's button-disabled
logic triplicates it. This module is the single source of truth.

  ROLES                — frozen set of valid roles (4)
  ROLE_RANK            — role → int (higher = more privileges)
  ACTION_MIN_ROLE      — closed action → minimum-role matrix
  KNOWN_ACTIONS        — frozenset of every action in the matrix
  is_at_least(r, t)    — bool, rank comparison
  can(r, action)       — bool, permission check
  can_assign_role(...) — bool, who can assign which role

Role hierarchy (ascending):
  viewer  (1) — read-only access to assigned projects
  member  (2) — can create / edit punchlist, submittals, estimates
  admin   (3) — can approve / verify, manage non-admin roles
  owner   (4) — can transfer ownership, delete org, manage admins

Critical invariants pinned by tests:
  * Admin CANNOT promote another to admin (only owner can).
    Defends against rogue-admin → owner-takeover paths.
  * Only owner can assign 'owner' role (= transfer of ownership).
  * Viewer cannot create resources (read-only).
  * Unknown actions deny by default (closed-action allowlist).
  * `can(None, ...)` and `can(..., None)` always return False.
"""

from __future__ import annotations

ROLES: frozenset[str] = frozenset({"owner", "admin", "member", "viewer"})


# Higher rank = more privileges. Pin so a refactor that flips
# the order doesn't break is_at_least. Exposed for sort orders
# in the org-settings UI's member-list view.
ROLE_RANK: dict[str, int] = {
    "viewer": 1,
    "member": 2,
    "admin": 3,
    "owner": 4,
}


# Action → minimum role required to perform it. Closed matrix —
# every action that crosses an auth boundary appears here. Pin
# so a refactor that adds an action without considering its auth
# requirement (or one that lowers the bar) surfaces in the test.
ACTION_MIN_ROLE: dict[str, str] = {
    # ---------- Read actions (viewer+) ----------
    "audit.read": "viewer",
    "project.read": "viewer",
    "estimate.read": "viewer",
    "punchlist.read": "viewer",
    "submittal.read": "viewer",
    "change_order.read": "viewer",
    # ---------- Create / edit (member+) ----------
    "punchlist.create": "member",
    "punchlist.update": "member",
    "submittal.create": "member",
    "submittal.update": "member",
    "estimate.create": "member",
    "estimate.update": "member",
    "change_order.create": "member",
    "change_order.update": "member",
    # ---------- Approve / verify / sign (admin+) ----------
    "punchlist.verify": "admin",
    "submittal.approve": "admin",
    "submittal.reject": "admin",
    "change_order.approve": "admin",
    "change_order.reject": "admin",
    "webhook.subscription.create": "admin",
    "webhook.subscription.delete": "admin",
    "webhook.subscription.rotate_secret": "admin",
    "org.member.role_change": "admin",
    # ---------- Owner-only (org-level) ----------
    "org.transfer_ownership": "owner",
    "org.delete": "owner",
    "org.settings.update": "owner",
}


# Closed set of every action in the matrix. Used by the audit
# router to validate that the requested-action filter only
# accepts known actions (otherwise a typo would silently match
# nothing rather than 404).
KNOWN_ACTIONS: frozenset[str] = frozenset(ACTION_MIN_ROLE.keys())


def is_at_least(role: str | None, threshold: str | None) -> bool:
    """True iff `role`'s rank >= `threshold`'s rank.

    Defensive: unknown / None role or threshold returns False.
    """
    if role not in ROLES or threshold not in ROLES:
        return False
    return ROLE_RANK[role] >= ROLE_RANK[threshold]


def can(role: str | None, action: str | None) -> bool:
    """True iff `role` is permitted to perform `action`.

    Unknown actions deny by default — the closed allowlist
    means a refactor that adds an endpoint without registering
    its action gate fails closed (HTTP 403) rather than open.
    """
    if action not in ACTION_MIN_ROLE:
        return False
    return is_at_least(role, ACTION_MIN_ROLE[action])


def can_assign_role(actor_role: str | None, target_role: str | None) -> bool:
    """True iff an actor with `actor_role` can assign `target_role`
    to another member.

    Rules:
      * Only owner can assign 'owner' (transfer of ownership).
      * Owner can assign any role.
      * Admin can assign 'member' / 'viewer' only — CANNOT
        promote another to admin (defense against rogue-admin
        → owner-takeover paths).
      * Member, viewer cannot assign any role.

    Defensive: unknown / None inputs return False.
    """
    if actor_role not in ROLES or target_role not in ROLES:
        return False
    # 'owner' role is owner-transfer-only.
    if target_role == "owner":
        return actor_role == "owner"
    # Owner can assign any non-owner role.
    if actor_role == "owner":
        return True
    # Admin can assign roles strictly below admin (member, viewer).
    if actor_role == "admin":
        return target_role in {"member", "viewer"}
    # Member, viewer cannot assign.
    return False
