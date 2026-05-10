"""Audit action classifier (cycle Z2).

Pinned seams:
  1. Three-segment actions split into module / resource / verb.
  2. Two-segment actions: module + verb, resource None.
  3. 4+ segment actions (e.g. admin.normalizer_rule.create has 3
     parts but normalizer_rule is itself two words logically) join
     middle segments into resource.
  4. Empty / None / single-segment inputs return defensive
     ActionParts without raising.
  5. `is_admin_action` matches AUDIT_MODULES membership.
  6. `AUDIT_MODULES` set covers every module currently in
     `services/audit.AuditAction`.
"""

from __future__ import annotations

from services.audit_action_meta import (
    ADMIN_MODULES,
    AUDIT_MODULES,
    ActionParts,
    is_admin_action,
    is_known_module,
    module_of,
    parse_action,
)


# ---------- parse_action ----------


def test_parse_three_segment_action():
    """Canonical: module.resource.verb."""
    out = parse_action("costpulse.estimate.approve")
    assert out == ActionParts(
        module="costpulse",
        resource="estimate",
        verb="approve",
        raw="costpulse.estimate.approve",
    )


def test_parse_two_segment_action():
    """`module.verb` shape — resource is None, the module IS the
    resource."""
    out = parse_action("webhook.test")
    assert out.module == "webhook"
    assert out.resource is None
    assert out.verb == "test"


def test_parse_single_segment_returns_module_only():
    """Defensive: an action without any dots is a programmer error
    but shouldn't crash. module=raw, resource=None, verb=None."""
    out = parse_action("unstructured")
    assert out.module == "unstructured"
    assert out.resource is None
    assert out.verb is None


def test_parse_empty_string_returns_empty_module():
    out = parse_action("")
    assert out.module == ""
    assert out.resource is None
    assert out.verb is None


def test_parse_none_returns_empty_module():
    """Defensive: a None action (corrupt audit row) returns an
    ActionParts with empty fields — caller can branch on
    `not module_of(...)`."""
    out = parse_action(None)
    assert out.module == ""
    assert out.raw == ""


def test_parse_four_segment_joins_middle_into_resource():
    """4+ segments: first = module, last = verb, middle joined
    with `.`. Handles the historical case where a resource name
    itself contains a dot (rare but allowed)."""
    out = parse_action("admin.foo.bar.baz")
    assert out.module == "admin"
    assert out.resource == "foo.bar"
    assert out.verb == "baz"


def test_parse_preserves_raw():
    """The raw string round-trips so even un-classifiable inputs
    render verbatim in the audit page."""
    out = parse_action("weird-shape::with-symbols")
    assert out.raw == "weird-shape::with-symbols"


# ---------- module_of ----------


def test_module_of_returns_module_segment():
    assert module_of("pulse.change_order.approve") == "pulse"
    assert module_of("admin.cron.run_now") == "admin"


def test_module_of_returns_empty_string_for_none():
    """Convenience accessor — empty string is a falsy fallback
    callers can branch on cleanly."""
    assert module_of(None) == ""
    assert module_of("") == ""


# ---------- is_admin_action ----------


def test_is_admin_action_true_for_admin_module():
    """All `admin.*` actions are platform-admin events that affect
    cross-tenant state. Pin the membership."""
    assert is_admin_action("admin.normalizer_rule.create") is True
    assert is_admin_action("admin.cron.run_now") is True
    assert is_admin_action("admin.retention.override_set") is True


def test_is_admin_action_false_for_workflow_modules():
    """Per-tenant workflow actions (cost / pulse / handover etc)
    are NOT admin actions even though admins typically perform
    them."""
    assert is_admin_action("costpulse.estimate.approve") is False
    assert is_admin_action("pulse.change_order.approve") is False
    assert is_admin_action("handover.package.deliver") is False


def test_is_admin_action_false_for_unknown_or_empty():
    assert is_admin_action(None) is False
    assert is_admin_action("") is False
    assert is_admin_action("typo-module.x.y") is False


def test_admin_modules_is_frozen():
    """ADMIN_MODULES must be a frozenset so a refactor can't
    accidentally append to it via `.add()` (which would silently
    promote a per-tenant module to admin status)."""
    assert isinstance(ADMIN_MODULES, frozenset)


# ---------- AUDIT_MODULES catalog ----------


def test_audit_modules_includes_every_existing_module_prefix():
    """Pin the closed set against the modules currently in
    `services/audit.AuditAction`. Adding a new module = touch
    here AND the AuditAction literal AND the frontend
    ACTION_FILTERS — three-way drift would slip a new module's
    actions into the audit page's "Other" fallback group."""
    expected = {
        "costpulse",
        "pulse",
        "org",
        "notifications",
        "handover",
        "punchlist",
        "submittals",
        "admin",
        "webhooks",
    }
    assert AUDIT_MODULES == frozenset(expected)


def test_is_known_module_for_existing_actions():
    """Every action emitted by the AuditAction literal classifies
    into one of AUDIT_MODULES. Pin via a sample from each module."""
    sample_actions = [
        "costpulse.estimate.approve",
        "pulse.change_order.approve",
        "org.member.role_change",
        "notifications.preference.update",
        "handover.package.deliver",
        "punchlist.list.sign_off",
        "submittals.review.approve",
        "admin.normalizer_rule.create",
        "webhooks.subscription.rotate_secret",
    ]
    for action in sample_actions:
        assert is_known_module(action), f"{action!r} module not in AUDIT_MODULES"


def test_is_known_module_false_for_typoed_module():
    """A typo'd module ("costpule" instead of "costpulse") returns
    False so the audit page's "Other" fallback surfaces it
    visibly rather than slotting into a real group."""
    assert is_known_module("costpule.estimate.approve") is False


def test_is_known_module_false_for_empty_or_none():
    assert is_known_module("") is False
    assert is_known_module(None) is False
