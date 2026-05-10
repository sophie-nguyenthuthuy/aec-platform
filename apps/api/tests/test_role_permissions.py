"""Org member role hierarchy + permission resolver (cycle DD1).

Pinned seams:
  1. ROLES has exactly 4 members.
  2. ROLE_RANK is strict ascending: viewer < member < admin < owner.
  3. Viewer cannot create resources (read-only).
  4. Admin cannot promote another to admin (rogue-admin defense).
  5. Only owner can assign 'owner' (transfer-of-ownership).
  6. Unknown actions deny by default (closed allowlist).
  7. None / unknown inputs always return False (defensive).
  8. ACTION_MIN_ROLE matrix targets are valid roles.
"""

from __future__ import annotations

from services.role_permissions import (
    ACTION_MIN_ROLE,
    KNOWN_ACTIONS,
    ROLE_RANK,
    ROLES,
    can,
    can_assign_role,
    is_at_least,
)

# ---------- ROLES ----------


def test_roles_has_exactly_four_members():
    """4-role closed set. Adding a 5th (e.g. "guest") requires
    touching the auth decorator, the org-settings UI, the audit
    row filter, AND the can_assign_role matrix. Pin so a sneaky
    add doesn't slip past four-way review."""
    assert len(ROLES) == 4
    assert frozenset({"owner", "admin", "member", "viewer"}) == ROLES


def test_roles_is_frozen():
    assert isinstance(ROLES, frozenset)


# ---------- ROLE_RANK ----------


def test_role_rank_strict_ascending():
    """Pin the canonical hierarchy. A refactor that flips two
    ranks would break is_at_least silently."""
    assert ROLE_RANK["viewer"] < ROLE_RANK["member"]
    assert ROLE_RANK["member"] < ROLE_RANK["admin"]
    assert ROLE_RANK["admin"] < ROLE_RANK["owner"]


def test_role_rank_covers_every_role():
    """Every role has a rank entry. Pin so a refactor that adds
    a role to ROLES without giving it a rank surfaces here."""
    assert frozenset(ROLE_RANK.keys()) == ROLES


def test_role_rank_unique_values():
    """No two roles share a rank — strict total order."""
    ranks = list(ROLE_RANK.values())
    assert len(ranks) == len(set(ranks))


# ---------- is_at_least ----------


def test_is_at_least_self_equal():
    """A role meets itself. Pin: is_at_least(admin, admin) = True
    so a route gated `is_at_least(actor, "admin")` lets actual
    admins through."""
    for role in ROLES:
        assert is_at_least(role, role) is True


def test_is_at_least_owner_dominates_all():
    for role in ROLES:
        assert is_at_least("owner", role) is True


def test_is_at_least_viewer_dominates_only_self():
    assert is_at_least("viewer", "viewer") is True
    assert is_at_least("viewer", "member") is False
    assert is_at_least("viewer", "admin") is False
    assert is_at_least("viewer", "owner") is False


def test_is_at_least_admin_above_member_and_viewer():
    assert is_at_least("admin", "viewer") is True
    assert is_at_least("admin", "member") is True
    assert is_at_least("admin", "admin") is True
    assert is_at_least("admin", "owner") is False


def test_is_at_least_false_for_unknown_or_none():
    """Defensive: None / unknown role returns False rather
    than raising. The auth decorator's posture is fail-closed."""
    assert is_at_least(None, "viewer") is False
    assert is_at_least("viewer", None) is False
    assert is_at_least(None, None) is False
    assert is_at_least("guest", "viewer") is False
    assert is_at_least("viewer", "guest") is False


# ---------- can (read actions) ----------


def test_viewer_can_read():
    """Read actions are viewer+. Pin so a refactor that bumps
    the audit page bar to "member" breaks here — the read-only
    role should always read."""
    assert can("viewer", "audit.read") is True
    assert can("viewer", "project.read") is True
    assert can("viewer", "estimate.read") is True
    assert can("viewer", "punchlist.read") is True


def test_higher_roles_inherit_read_access():
    for role in ["member", "admin", "owner"]:
        assert can(role, "audit.read") is True
        assert can(role, "project.read") is True


# ---------- can (create / edit) ----------


def test_viewer_cannot_create_resources():
    """Cardinal viewer pin: read-only. A refactor that gives
    viewers create access would silently allow data entry from
    "guest"-like accounts."""
    assert can("viewer", "punchlist.create") is False
    assert can("viewer", "submittal.create") is False
    assert can("viewer", "estimate.create") is False
    assert can("viewer", "change_order.create") is False


def test_member_can_create_resources():
    assert can("member", "punchlist.create") is True
    assert can("member", "submittal.create") is True
    assert can("member", "estimate.create") is True
    assert can("member", "change_order.create") is True


def test_member_cannot_approve():
    """Members create, admins approve. Pin the separation —
    creator-approver collision is a workflow integrity risk."""
    assert can("member", "submittal.approve") is False
    assert can("member", "change_order.approve") is False
    assert can("member", "punchlist.verify") is False


# ---------- can (admin actions) ----------


def test_admin_can_approve():
    assert can("admin", "submittal.approve") is True
    assert can("admin", "change_order.approve") is True
    assert can("admin", "punchlist.verify") is True


def test_admin_can_manage_webhook_subscriptions():
    assert can("admin", "webhook.subscription.create") is True
    assert can("admin", "webhook.subscription.delete") is True
    assert can("admin", "webhook.subscription.rotate_secret") is True


def test_admin_can_change_member_roles():
    assert can("admin", "org.member.role_change") is True


def test_admin_cannot_delete_org():
    """Admin is bounded — org-deletion is owner-only. Pin so a
    refactor that lowers the bar to "admin" doesn't enable a
    destructive action without explicit ownership."""
    assert can("admin", "org.delete") is False
    assert can("admin", "org.transfer_ownership") is False
    assert can("admin", "org.settings.update") is False


# ---------- can (owner actions) ----------


def test_owner_can_do_everything():
    """Owner is the apex — every known action returns True."""
    for action in ACTION_MIN_ROLE:
        assert can("owner", action) is True, f"owner should be able to {action}"


def test_owner_only_actions():
    assert can("owner", "org.transfer_ownership") is True
    assert can("owner", "org.delete") is True
    assert can("owner", "org.settings.update") is True


# ---------- can (defensive) ----------


def test_can_unknown_action_denies():
    """Closed allowlist: unknown actions deny by default. Pin so
    a refactor that adds an endpoint without registering its
    action surfaces as HTTP 403 rather than silently allowing."""
    assert can("owner", "unknown.action") is False
    assert can("owner", "fictional.thing") is False


def test_can_none_role_or_action_denies():
    """Defensive: None inputs return False (fail-closed)."""
    assert can(None, "audit.read") is False
    assert can("viewer", None) is False
    assert can(None, None) is False


def test_can_unknown_role_denies():
    assert can("guest", "audit.read") is False
    assert can("superuser", "org.delete") is False


# ---------- can_assign_role ----------


def test_owner_can_assign_any_role():
    """Owner can promote / demote arbitrarily."""
    for target in ROLES:
        assert can_assign_role("owner", target) is True, f"owner→{target}"


def test_only_owner_can_assign_owner():
    """Cardinal pin: 'owner' is transfer-of-ownership and
    requires explicit owner action. A refactor that lets admins
    transfer ownership would break the most fundamental auth
    invariant."""
    assert can_assign_role("owner", "owner") is True
    assert can_assign_role("admin", "owner") is False
    assert can_assign_role("member", "owner") is False
    assert can_assign_role("viewer", "owner") is False


def test_admin_cannot_promote_to_admin():
    """Cardinal pin: rogue-admin defense. A rogue admin who
    could promote others to admin would mint an arbitrary number
    of admins → effective owner-takeover. Pin so a "self-service
    admin invitation" feature can't slip past."""
    assert can_assign_role("admin", "admin") is False


def test_admin_can_assign_member_and_viewer():
    """Admin manages roles strictly below admin."""
    assert can_assign_role("admin", "member") is True
    assert can_assign_role("admin", "viewer") is True


def test_member_cannot_assign_any_role():
    for target in ROLES:
        assert can_assign_role("member", target) is False, f"member→{target}"


def test_viewer_cannot_assign_any_role():
    for target in ROLES:
        assert can_assign_role("viewer", target) is False, f"viewer→{target}"


def test_can_assign_role_defensive():
    assert can_assign_role(None, "viewer") is False
    assert can_assign_role("admin", None) is False
    assert can_assign_role("guest", "viewer") is False
    assert can_assign_role("admin", "guest") is False


# ---------- ACTION_MIN_ROLE matrix invariants ----------


def test_action_min_role_targets_are_valid_roles():
    """Every minimum-role value is a member of ROLES — no typos
    in the matrix."""
    for action, min_role in ACTION_MIN_ROLE.items():
        assert min_role in ROLES, f"{action} → {min_role} not a valid role"


def test_known_actions_matches_matrix_keys():
    """KNOWN_ACTIONS is the closed set of actions in the matrix.
    Used by the audit filter validator — pin so a refactor that
    adds an action to one and not the other surfaces here."""
    assert frozenset(ACTION_MIN_ROLE.keys()) == KNOWN_ACTIONS


def test_known_actions_is_frozen():
    assert isinstance(KNOWN_ACTIONS, frozenset)


def test_org_delete_is_owner_only():
    """The most destructive action — pin owner-only as a hard
    invariant."""
    assert ACTION_MIN_ROLE["org.delete"] == "owner"
    assert ACTION_MIN_ROLE["org.transfer_ownership"] == "owner"
