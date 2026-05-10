"""VN bank account number formatter (cycle HH2, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/format-bank-account.test.ts`):
  1. VN_BANKS has 12 entries (closed registry).
  2. MIN/MAX = 8/19 digits.
  3. Right-aligned 4-digit grouping (LAST group always 4).
  4. Leading zeros preserved.
  5. Whitespace + hyphens stripped on parse.
  6. Non-digit chars → None.
  7. bank_display_name case-insensitive.
  8. None / empty / out-of-range → None/empty.
  9. Cross-language byte-for-byte parity with TS half.
"""

from __future__ import annotations

from services.format_bank_account import (
    MAX_BANK_ACCOUNT_LENGTH,
    MIN_BANK_ACCOUNT_LENGTH,
    VN_BANKS,
    bank_display_name,
    format_bank_account,
    parse_bank_account,
)

# ---------- VN_BANKS ----------


def test_vn_banks_has_twelve_entries():
    assert len(VN_BANKS) == 12


def test_vn_banks_canonical_entries():
    assert VN_BANKS["VCB"] == "Vietcombank"
    assert VN_BANKS["TCB"] == "Techcombank"
    assert VN_BANKS["BIDV"] == "BIDV"
    assert VN_BANKS["ACB"] == "ACB"


def test_vn_banks_keys_are_uppercase():
    for code in VN_BANKS:
        assert code == code.upper(), f"{code!r} should be uppercase"


# ---------- Constants ----------


def test_min_length_is_8():
    """Legacy 8-digit accounts still active at older banks."""
    assert MIN_BANK_ACCOUNT_LENGTH == 8


def test_max_length_is_19():
    assert MAX_BANK_ACCOUNT_LENGTH == 19


# ---------- parse_bank_account ----------


def test_parse_canonical_at_min():
    assert parse_bank_account("12345678") == "12345678"


def test_parse_canonical_at_max():
    max_account = "1" * 19
    assert parse_bank_account(max_account) == max_account


def test_parse_strips_whitespace():
    assert parse_bank_account("1234 5678 9012") == "123456789012"
    assert parse_bank_account("  1234 5678  ") == "12345678"


def test_parse_strips_hyphens():
    assert parse_bank_account("1234-5678-9012") == "123456789012"


def test_parse_preserves_leading_zeros():
    """Some VN banks issue accounts with leading zeros — pin so
    a refactor that strips them via int() conversion doesn't
    silently lose precision."""
    assert parse_bank_account("00123456") == "00123456"


def test_parse_rejects_too_short():
    assert parse_bank_account("1234567") is None  # 7 digits


def test_parse_rejects_too_long():
    assert parse_bank_account("1" * 20) is None


def test_parse_rejects_non_digit():
    assert parse_bank_account("12345678abc") is None
    assert parse_bank_account("1234.5678") is None


def test_parse_rejects_none_and_empty():
    assert parse_bank_account(None) is None
    assert parse_bank_account("") is None


# ---------- format_bank_account ----------


def test_format_8_digits_as_4_4():
    assert format_bank_account("12345678") == "1234 5678"


def test_format_9_digits_as_1_4_4():
    """Cardinal pin: right-aligned. LEADING group has remainder
    (1 digit here), LAST group always 4."""
    assert format_bank_account("123456789") == "1 2345 6789"


def test_format_11_digits_as_3_4_4():
    assert format_bank_account("12345678901") == "123 4567 8901"


def test_format_16_digits_as_4_4_4_4():
    assert format_bank_account("1234567890123456") == "1234 5678 9012 3456"


def test_format_19_digits_as_3_4_4_4_4():
    assert format_bank_account("1234567890123456789") == "123 4567 8901 2345 6789"


def test_format_12_digits_no_leading_short_group():
    """When count is multiple of 4, no leading short group."""
    assert format_bank_account("123456789012") == "1234 5678 9012"


def test_format_round_trips_already_formatted():
    assert format_bank_account("1234 5678") == "1234 5678"
    assert format_bank_account("1234 5678 9012") == "1234 5678 9012"


def test_format_strips_and_regroups_non_canonical_spacing():
    assert format_bank_account("12 34 56 78") == "1234 5678"


def test_format_preserves_leading_zeros():
    assert format_bank_account("00123456") == "0012 3456"


def test_format_returns_empty_for_invalid():
    assert format_bank_account(None) == ""
    assert format_bank_account("") == ""
    assert format_bank_account("invalid") == ""
    assert format_bank_account("1234567") == ""  # too short
    assert format_bank_account("1" * 20) == ""  # too long


# ---------- bank_display_name ----------


def test_bank_display_name_known_code():
    assert bank_display_name("VCB") == "Vietcombank"
    assert bank_display_name("TCB") == "Techcombank"


def test_bank_display_name_case_insensitive():
    assert bank_display_name("vcb") == "Vietcombank"
    assert bank_display_name("Vcb") == "Vietcombank"


def test_bank_display_name_unknown_returns_none():
    assert bank_display_name("UNKNOWN") is None
    assert bank_display_name("XYZ") is None


def test_bank_display_name_none_and_empty():
    assert bank_display_name(None) is None
    assert bank_display_name("") is None


# ---------- Cross-language consistency ----------


def test_matches_ts_half_byte_for_byte():
    """Cross-language pin: TS and Python halves format identically.
    A divergence (e.g. one half left-aligned grouping) would
    surface here."""
    cases = [
        ("12345678", "1234 5678"),
        ("123456789", "1 2345 6789"),
        ("12345678901", "123 4567 8901"),
        ("1234567890123456", "1234 5678 9012 3456"),
        ("1234567890123456789", "123 4567 8901 2345 6789"),
        ("00123456", "0012 3456"),
        ("1234 5678", "1234 5678"),
        ("1234-5678", "1234 5678"),
        (None, ""),
        ("", ""),
        ("invalid", ""),
        ("1234567", ""),
    ]
    for input_text, expected in cases:
        assert format_bank_account(input_text) == expected, (
            f"format_bank_account({input_text!r}) = {format_bank_account(input_text)!r}, expected {expected!r}"
        )
