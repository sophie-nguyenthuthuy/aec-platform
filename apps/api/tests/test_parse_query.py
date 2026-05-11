"""HTTP query string parser (cycle RR2).

Pinned seams:
  1. Repeated keys collected into list (order preserved).
  2. Single-occurrence keys yield string.
  3. Empty value preserved as "".
  4. No `=` in pair → empty value.
  5. Leading `?` stripped.
  6. Percent-decoding.
  7. None / empty → {}.
  8. Round-trip stable with PP3 build_canonical_query.
"""

from __future__ import annotations

from services.canonical_query import build_canonical_query
from services.parse_query import parse_query

# ---------- Empty ----------


def test_none_returns_empty_dict():
    assert parse_query(None) == {}


def test_empty_returns_empty_dict():
    assert parse_query("") == {}


def test_whitespace_only_returns_empty_dict():
    assert parse_query("   ") == {}


def test_only_question_mark_returns_empty_dict():
    assert parse_query("?") == {}


# ---------- Basic ----------


def test_single_pair():
    assert parse_query("a=1") == {"a": "1"}


def test_two_pairs():
    assert parse_query("a=1&b=2") == {"a": "1", "b": "2"}


def test_strips_leading_question_mark():
    assert parse_query("?a=1") == {"a": "1"}


def test_strips_leading_question_mark_with_pairs():
    assert parse_query("?a=1&b=2") == {"a": "1", "b": "2"}


# ---------- Repeated keys ----------


def test_repeated_keys_become_list():
    assert parse_query("a=1&a=2") == {"a": ["1", "2"]}


def test_three_repeats():
    assert parse_query("a=1&a=2&a=3") == {"a": ["1", "2", "3"]}


def test_repeats_preserve_order():
    """Cardinal pin: list reflects URL order, NOT alphabetical
    or some other reordering."""
    assert parse_query("a=z&a=y&a=x") == {"a": ["z", "y", "x"]}


def test_mixed_single_and_repeat():
    assert parse_query("a=1&b=2&a=3") == {"a": ["1", "3"], "b": "2"}


# ---------- Empty values ----------


def test_empty_value_preserved():
    """Cardinal pin: `a=` is DISTINCT from missing key — preserves
    user's intent (e.g., explicitly clear filter)."""
    assert parse_query("a=") == {"a": ""}


def test_empty_value_with_other_pairs():
    assert parse_query("a=&b=2") == {"a": "", "b": "2"}


def test_no_equals_treats_as_empty_value():
    """Pin: `a` (no `=`) → `{"a": ""}` (defensive parsing)."""
    assert parse_query("a") == {"a": ""}


def test_repeated_no_equals():
    assert parse_query("a&a") == {"a": ["", ""]}


# ---------- Percent-decoding ----------


def test_decodes_percent_20_as_space():
    assert parse_query("a=hello%20world") == {"a": "hello world"}


def test_decodes_unicode():
    """UTF-8 percent escapes decode to Unicode."""
    assert parse_query("name=H%C3%A0%20N%E1%BB%99i") == {"name": "Hà Nội"}


def test_decodes_special_chars():
    assert parse_query("k=a%26b%3Dc") == {"k": "a&b=c"}


def test_decodes_keys_too():
    """Pin: keys also percent-decoded."""
    assert parse_query("a%20key=1") == {"a key": "1"}


# ---------- Empty pair segments ----------


def test_empty_pair_segments_skipped():
    """`a=1&&b=2` (empty between commas) — empty segments skipped."""
    assert parse_query("a=1&&b=2") == {"a": "1", "b": "2"}


def test_trailing_ampersand():
    assert parse_query("a=1&") == {"a": "1"}


def test_leading_ampersand():
    assert parse_query("&a=1") == {"a": "1"}


# ---------- Round-trip with PP3 ----------


def test_round_trip_simple():
    """Cardinal cross-cycle pin: PP3 + RR2 round-trip stable."""
    original = {"a": "1", "b": "2"}
    serialized = build_canonical_query(original)
    parsed = parse_query(serialized)
    assert parsed == original


def test_round_trip_with_list():
    original = {"tags": ["x", "y", "z"]}
    serialized = build_canonical_query(original)
    parsed = parse_query(serialized)
    assert parsed == original


def test_round_trip_with_special_chars():
    original = {"q": "hello world", "k": "a&b=c"}
    serialized = build_canonical_query(original)
    parsed = parse_query(serialized)
    assert parsed == original


def test_round_trip_with_unicode():
    original = {"name": "Hà Nội"}
    serialized = build_canonical_query(original)
    parsed = parse_query(serialized)
    assert parsed == original


def test_round_trip_realistic_audit_filter():
    """Realistic audit-page filter query round-trip."""
    original = {
        "since": "2026-01-01",
        "actor": "user@example.com",
        "modules": ["pulse", "submittals"],
        "page": "1",
    }
    serialized = build_canonical_query(original)
    parsed = parse_query(serialized)
    assert parsed == original


def test_round_trip_drops_none_values():
    """Pin: PP3 DROPS None values on serialize. Round-trip yields
    a dict without those keys."""
    original_with_none = {"a": "1", "b": None}
    serialized = build_canonical_query(original_with_none)
    parsed = parse_query(serialized)
    assert parsed == {"a": "1"}


def test_round_trip_preserves_empty_string_value():
    """Pin: empty string `""` SURVIVES round-trip (distinct from
    None which is dropped)."""
    original = {"a": "1", "b": ""}
    serialized = build_canonical_query(original)
    parsed = parse_query(serialized)
    assert parsed == original


# ---------- Edge cases ----------


def test_empty_key_preserved():
    """Edge case: `=value` (no key) → empty key."""
    assert parse_query("=value") == {"": "value"}


def test_value_with_equals():
    """Pin: only first `=` separates key/value. Subsequent `=`
    is part of the value."""
    assert parse_query("a=b=c") == {"a": "b=c"}
