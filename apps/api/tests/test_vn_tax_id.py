"""Vietnamese tax ID (MST) validator (cycle EE2).

Pinned seams:
  1. 10-digit core required (NOT 13 — that's CCCD).
  2. Optional 3-digit branch suffix `-XXX`.
  3. Checksum: weighted-sum mod 11 with weights (31, 29, 23, 19, 17, 13, 7, 5, 3).
  4. Checksum result 10 maps to 0 (VN validator fallback).
  5. Whitespace stripped on parse but no other characters tolerated.
  6. Branch suffix must be EXACTLY 3 digits (not 1, 4, etc).
  7. None / empty / non-numeric → None.
"""

from __future__ import annotations

from services.vn_tax_id import (
    _compute_check_digit,
    is_valid_mst,
    parse_mst,
)

# ---------- Check digit ----------


def test_compute_check_digit_canonical_example():
    """Pin a worked example so a refactor that flips weights
    breaks here. weights × digits = 31×0+29×1+23×2+19×3+17×4
    +13×5+7×6+5×7+3×8 = 366; 366 mod 11 = 3; check = 10-3 = 7."""
    assert _compute_check_digit("012345678") == 7


def test_compute_check_digit_low_value():
    """100000000: 31×1 = 31; 31 mod 11 = 9; check = 10-9 = 1."""
    assert _compute_check_digit("100000000") == 1


def test_compute_check_digit_remainder_zero_maps_to_ten_then_zero():
    """100000004: 31+12 = 43; 43 mod 11 = 10; check = 10-10 = 0.
    Pin the fallback: when the strict algorithm produces 10
    (one digit too many), the official VN validator maps to 0."""
    assert _compute_check_digit("100000004") == 0


# ---------- Canonical valid MSTs ----------


def test_valid_mst_10_digit_core():
    """`0123456787` — 9 digits + check digit 7 (computed above)."""
    assert is_valid_mst("0123456787") is True


def test_valid_mst_with_branch_suffix():
    assert is_valid_mst("0123456787-001") is True
    assert is_valid_mst("0123456787-999") is True


def test_valid_mst_check_digit_zero_case():
    """The fallback case — `1000000040` has check digit 0."""
    assert is_valid_mst("1000000040") is True


# ---------- Invalid checksums ----------


def test_invalid_checksum_rejected():
    """Last digit doesn't match the computed check — reject."""
    assert is_valid_mst("0123456788") is False
    assert is_valid_mst("0123456789") is False


def test_invalid_checksum_with_valid_branch_rejected():
    """A bad core checksum + valid branch suffix is still
    invalid — pin so a refactor that validates only structure
    doesn't slip a typo through."""
    assert is_valid_mst("0123456788-001") is False


# ---------- Wrong lengths ----------


def test_too_short_rejected():
    assert is_valid_mst("12345") is False
    assert is_valid_mst("012345678") is False  # 9 digits


def test_too_long_rejected():
    """11 digits — pin so MST isn't confused with VN CCCD
    (citizen ID, 12 digits) or any other 11+ digit identifier."""
    assert is_valid_mst("01234567890") is False
    assert is_valid_mst("123456789012") is False  # 12 digits (CCCD-like)


# ---------- Branch suffix rules ----------


def test_branch_suffix_must_be_three_digits():
    """Pin: branch suffix is EXACTLY 3 digits — not 1, 2, or 4."""
    assert is_valid_mst("0123456787-1") is False
    assert is_valid_mst("0123456787-12") is False
    assert is_valid_mst("0123456787-0001") is False


def test_branch_suffix_must_be_numeric():
    assert is_valid_mst("0123456787-abc") is False
    assert is_valid_mst("0123456787-A01") is False


def test_branch_suffix_separator_must_be_hyphen():
    """Pin: only `-` separator. Underscore / dot / slash all reject."""
    assert is_valid_mst("0123456787_001") is False
    assert is_valid_mst("0123456787.001") is False
    assert is_valid_mst("0123456787/001") is False


# ---------- Whitespace ----------


def test_whitespace_stripped_in_core():
    """Users paste from PDFs / contracts with spaces — strip."""
    assert is_valid_mst("0123 4567 87") is True
    assert is_valid_mst("01 23 45 67 87") is True


def test_whitespace_stripped_around_branch():
    assert is_valid_mst("0123456787 - 001") is True


def test_leading_trailing_whitespace_stripped():
    assert is_valid_mst("  0123456787  ") is True


def test_internal_non_whitespace_chars_rejected():
    """Pin: only whitespace is tolerated. Hyphens inside the core
    (other than the branch separator) reject."""
    assert is_valid_mst("01-23-45-67-87") is False
    assert is_valid_mst("0123,456787") is False


# ---------- Defensive ----------


def test_none_and_empty_rejected():
    assert is_valid_mst(None) is False
    assert is_valid_mst("") is False
    assert is_valid_mst("   ") is False  # all-whitespace strips to ""


def test_non_numeric_rejected():
    assert is_valid_mst("abcdefghij") is False
    assert is_valid_mst("INVALID") is False
    assert is_valid_mst("0123abc787") is False


# ---------- parse_mst ----------


def test_parse_returns_canonical_form_for_core():
    assert parse_mst("0123456787") == "0123456787"


def test_parse_returns_canonical_form_for_branch():
    assert parse_mst("0123456787-001") == "0123456787-001"


def test_parse_strips_whitespace_to_canonical():
    assert parse_mst("0123 4567 87") == "0123456787"
    assert parse_mst("0123456787 - 001") == "0123456787-001"


def test_parse_returns_none_for_invalid():
    assert parse_mst(None) is None
    assert parse_mst("") is None
    assert parse_mst("invalid") is None
    assert parse_mst("0123456788") is None  # bad checksum
    assert parse_mst("0123456787-1") is None  # short branch
