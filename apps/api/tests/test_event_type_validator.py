"""Webhook subscription event_type pattern validator (cycle WW3).

Pinned seams:
  1. Bare `*` always valid.
  2. `module.*` valid iff module ∈ Z2 AUDIT_MODULES.
  3. Literal patterns must have known module prefix.
  4. None / empty / whitespace-only → False.
  5. Case-sensitive.
  6. Composes with Z2 directly.
"""

from __future__ import annotations

from services.audit_action_meta import AUDIT_MODULES
from services.event_type_validator import (
    is_valid_event_type,
    validate_event_types,
)

# ---------- Universal wildcard ----------


def test_star_always_valid():
    """Cardinal pin: bare `*` always valid (subscribe to all)."""
    assert is_valid_event_type("*") is True


def test_star_with_whitespace_valid():
    assert is_valid_event_type("  *  ") is True


# ---------- Module wildcard ----------


def test_known_module_wildcard_valid():
    assert is_valid_event_type("pulse.*") is True
    assert is_valid_event_type("admin.*") is True
    assert is_valid_event_type("punchlist.*") is True


def test_unknown_module_wildcard_invalid():
    """Pin: `typo.*` rejected when typo not in AUDIT_MODULES."""
    assert is_valid_event_type("typo.*") is False
    assert is_valid_event_type("unknown.*") is False


# ---------- Literal patterns ----------


def test_known_module_literal_valid():
    assert is_valid_event_type("pulse.change_order.approve") is True
    assert is_valid_event_type("admin.cron.run_now") is True


def test_unknown_module_literal_invalid():
    assert is_valid_event_type("typo.change_order.approve") is False


def test_two_segment_literal_with_known_module_valid():
    """`webhook.test` — 2-segment literal with known module."""
    assert is_valid_event_type("webhook.test") is True


# ---------- Bare module without dot ----------


def test_bare_module_without_dot_invalid():
    """Pin: `pulse` (no dot) is NOT valid — must be either
    `pulse.*` (wildcard) or `pulse.X` (literal)."""
    assert is_valid_event_type("pulse") is False


# ---------- Empty / whitespace ----------


def test_empty_invalid():
    assert is_valid_event_type("") is False
    assert is_valid_event_type(None) is False


def test_whitespace_only_invalid():
    assert is_valid_event_type("   ") is False


# ---------- Case sensitivity ----------


def test_case_sensitive_module():
    """Pin: `PULSE.*` rejected. AUDIT_MODULES uses lowercase
    canonical names. Pin so a refactor that lowercases input
    silently doesn't enable case-mismatched event_types."""
    assert is_valid_event_type("PULSE.*") is False


def test_case_sensitive_literal():
    assert is_valid_event_type("PULSE.change_order.approve") is False


# ---------- validate_event_types ----------


def test_validate_all_valid():
    valid, rejected = validate_event_types(["*", "pulse.*", "webhook.test"])
    assert valid == ["*", "pulse.*", "webhook.test"]
    assert rejected == []


def test_validate_all_rejected():
    valid, rejected = validate_event_types(["typo.*", "", "no_dot"])
    assert valid == []
    assert rejected == ["typo.*", "", "no_dot"]


def test_validate_mixed():
    valid, rejected = validate_event_types(
        [
            "pulse.*",
            "typo.*",
            "*",
            "  pulse.change_order.approve  ",
            "",
        ]
    )
    assert valid == ["pulse.*", "*", "pulse.change_order.approve"]
    assert rejected == ["typo.*", ""]


def test_validate_strips_whitespace_in_valid():
    """Valid patterns are returned whitespace-stripped."""
    valid, _ = validate_event_types(["  pulse.*  "])
    assert valid == ["pulse.*"]


# ---------- Cross-cycle composition with Z2 ----------


def test_pin_z2_audit_modules_alignment():
    """Cardinal cross-cycle pin: every module in Z2's
    AUDIT_MODULES is a valid `module.*` event type. A refactor
    that adds a module to Z2 should automatically work here
    without explicit code changes."""
    for module in AUDIT_MODULES:
        assert is_valid_event_type(f"{module}.*") is True, f"{module}.* should be valid (Z2 says {module} is known)"


def test_pin_z2_audit_modules_literal_alignment():
    """Same alignment for literal patterns."""
    for module in AUDIT_MODULES:
        assert is_valid_event_type(f"{module}.x.y") is True, f"{module}.x.y should be valid"


# ---------- Realistic ----------


def test_realistic_subscription_create():
    """Realistic webhook subscription create — mix of wildcards
    and literals, with one typo."""
    valid, rejected = validate_event_types(
        [
            "pulse.*",
            "punchlist.list.create",
            "admin.cron.*",
            "typo.*",  # rejected
            "*",
        ]
    )
    assert "pulse.*" in valid
    assert "punchlist.list.create" in valid
    assert "admin.cron.*" in valid
    assert "*" in valid
    assert rejected == ["typo.*"]
