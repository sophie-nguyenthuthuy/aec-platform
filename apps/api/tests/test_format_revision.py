"""Estimate revision number formatter (cycle BBB2, Python half).

Pinned seams:
  1. Format: <PREFIX>-<YYYY>-<NNN>[/r<R>].
  2. Prefix 2-4 uppercase letters (no digits).
  3. Sequence 3-digit zero-padded on output.
  4. Sequence range [1, 999], revision [0, 999].
  5. Year range [2020, 2099].
  6. revision=0 omits /r suffix; revision>=1 includes it.
  7. `/r0` on parse → None (canonical form omits).
  8. Round-trip stable.
  9. Cross-language byte-for-byte parity with TS half.
"""

from __future__ import annotations

import pytest

from services.format_revision import (
    MAX_REVISION,
    MAX_SEQUENCE,
    MAX_YEAR,
    MIN_YEAR,
    PREFIX_LENGTH_MAX,
    PREFIX_LENGTH_MIN,
    SEQUENCE_LENGTH,
    RevisionNumber,
    format_revision_number,
    is_valid_revision_number,
    next_revision,
    parse_revision_number,
)

# ---------- Constants ----------


def test_constants():
    assert PREFIX_LENGTH_MIN == 2
    assert PREFIX_LENGTH_MAX == 4
    assert SEQUENCE_LENGTH == 3
    assert MAX_SEQUENCE == 999
    assert MAX_REVISION == 999
    assert MIN_YEAR == 2020
    assert MAX_YEAR == 2099


# ---------- Parse — base ----------


def test_parse_canonical_base():
    assert parse_revision_number("EST-2026-001") == RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=1,
        revision=0,
    )


def test_parse_non_padded_sequence():
    """Pin: parser accepts non-padded sequence."""
    assert parse_revision_number("EST-2026-1") == RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=1,
        revision=0,
    )


def test_parse_4_char_prefix():
    assert parse_revision_number("RFII-2026-001") == RevisionNumber(
        prefix="RFII",
        year=2026,
        sequence=1,
        revision=0,
    )


def test_parse_2_char_prefix():
    assert parse_revision_number("CO-2026-001") == RevisionNumber(
        prefix="CO",
        year=2026,
        sequence=1,
        revision=0,
    )


def test_parse_sequence_at_max():
    assert parse_revision_number("EST-2026-999") == RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=999,
        revision=0,
    )


def test_parse_whitespace_stripped():
    assert parse_revision_number("  EST-2026-001  ") == RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=1,
        revision=0,
    )


# ---------- Parse — revised ----------


def test_parse_r2():
    assert parse_revision_number("EST-2026-001/r2") == RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=1,
        revision=2,
    )


def test_parse_r_at_max():
    assert parse_revision_number(
        "EST-2026-001/r999",
    ) == RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=1,
        revision=999,
    )


def test_parse_r0_rejected():
    """Cardinal pin: `/r0` is NOT canonical (base omits suffix)."""
    assert parse_revision_number("EST-2026-001/r0") is None


def test_parse_r_over_max_rejected():
    assert parse_revision_number("EST-2026-001/r1000") is None


# ---------- Parse — rejection ----------


def test_parse_lowercase_prefix_rejected():
    assert parse_revision_number("est-2026-001") is None


def test_parse_prefix_with_digit_rejected():
    """Cardinal pin: digits in prefix would collide with year."""
    assert parse_revision_number("ES1-2026-001") is None


def test_parse_1_char_prefix_rejected():
    assert parse_revision_number("E-2026-001") is None


def test_parse_5_char_prefix_rejected():
    assert parse_revision_number("ESTIM-2026-001") is None


def test_parse_sequence_zero_rejected():
    assert parse_revision_number("EST-2026-000") is None
    assert parse_revision_number("EST-2026-0") is None


def test_parse_4_digit_sequence_rejected():
    assert parse_revision_number("EST-2026-1000") is None


def test_parse_year_before_min_rejected():
    assert parse_revision_number("EST-2019-001") is None


def test_parse_year_after_max_rejected():
    assert parse_revision_number("EST-2100-001") is None


def test_parse_wrong_separator_rejected():
    assert parse_revision_number("EST_2026_001") is None
    assert parse_revision_number("EST.2026.001") is None


def test_parse_uppercase_R_rejected():
    """Pin: revision tag is lowercase `r` only."""
    assert parse_revision_number("EST-2026-001/R2") is None


def test_parse_none_empty():
    assert parse_revision_number(None) is None
    assert parse_revision_number("") is None
    assert parse_revision_number("   ") is None


def test_parse_garbage():
    assert parse_revision_number("not-a-revision") is None
    assert parse_revision_number("EST") is None


# ---------- Format ----------


def test_format_base():
    assert (
        format_revision_number(
            RevisionNumber(prefix="EST", year=2026, sequence=1, revision=0),
        )
        == "EST-2026-001"
    )


def test_format_revised():
    assert (
        format_revision_number(
            RevisionNumber(prefix="EST", year=2026, sequence=1, revision=2),
        )
        == "EST-2026-001/r2"
    )


def test_format_zero_pads_sequence():
    assert (
        format_revision_number(
            RevisionNumber(prefix="EST", year=2026, sequence=7, revision=0),
        )
        == "EST-2026-007"
    )


def test_format_does_not_pad_revision():
    """Cardinal pin: revision is NOT zero-padded."""
    assert (
        format_revision_number(
            RevisionNumber(prefix="EST", year=2026, sequence=1, revision=2),
        )
        == "EST-2026-001/r2"
    )
    assert (
        format_revision_number(
            RevisionNumber(prefix="EST", year=2026, sequence=1, revision=12),
        )
        == "EST-2026-001/r12"
    )


def test_format_invalid_prefix_raises():
    with pytest.raises(ValueError):
        format_revision_number(
            RevisionNumber(prefix="est", year=2026, sequence=1, revision=0),
        )


def test_format_year_out_of_range_raises():
    with pytest.raises(ValueError):
        format_revision_number(
            RevisionNumber(prefix="EST", year=1999, sequence=1, revision=0),
        )


def test_format_sequence_zero_raises():
    with pytest.raises(ValueError):
        format_revision_number(
            RevisionNumber(prefix="EST", year=2026, sequence=0, revision=0),
        )


def test_format_revision_over_max_raises():
    with pytest.raises(ValueError):
        format_revision_number(
            RevisionNumber(
                prefix="EST",
                year=2026,
                sequence=1,
                revision=1000,
            ),
        )


# ---------- is_valid_revision_number ----------


def test_is_valid_for_canonical():
    assert is_valid_revision_number("EST-2026-001") is True
    assert is_valid_revision_number("EST-2026-001/r2") is True


def test_is_valid_false_for_invalid():
    assert is_valid_revision_number(None) is False
    assert is_valid_revision_number("") is False
    assert is_valid_revision_number("invalid") is False
    assert is_valid_revision_number("EST-2026-000") is False


# ---------- Round-trip ----------


def test_round_trip_canonical_base():
    canonical = "EST-2026-001"
    parsed = parse_revision_number(canonical)
    assert parsed is not None
    assert format_revision_number(parsed) == canonical


def test_round_trip_canonical_revised():
    canonical = "EST-2026-042/r3"
    parsed = parse_revision_number(canonical)
    assert parsed is not None
    assert format_revision_number(parsed) == canonical


def test_round_trip_canonicalizes_unpadded():
    parsed = parse_revision_number("EST-2026-1")
    assert parsed is not None
    assert format_revision_number(parsed) == "EST-2026-001"


# ---------- next_revision ----------


def test_next_zero_to_one():
    base = RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=1,
        revision=0,
    )
    assert next_revision(base).revision == 1


def test_next_two_to_three():
    r2 = RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=1,
        revision=2,
    )
    assert next_revision(r2).revision == 3


def test_next_preserves_other_fields():
    r = RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=42,
        revision=0,
    )
    nxt = next_revision(r)
    assert nxt.prefix == "EST"
    assert nxt.year == 2026
    assert nxt.sequence == 42


def test_next_at_max_raises():
    at_max = RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=1,
        revision=MAX_REVISION,
    )
    with pytest.raises(ValueError):
        next_revision(at_max)


# ---------- Cross-language parity ----------


def test_cross_language_parity_canonical_base():
    """Cardinal pin: byte-for-byte same as TS format."""
    assert (
        format_revision_number(
            RevisionNumber(prefix="EST", year=2026, sequence=1, revision=0),
        )
        == "EST-2026-001"
    )


def test_cross_language_parity_revised():
    assert (
        format_revision_number(
            RevisionNumber(prefix="CO", year=2026, sequence=12, revision=1),
        )
        == "CO-2026-012/r1"
    )


# ---------- Realistic ----------


def test_realistic_initial_bid():
    assert (
        format_revision_number(
            RevisionNumber(prefix="EST", year=2026, sequence=1, revision=0),
        )
        == "EST-2026-001"
    )


def test_realistic_change_order_revised():
    assert (
        format_revision_number(
            RevisionNumber(prefix="CO", year=2026, sequence=12, revision=1),
        )
        == "CO-2026-012/r1"
    )


def test_realistic_rfi_4char_prefix():
    assert (
        format_revision_number(
            RevisionNumber(prefix="RFII", year=2026, sequence=7, revision=0),
        )
        == "RFII-2026-007"
    )


# ---------- Frozen ----------


def test_revision_number_is_frozen():
    rev = RevisionNumber(
        prefix="EST",
        year=2026,
        sequence=1,
        revision=0,
    )
    try:
        rev.sequence = 2  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("RevisionNumber should be frozen")
