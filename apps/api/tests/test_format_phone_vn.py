"""Vietnamese phone number formatter (cycle BB2, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/format-phone-vn.test.ts`):
  1. VN_MOBILE_PREFIXES = {3, 5, 7, 8, 9} per MIC 2018 reorg.
  2. Three formats: national (default), international, e164.
  3. Canonical E.164 is `+84XXXXXXXXX` (no separators).
  4. parse_phone_vn accepts five input forms.
  5. parse_phone_vn rejects non-mobile prefixes (1, 2, 4, 6).
  6. Invalid input → '' from format_phone_vn, None from parse_phone_vn.
"""

from __future__ import annotations

from services.format_phone_vn import (
    VN_MOBILE_PREFIXES,
    format_phone_vn,
    is_valid_vn_mobile,
    parse_phone_vn,
)


# ---------- Constants ----------


def test_mobile_prefixes_match_mic_2018_allowlist():
    """Pin to {3, 5, 7, 8, 9} per the MIC 2018 mobile reorg."""
    assert VN_MOBILE_PREFIXES == frozenset({"3", "5", "7", "8", "9"})


def test_mobile_prefixes_excludes_pre_2018_one():
    """'1' was a valid VN mobile prefix pre-2018 (e.g. 0123…),
    retired in the reorg. Pin so a refactor that re-adds it
    surfaces here — accepting old-format numbers from a
    migration import would silently store invalid data."""
    assert "1" not in VN_MOBILE_PREFIXES
    assert "2" not in VN_MOBILE_PREFIXES
    assert "4" not in VN_MOBILE_PREFIXES
    assert "6" not in VN_MOBILE_PREFIXES


def test_mobile_prefixes_is_frozen():
    assert isinstance(VN_MOBILE_PREFIXES, frozenset)


# ---------- parse_phone_vn ----------


def test_parse_national_to_e164():
    assert parse_phone_vn("0901234567") == "+84901234567"


def test_parse_e164_round_trip():
    assert parse_phone_vn("+84901234567") == "+84901234567"


def test_parse_country_coded_without_plus():
    assert parse_phone_vn("84901234567") == "+84901234567"


def test_parse_strips_grouping_chars():
    assert parse_phone_vn("+84 90 123 4567") == "+84901234567"
    assert parse_phone_vn("0901 234 567") == "+84901234567"
    assert parse_phone_vn("0901-234-567") == "+84901234567"
    assert parse_phone_vn("0901.234.567") == "+84901234567"
    assert parse_phone_vn("(090) 1234567") == "+84901234567"


def test_parse_accepts_all_valid_mobile_prefixes():
    assert parse_phone_vn("0301234567") == "+84301234567"
    assert parse_phone_vn("0501234567") == "+84501234567"
    assert parse_phone_vn("0701234567") == "+84701234567"
    assert parse_phone_vn("0801234567") == "+84801234567"
    assert parse_phone_vn("0901234567") == "+84901234567"


def test_parse_rejects_non_mobile_prefixes():
    """Pin: '1', '2', '4', '6' are NOT mobile prefixes."""
    assert parse_phone_vn("0101234567") is None
    assert parse_phone_vn("0201234567") is None
    assert parse_phone_vn("0401234567") is None
    assert parse_phone_vn("0601234567") is None


def test_parse_rejects_too_short():
    assert parse_phone_vn("090123456") is None
    assert parse_phone_vn("090") is None


def test_parse_rejects_too_long():
    assert parse_phone_vn("09012345678") is None
    assert parse_phone_vn("+849012345678") is None


def test_parse_rejects_non_digit_garbage():
    assert parse_phone_vn("abc") is None
    assert parse_phone_vn("090abc4567") is None


def test_parse_returns_none_for_none_and_empty():
    assert parse_phone_vn(None) is None
    assert parse_phone_vn("") is None
    assert parse_phone_vn("   ") is None  # whitespace-only strips to ""


# ---------- is_valid_vn_mobile ----------


def test_is_valid_vn_mobile_true_for_valid():
    assert is_valid_vn_mobile("0901234567") is True
    assert is_valid_vn_mobile("+84901234567") is True


def test_is_valid_vn_mobile_false_for_invalid():
    assert is_valid_vn_mobile("0101234567") is False
    assert is_valid_vn_mobile(None) is False
    assert is_valid_vn_mobile("abc") is False


# ---------- format_phone_vn ----------


def test_format_default_is_national():
    """Most common form in VN UIs — leading 0 is universally
    recognised. Pin so a refactor that flips the default to
    international doesn't silently change every member-list page."""
    assert format_phone_vn("+84901234567") == "0901 234 567"


def test_format_national_4_3_3():
    assert format_phone_vn("+84901234567", "national") == "0901 234 567"
    assert format_phone_vn("0901234567", "national") == "0901 234 567"


def test_format_international_2_3_4_after_country_code():
    assert format_phone_vn("+84901234567", "international") == "+84 90 123 4567"
    assert format_phone_vn("0901234567", "international") == "+84 90 123 4567"


def test_format_e164_no_separators():
    assert format_phone_vn("+84901234567", "e164") == "+84901234567"
    assert format_phone_vn("0901 234 567", "e164") == "+84901234567"


def test_format_invalid_returns_empty():
    """Chained-render-friendly: `format_phone_vn(member.phone)`
    works without a None check."""
    assert format_phone_vn(None) == ""
    assert format_phone_vn("") == ""
    assert format_phone_vn("0101234567") == ""  # invalid prefix
    assert format_phone_vn("abc") == ""


def test_format_normalises_grouping_on_round_trip():
    """User types weird grouping; we render canonical grouping.
    Pin so a refactor that preserves user-typed whitespace breaks
    here."""
    assert format_phone_vn("0 9 0 1 2 3 4 5 6 7", "national") == "0901 234 567"


# ---------- Cross-language consistency ----------


def test_round_trip_through_parse_and_format_e164():
    """A valid input → parse → format(e164) must preserve the
    canonical form. Pin so a refactor that drops the +84 prefix
    surfaces here."""
    canonical = "+84901234567"
    parsed = parse_phone_vn("0901 234 567")
    formatted = format_phone_vn(parsed, "e164")
    assert formatted == canonical
