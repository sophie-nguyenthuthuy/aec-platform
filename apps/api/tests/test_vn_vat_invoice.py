"""VN VAT invoice number validator (cycle AAA3).

Pinned seams:
  1. Format: <series>/<sequence>.
  2. Series 6-8 alphanumeric uppercase.
  3. Sequence 7-digit zero-padded on output.
  4. Sequence range [1, 9999999].
  5. Slash separator only.
  6. Round-trip stable.
"""

from __future__ import annotations

import pytest

from services.vn_vat_invoice import (
    MAX_SEQUENCE,
    SEQUENCE_LENGTH,
    SERIES_LENGTH_MAX,
    SERIES_LENGTH_MIN,
    InvoiceNumber,
    InvoiceSequenceExhausted,
    format_invoice_number,
    is_valid_invoice_number,
    next_invoice_number,
    parse_invoice_number,
)

# ---------- Constants ----------


def test_constants():
    assert SERIES_LENGTH_MIN == 6
    assert SERIES_LENGTH_MAX == 8
    assert SEQUENCE_LENGTH == 7
    assert MAX_SEQUENCE == 9_999_999


# ---------- parse_invoice_number ----------


def test_parse_canonical():
    result = parse_invoice_number("C25TAA/0000123")
    assert result == InvoiceNumber(series="C25TAA", sequence=123)


def test_parse_canonical_8_char_series():
    result = parse_invoice_number("C25TAABB/0000001")
    assert result == InvoiceNumber(series="C25TAABB", sequence=1)


def test_parse_non_zero_padded_sequence():
    """Pin: parser accepts non-padded sequence."""
    result = parse_invoice_number("C25TAA/123")
    assert result == InvoiceNumber(series="C25TAA", sequence=123)


def test_parse_sequence_at_max():
    result = parse_invoice_number("C25TAA/9999999")
    assert result is not None
    assert result.sequence == 9_999_999


def test_parse_sequence_at_one():
    result = parse_invoice_number("C25TAA/1")
    assert result == InvoiceNumber(series="C25TAA", sequence=1)


# ---------- Series validation ----------


def test_parse_series_too_short_rejected():
    """Series of 5 chars → invalid."""
    assert parse_invoice_number("C25TA/0000001") is None


def test_parse_series_too_long_rejected():
    """Series of 9 chars → invalid."""
    assert parse_invoice_number("C25TAABBC/0000001") is None


def test_parse_lowercase_series_rejected():
    """Cardinal pin: uppercase only. Tax authority assigns
    canonical uppercase series."""
    assert parse_invoice_number("c25taa/0000001") is None


def test_parse_mixed_case_series_rejected():
    assert parse_invoice_number("c25TAA/0000001") is None


def test_parse_special_chars_in_series_rejected():
    assert parse_invoice_number("C25-TAA/0000001") is None
    assert parse_invoice_number("C25_TAA/0000001") is None


# ---------- Sequence validation ----------


def test_parse_sequence_zero_rejected():
    """Pin: sequence starts at 1."""
    assert parse_invoice_number("C25TAA/0") is None
    assert parse_invoice_number("C25TAA/0000000") is None


def test_parse_sequence_over_max_rejected():
    assert parse_invoice_number("C25TAA/10000000") is None


def test_parse_sequence_8_digits_rejected():
    """Sequence pattern is at most 7 digits."""
    assert parse_invoice_number("C25TAA/12345678") is None


def test_parse_negative_sequence_rejected():
    assert parse_invoice_number("C25TAA/-1") is None


def test_parse_non_numeric_sequence_rejected():
    assert parse_invoice_number("C25TAA/ABC") is None


# ---------- Separator ----------


def test_parse_no_separator_rejected():
    assert parse_invoice_number("C25TAA0000123") is None


def test_parse_hyphen_separator_rejected():
    """Pin: slash only, no hyphen variant."""
    assert parse_invoice_number("C25TAA-0000123") is None


def test_parse_dash_separator_rejected():
    assert parse_invoice_number("C25TAA—0000123") is None


# ---------- Whitespace ----------


def test_parse_whitespace_stripped():
    assert parse_invoice_number("  C25TAA / 0000123  ") == (InvoiceNumber(series="C25TAA", sequence=123))


# ---------- Defensive ----------


def test_parse_none():
    assert parse_invoice_number(None) is None


def test_parse_empty():
    assert parse_invoice_number("") is None


def test_parse_whitespace_only():
    assert parse_invoice_number("   ") is None


# ---------- format_invoice_number ----------


def test_format_zero_padded():
    """Cardinal pin: 7-digit zero-padded output."""
    inv = InvoiceNumber(series="C25TAA", sequence=123)
    assert format_invoice_number(inv) == "C25TAA/0000123"


def test_format_at_max():
    inv = InvoiceNumber(series="C25TAA", sequence=9_999_999)
    assert format_invoice_number(inv) == "C25TAA/9999999"


def test_format_sequence_one():
    inv = InvoiceNumber(series="C25TAA", sequence=1)
    assert format_invoice_number(inv) == "C25TAA/0000001"


# ---------- Round-trip ----------


def test_round_trip_canonical():
    canonical = "C25TAA/0000123"
    parsed = parse_invoice_number(canonical)
    assert parsed is not None
    assert format_invoice_number(parsed) == canonical


def test_round_trip_canonicalizes_unpadded():
    """`C25TAA/123` → parses → formats to `C25TAA/0000123`."""
    parsed = parse_invoice_number("C25TAA/123")
    assert parsed is not None
    assert format_invoice_number(parsed) == "C25TAA/0000123"


# ---------- next_invoice_number ----------


def test_next_increments_by_one():
    next_inv = next_invoice_number("C25TAA", 122)
    assert next_inv == InvoiceNumber(series="C25TAA", sequence=123)


def test_next_from_zero():
    """last_seq=0 → next is 1."""
    next_inv = next_invoice_number("C25TAA", 0)
    assert next_inv.sequence == 1


def test_next_at_max_minus_one_succeeds():
    """last_seq = MAX-1 → next = MAX."""
    next_inv = next_invoice_number("C25TAA", MAX_SEQUENCE - 1)
    assert next_inv.sequence == MAX_SEQUENCE


def test_next_at_max_raises_exhausted():
    """Cardinal pin: last_seq = MAX → exhausted."""
    with pytest.raises(InvoiceSequenceExhausted):
        next_invoice_number("C25TAA", MAX_SEQUENCE)


def test_next_invalid_series_raises():
    with pytest.raises(ValueError):
        next_invoice_number("invalid", 1)
    with pytest.raises(ValueError):
        next_invoice_number("c25taa", 1)


def test_next_negative_last_seq_raises():
    with pytest.raises(ValueError):
        next_invoice_number("C25TAA", -1)


# ---------- is_valid_invoice_number ----------


def test_is_valid_for_canonical():
    assert is_valid_invoice_number("C25TAA/0000123") is True


def test_is_valid_false_for_invalid():
    assert is_valid_invoice_number(None) is False
    assert is_valid_invoice_number("") is False
    assert is_valid_invoice_number("invalid") is False
    assert is_valid_invoice_number("C25TAA/0") is False


# ---------- Frozen ----------


def test_invoice_number_is_frozen():
    inv = InvoiceNumber(series="C25TAA", sequence=1)
    try:
        inv.sequence = 2  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("InvoiceNumber should be frozen")
