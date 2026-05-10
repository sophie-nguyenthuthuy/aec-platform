"""VN postal code validator (cycle OO2).

Pinned seams:
  1. POSTAL_CODE_LENGTH = 6 (NOT 5 — pre-2018 form rejected).
  2. Province prefix band [01, 99] (matches FF1 CCCD).
  3. Whitespace stripped on parse.
  4. Non-digit reject.
  5. None / empty → None.
"""

from __future__ import annotations

from services.vn_postal_code import (
    POSTAL_CODE_LENGTH,
    POSTAL_PROVINCE_MAX,
    POSTAL_PROVINCE_MIN,
    is_valid_postal_code,
    parse_postal_code,
    postal_code_province_code,
)

# ---------- Constants ----------


def test_postal_code_length_is_6():
    """Cardinal pin: 6 digits (Vietnam Post 2018 reform). Pin
    so a refactor that accepts the pre-2018 5-digit form
    silently re-introduces legacy codes."""
    assert POSTAL_CODE_LENGTH == 6


def test_province_band_matches_cccd():
    """Same band as FF1's CCCD province codes."""
    assert POSTAL_PROVINCE_MIN == 1
    assert POSTAL_PROVINCE_MAX == 99


# ---------- Canonical valid ----------


def test_parse_canonical_hanoi():
    """100000 = Hanoi (province 10)."""
    assert parse_postal_code("100000") == "100000"


def test_parse_canonical_hcm():
    """700000 = Hồ Chí Minh (province 70)."""
    assert parse_postal_code("700000") == "700000"


def test_parse_canonical_da_nang():
    """550000 = Đà Nẵng (province 55)."""
    assert parse_postal_code("550000") == "550000"


def test_parse_at_min_province_boundary():
    """010000 = province 01."""
    assert parse_postal_code("010000") == "010000"


def test_parse_at_max_province_boundary():
    """990000 = province 99."""
    assert parse_postal_code("990000") == "990000"


# ---------- Length rejection ----------


def test_rejects_pre_2018_5_digits():
    """Cardinal pin: 5-digit pre-2018 form REJECTED. A migration
    import that accepts both forms would silently allow legacy
    codes alongside modern ones."""
    assert is_valid_postal_code("12345") is False


def test_rejects_too_short():
    assert is_valid_postal_code("12345") is False
    assert is_valid_postal_code("1234") is False


def test_rejects_too_long():
    assert is_valid_postal_code("1234567") is False
    assert is_valid_postal_code("12345678") is False


# ---------- Province band rejection ----------


def test_rejects_province_zero():
    """Province 00 is reserved / unassigned."""
    assert is_valid_postal_code("000000") is False


def test_province_above_99_unreachable():
    """For 6-digit input, first 2 digits max is 99 lexically;
    no need to test > 99 since `100000` is 6 digits with
    province=10 which is valid. The band check is for explicit
    `00` rejection only."""
    # 999999 → province 99 → valid.
    assert is_valid_postal_code("999999") is True


# ---------- Non-numeric rejection ----------


def test_rejects_non_digit_chars():
    assert is_valid_postal_code("abc456") is False
    assert is_valid_postal_code("12345a") is False
    assert is_valid_postal_code("100-000") is False
    assert is_valid_postal_code("100.000") is False


# ---------- Whitespace handling ----------


def test_strips_internal_whitespace():
    """Users paste from PDFs / contracts — strip."""
    assert parse_postal_code("100 000") == "100000"
    assert parse_postal_code("10 00 00") == "100000"


def test_strips_boundary_whitespace():
    assert parse_postal_code("  100000  ") == "100000"


def test_whitespace_only_returns_none():
    assert parse_postal_code("   ") is None


# ---------- Defensive ----------


def test_none_returns_none():
    assert parse_postal_code(None) is None


def test_empty_returns_none():
    assert parse_postal_code("") is None


# ---------- postal_code_province_code ----------


def test_province_code_extraction():
    assert postal_code_province_code("100000") == "10"
    assert postal_code_province_code("700000") == "70"
    assert postal_code_province_code("010000") == "01"
    assert postal_code_province_code("990000") == "99"


def test_province_code_none_for_invalid():
    assert postal_code_province_code(None) is None
    assert postal_code_province_code("") is None
    assert postal_code_province_code("invalid") is None
    assert postal_code_province_code("12345") is None  # 5 digits
    assert postal_code_province_code("000000") is None  # bad province


# ---------- is_valid_postal_code ----------


def test_is_valid_for_canonical():
    assert is_valid_postal_code("100000") is True


def test_is_valid_false_for_invalid():
    assert is_valid_postal_code(None) is False
    assert is_valid_postal_code("") is False
    assert is_valid_postal_code("invalid") is False
