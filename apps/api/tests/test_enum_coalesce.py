"""Enum coalescer (cycle RR1, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/coalesce-enum.test.ts`):
  1. Exact match preferred.
  2. Case-insensitive fallback.
  3. Whitespace stripped.
  4. Empty / no-match → default.
  5. Cross-language byte-for-byte parity.
"""

from __future__ import annotations

from services.enum_coalesce import coalesce_enum

# ---------- Exact match ----------


def test_exact_match():
    assert coalesce_enum("open", ["open", "closed"]) == "open"


def test_exact_match_preferred_over_case_insensitive():
    """Cardinal pin: when both `Open` and `OPEN` in choices,
    exact case match wins."""
    assert coalesce_enum("Open", ["Open", "OPEN"]) == "Open"
    assert coalesce_enum("OPEN", ["Open", "OPEN"]) == "OPEN"


# ---------- Case-insensitive ----------


def test_uppercase_input_matches_lowercase_canonical():
    assert coalesce_enum("OPEN", ["open", "closed"]) == "open"


def test_mixed_case_input():
    assert coalesce_enum("oPeN", ["open"]) == "open"


def test_returns_canonical_not_input():
    """Pin: result is from `choices`, not the user's input case."""
    assert coalesce_enum("OPEN", ["open"]) == "open"


def test_first_match_wins_on_case_insensitive():
    """Two choices lowercasing to same — first in iteration order wins."""
    assert coalesce_enum("foo", ["FOO", "Foo"]) == "FOO"


# ---------- Whitespace ----------


def test_strips_input_whitespace():
    assert coalesce_enum("  open  ", ["open"]) == "open"
    assert coalesce_enum("\topen\n", ["open"]) == "open"


def test_strips_choice_whitespace():
    """Pin: choices with internal whitespace match input
    after both are stripped."""
    assert coalesce_enum("open", [" open "]) == " open "


# ---------- Defaults ----------


def test_no_match_default_none():
    assert coalesce_enum("nope", ["open", "closed"]) is None


def test_no_match_custom_default():
    assert coalesce_enum("nope", ["open"], "fallback") == "fallback"


def test_none_input_returns_default():
    assert coalesce_enum(None, ["open"], "x") == "x"


def test_empty_input_returns_default():
    assert coalesce_enum("", ["open"], "x") == "x"


def test_whitespace_only_input_returns_default():
    assert coalesce_enum("   ", ["open"], "x") == "x"


def test_empty_choices_returns_default():
    assert coalesce_enum("open", [], "x") == "x"


# ---------- Iterable choices ----------


def test_accepts_generator_choices():
    """Iterable parameter — supports generators / lazy iteration."""

    def gen():
        yield "open"
        yield "closed"

    assert coalesce_enum("OPEN", gen()) == "open"


def test_accepts_set_choices():
    """Set is order-undefined but should still match."""
    result = coalesce_enum("foo", {"foo", "bar"})
    assert result == "foo"


# ---------- Realistic shapes ----------


def test_role_lookup():
    """Use case: role from request body."""
    ROLES = ["owner", "admin", "member", "viewer"]
    assert coalesce_enum("Admin", ROLES) == "admin"
    assert coalesce_enum("OWNER", ROLES) == "owner"
    assert coalesce_enum("Guest", ROLES) is None


def test_status_filter_chip():
    """Use case: punchlist status filter."""
    STATUSES = ["open", "in_progress", "resolved", "verified", "closed"]
    assert coalesce_enum("IN_PROGRESS", STATUSES) == "in_progress"
    assert coalesce_enum("Verified", STATUSES) == "verified"


# ---------- Cross-language consistency ----------


def test_matches_ts_half_byte_for_byte():
    """Cross-language pin: TS and Python halves coalesce identically."""
    cases = [
        ("open", ["open", "closed"], None, "open"),
        ("OPEN", ["open", "closed"], None, "open"),
        ("  open  ", ["open"], None, "open"),
        ("nope", ["open"], "fallback", "fallback"),
        (None, ["open"], "x", "x"),
        ("", ["open"], "x", "x"),
        ("open", [], "x", "x"),
        ("Open", ["Open", "OPEN"], None, "Open"),
        ("foo", ["FOO", "Foo"], None, "FOO"),
    ]
    for input_str, choices, default, expected in cases:
        assert coalesce_enum(input_str, choices, default) == expected, (
            f"coalesce_enum({input_str!r}, {choices}, {default!r}) = "
            f"{coalesce_enum(input_str, choices, default)!r}, "
            f"expected {expected!r}"
        )
