"""File hash prefix display (cycle PP1, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/format-hash-prefix.test.ts`):
  1. ELLIPSIS = "…" (U+2026, single char).
  2. Default length 7 (git-style).
  3. Length out of [4, 64] → "".
  4. Lowercased output.
  5. Whitespace + outer quotes stripped.
  6. Non-hex → "".
  7. Length >= digest length → no ellipsis.
  8. Cross-language byte-for-byte parity with TS half.
"""

from __future__ import annotations

from services.format_hash_prefix import (
    DEFAULT_HASH_PREFIX_LENGTH,
    ELLIPSIS,
    MAX_HASH_PREFIX_LENGTH,
    MIN_HASH_PREFIX_LENGTH,
    format_hash_prefix,
)

# ---------- Constants ----------


def test_min_hash_prefix_length():
    assert MIN_HASH_PREFIX_LENGTH == 4


def test_max_hash_prefix_length():
    """Full SHA-256 digest is 64 hex chars."""
    assert MAX_HASH_PREFIX_LENGTH == 64


def test_default_length_matches_git():
    assert DEFAULT_HASH_PREFIX_LENGTH == 7


def test_ellipsis_is_unicode_single_char():
    """Cardinal pin: U+2026 horizontal ellipsis, NOT three ASCII
    dots. Pin so a refactor that swaps to `...` surfaces here."""
    assert ELLIPSIS == "…"
    assert len(ELLIPSIS) == 1
    assert ELLIPSIS != "..."


# ---------- Truncation ----------


def test_truncate_default_length():
    assert format_hash_prefix("a1b2c3d4e5f6") == "a1b2c3d…"


def test_truncate_custom_length():
    assert format_hash_prefix("a1b2c3d4e5f6", 4) == "a1b2…"


def test_at_max_length_no_ellipsis():
    sha = "a" * 64
    assert format_hash_prefix(sha, 64) == sha


def test_full_digest_when_length_ge_digest():
    assert format_hash_prefix("a1b2c3", 7) == "a1b2c3"
    assert format_hash_prefix("a1b2c3", 6) == "a1b2c3"


# ---------- Case folding ----------


def test_uppercase_lowercases():
    assert format_hash_prefix("A1B2C3D4E5F6") == "a1b2c3d…"


def test_mixed_case_lowercases():
    assert format_hash_prefix("AbCdEf01234") == "abcdef0…"


# ---------- Whitespace + quotes ----------


def test_strips_boundary_whitespace():
    assert format_hash_prefix("  a1b2c3d4e5f6  ") == "a1b2c3d…"


def test_strips_outer_double_quotes():
    assert format_hash_prefix('"a1b2c3d4e5f6"') == "a1b2c3d…"


def test_strips_outer_single_quotes():
    assert format_hash_prefix("'a1b2c3d4e5f6'") == "a1b2c3d…"


def test_does_not_strip_mismatched_quotes():
    """Pin: `"abc'` is not a valid quoted string. The mismatched
    quotes remain, then the hex check fails → ""."""
    assert format_hash_prefix("\"a1b2c3'") == ""


# ---------- Length bounds ----------


def test_length_below_min_returns_empty():
    """Cardinal pin: out-of-range length → "" (NOT clamped).
    Surfaces config bugs rather than silently truncating."""
    assert format_hash_prefix("a1b2c3d4", 3) == ""
    assert format_hash_prefix("a1b2c3d4", 0) == ""


def test_length_above_max_returns_empty():
    assert format_hash_prefix("a1b2c3d4", 65) == ""
    assert format_hash_prefix("a1b2c3d4", 100) == ""


def test_length_at_min_boundary():
    assert format_hash_prefix("a1b2c3d4", 4) == "a1b2…"


def test_length_at_max_boundary():
    sha = "a" * 64
    assert format_hash_prefix(sha, 64) == sha


# ---------- Non-hex ----------


def test_non_hex_chars_rejected():
    assert format_hash_prefix("not-a-hash") == ""
    assert format_hash_prefix("ghijkl") == ""  # g+ not hex
    assert format_hash_prefix("a1b2c3z") == ""


def test_internal_spaces_rejected():
    assert format_hash_prefix("a1 b2c3") == ""


# ---------- Defensive ----------


def test_none_returns_empty():
    assert format_hash_prefix(None) == ""


def test_empty_returns_empty():
    assert format_hash_prefix("") == ""


def test_whitespace_only_returns_empty():
    assert format_hash_prefix("   ") == ""


# ---------- Cross-language consistency ----------


def test_matches_ts_half_byte_for_byte():
    """Cross-language pin: TS and Python halves produce the same
    output for every input. A divergence (e.g. one half using
    `...` for ellipsis) would surface here."""
    cases = [
        ("a1b2c3d4e5f6", "a1b2c3d…"),
        ("A1B2C3D4E5F6", "a1b2c3d…"),
        ("  a1b2c3d4e5f6  ", "a1b2c3d…"),
        ('"a1b2c3d4e5f6"', "a1b2c3d…"),
        ("a1b2c3", "a1b2c3"),
        ("not-hex", ""),
        ("", ""),
        (None, ""),
    ]
    for input_text, expected in cases:
        assert format_hash_prefix(input_text) == expected, (
            f"format_hash_prefix({input_text!r}) = {format_hash_prefix(input_text)!r}, expected {expected!r}"
        )
