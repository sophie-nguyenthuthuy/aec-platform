"""HTTP Range header parser (cycle ZZ2).

Pinned seams:
  1. Three forms: closed, open-ended, suffix.
  2. start <= end strict.
  3. end clamped to total_size - 1.
  4. Suffix > total clamped to total.
  5. Only `bytes=` unit.
  6. Multipart rejected.
  7. total_size <= 0 → None.
"""

from __future__ import annotations

from services.range_header import Range, parse_range

# ---------- Closed range ----------


def test_closed_range_basic():
    assert parse_range("bytes=0-499", 1000) == Range(start=0, end=499, length=500)


def test_closed_range_first_byte():
    assert parse_range("bytes=0-0", 1000) == Range(start=0, end=0, length=1)


def test_closed_range_last_byte():
    assert parse_range("bytes=999-999", 1000) == Range(start=999, end=999, length=1)


def test_closed_range_full_file():
    assert parse_range("bytes=0-999", 1000) == Range(start=0, end=999, length=1000)


def test_closed_range_end_clamped():
    """end >= total_size clamped to total_size - 1 per RFC."""
    assert parse_range("bytes=0-9999", 1000) == Range(start=0, end=999, length=1000)


# ---------- Open-ended ----------


def test_open_ended_range():
    assert parse_range("bytes=500-", 1000) == Range(start=500, end=999, length=500)


def test_open_ended_from_zero():
    """Equivalent to full file."""
    assert parse_range("bytes=0-", 1000) == Range(start=0, end=999, length=1000)


def test_open_ended_start_at_eof_invalid():
    """start >= total_size → None."""
    assert parse_range("bytes=1000-", 1000) is None
    assert parse_range("bytes=2000-", 1000) is None


# ---------- Suffix ----------


def test_suffix_range():
    assert parse_range("bytes=-200", 1000) == Range(start=800, end=999, length=200)


def test_suffix_full_file():
    """Suffix == total → full file."""
    assert parse_range("bytes=-1000", 1000) == Range(start=0, end=999, length=1000)


def test_suffix_larger_than_total_clamped():
    """Cardinal pin: suffix length > total clamped to total."""
    assert parse_range("bytes=-2000", 1000) == Range(start=0, end=999, length=1000)


def test_suffix_zero_invalid():
    """`bytes=-0` (zero suffix) is invalid per RFC."""
    assert parse_range("bytes=-0", 1000) is None


# ---------- Invalid ----------


def test_start_greater_than_end_invalid():
    """Cardinal pin: start > end is invalid (NOT auto-swapped)."""
    assert parse_range("bytes=500-100", 1000) is None


def test_start_at_eof_invalid():
    """start >= total_size invalid for closed range too."""
    assert parse_range("bytes=1000-1100", 1000) is None


def test_negative_start_invalid():
    """Negative start (parsed as `-N` but appearing in middle of
    pattern would not match the regex anyway; defensive check)."""
    # The regex requires `bytes=DIGITS-DIGITS` so negatives
    # don't match. This test pins that behaviour.
    assert parse_range("bytes=-100-200", 1000) is None


def test_empty_range_invalid():
    """`bytes=-` (both sides empty) invalid."""
    assert parse_range("bytes=-", 1000) is None


def test_empty_string_invalid():
    """`bytes=` (no values) invalid."""
    assert parse_range("bytes=", 1000) is None


def test_garbage_invalid():
    assert parse_range("garbage", 1000) is None


def test_multipart_rejected():
    """Cardinal pin: multipart range (`bytes=0-99,200-299`) NOT
    supported. Caller re-implements multipart if needed."""
    assert parse_range("bytes=0-99,200-299", 1000) is None


def test_non_bytes_unit_rejected():
    """RFC allows other units; practice uses bytes only."""
    assert parse_range("items=0-99", 1000) is None
    assert parse_range("seconds=0-10", 1000) is None


# ---------- Case insensitivity ----------


def test_uppercase_bytes_accepted():
    assert parse_range("BYTES=0-99", 1000) == Range(start=0, end=99, length=100)


def test_mixed_case():
    assert parse_range("Bytes=0-99", 1000) == Range(start=0, end=99, length=100)


# ---------- Whitespace ----------


def test_strips_whitespace():
    assert parse_range("  bytes=0-99  ", 1000) == Range(start=0, end=99, length=100)


# ---------- Defensive ----------


def test_none_header():
    assert parse_range(None, 1000) is None


def test_empty_header():
    assert parse_range("", 1000) is None


def test_zero_total_size():
    """Degenerate file (empty)."""
    assert parse_range("bytes=0-99", 0) is None


def test_negative_total_size():
    assert parse_range("bytes=0-99", -1) is None


# ---------- Frozen ----------


def test_range_is_frozen():
    r = Range(start=0, end=99, length=100)
    try:
        r.start = 100  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Range should be frozen")
