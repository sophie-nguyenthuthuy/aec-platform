"""Vietnamese citizen ID (CCCD) validator (cycle FF1).

Pinned seams:
  1. CCCD_LENGTH = 12 (NOT 9 — pre-2016 CMND; NOT 10 — MST).
  2. Province code in [1, 99].
  3. Gender/century code in {0, 1, 2, 3} (4-9 reserved).
  4. Birth year resolves via gender code: 0/1 → 1900s, 2/3 → 2000s.
  5. Whitespace stripped on parse.
  6. None / empty / non-numeric → None.
"""

from __future__ import annotations

from services.vn_citizen_id import (
    CCCD_LENGTH,
    CCCD_PROVINCE_MAX,
    CCCD_PROVINCE_MIN,
    GENDER_CENTURY_CODES,
    cccd_birth_year,
    cccd_province_code,
    is_valid_cccd,
    parse_cccd,
)

# ---------- Constants ----------


def test_cccd_length_is_twelve():
    """Pin: 12 digits exactly. NOT 9 (pre-2016 CMND) and NOT 10
    (MST corporate tax ID). A refactor that accepts the legacy
    9-digit CMND would silently allow a different identifier
    type to pass validation."""
    assert CCCD_LENGTH == 12


def test_province_band():
    """Province codes 001-099 per VN administrative divisions.
    Pin the band edges."""
    assert CCCD_PROVINCE_MIN == 1
    assert CCCD_PROVINCE_MAX == 99


def test_gender_century_codes_canonical_set():
    """Pin: only {0, 1, 2, 3} are valid gender/century codes
    today. 4-9 are reserved for future centuries — accepting
    them now would be premature."""
    assert frozenset({"0", "1", "2", "3"}) == GENDER_CENTURY_CODES


def test_gender_century_codes_is_frozen():
    assert isinstance(GENDER_CENTURY_CODES, frozenset)


# ---------- parse_cccd ----------


def test_parse_canonical_form():
    assert parse_cccd("079203456789") == "079203456789"


def test_parse_strips_whitespace():
    """Users paste from PDFs with embedded spaces — strip."""
    assert parse_cccd("079 203 456 789") == "079203456789"
    assert parse_cccd("  079203456789  ") == "079203456789"


def test_parse_returns_none_for_invalid():
    assert parse_cccd(None) is None
    assert parse_cccd("") is None
    assert parse_cccd("invalid") is None


# ---------- Length rejection ----------


def test_rejects_pre_2016_cmnd_9_digits():
    """Cardinal pin: 9-digit pre-2016 CMND is REJECTED. A migration
    import that accepts both formats would silently allow legacy
    IDs to slip past length validation."""
    assert is_valid_cccd("123456789") is False


def test_rejects_mst_10_digits():
    """Cardinal pin: 10-digit MST (corporate tax ID) is REJECTED.
    Different identifier type — pin so a refactor that conflates
    parsers doesn't slip past."""
    assert is_valid_cccd("0123456787") is False


def test_rejects_too_short():
    assert is_valid_cccd("12345") is False
    assert is_valid_cccd("01234567890") is False  # 11 digits


def test_rejects_too_long():
    assert is_valid_cccd("0123456789012") is False  # 13 digits


# ---------- Province code rejection ----------


def test_rejects_province_zero():
    """Province 000 is reserved / unassigned."""
    assert is_valid_cccd("000203456789") is False


def test_rejects_province_above_99():
    """Pin: codes ≥100 are not in the published province table.
    A refactor that bumps the ceiling without consulting the
    administrative divisions table would silently accept invalid
    province prefixes."""
    assert is_valid_cccd("100203456789") is False
    assert is_valid_cccd("999203456789") is False


def test_accepts_province_at_boundaries():
    assert is_valid_cccd("001203456789") is True  # province 001
    assert is_valid_cccd("099203456789") is True  # province 099


# ---------- Gender/century code rejection ----------


def test_rejects_gender_code_4_through_9():
    """Pin: 4-9 are reserved for future centuries (22nd onwards).
    Accepting them now would be premature and might conflict
    with a future official assignment."""
    for digit in ["4", "5", "6", "7", "8", "9"]:
        cccd = f"079{digit}03456789"
        assert is_valid_cccd(cccd) is False, f"gender code {digit} should reject"


# ---------- Non-numeric rejection ----------


def test_rejects_non_numeric_chars():
    assert is_valid_cccd("079ABC456789") is False
    assert is_valid_cccd("079203456-89") is False
    assert is_valid_cccd("079203.456789") is False


# ---------- cccd_province_code ----------


def test_province_code_extraction():
    assert cccd_province_code("079203456789") == "079"
    assert cccd_province_code("001203456789") == "001"
    assert cccd_province_code("099203456789") == "099"


def test_province_code_none_for_invalid():
    assert cccd_province_code(None) is None
    assert cccd_province_code("invalid") is None
    assert cccd_province_code("100203456789") is None  # bad province


# ---------- cccd_birth_year ----------


def test_birth_year_20th_century_male():
    """Gender code 0 = male/20th c. YOB 92 → 1992."""
    assert cccd_birth_year("079092345678") == 1992


def test_birth_year_20th_century_female():
    """Gender code 1 = female/20th c. YOB 92 → 1992."""
    assert cccd_birth_year("079192345678") == 1992


def test_birth_year_21st_century_male():
    """Gender code 2 = male/21st c. YOB 03 → 2003."""
    assert cccd_birth_year("079203456789") == 2003


def test_birth_year_21st_century_female():
    """Gender code 3 = female/21st c. YOB 03 → 2003."""
    assert cccd_birth_year("079303456789") == 2003


def test_birth_year_yob_zero():
    """YOB 00 — should resolve as 1900 (gender 0/1) or 2000 (2/3)."""
    assert cccd_birth_year("079000123456") == 1900
    assert cccd_birth_year("079200123456") == 2000


def test_birth_year_yob_99():
    """YOB 99 — 1999 (20th c) or 2099 (21st c)."""
    assert cccd_birth_year("079099123456") == 1999
    assert cccd_birth_year("079299123456") == 2099


def test_birth_year_none_for_invalid():
    assert cccd_birth_year(None) is None
    assert cccd_birth_year("") is None
    assert cccd_birth_year("invalid") is None
    assert cccd_birth_year("079403456789") is None  # bad gender code


# ---------- is_valid_cccd ----------


def test_is_valid_cccd_for_canonical():
    assert is_valid_cccd("079203456789") is True


def test_is_valid_cccd_false_for_none_and_empty():
    assert is_valid_cccd(None) is False
    assert is_valid_cccd("") is False
    assert is_valid_cccd("   ") is False  # all-whitespace strips to ""
