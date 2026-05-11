"""ISO 4217 currency code lookup (cycle LL3).

Pinned seams:
  1. KNOWN_CURRENCIES has 16 entries (closed VN-relevant set).
  2. ZERO_DECIMAL_CURRENCIES = {VND, JPY, KRW, IDR}.
  3. VND is 0 decimals (NOT 2 — historical hào/xu unused).
  4. Lookups case-insensitive.
  5. Unknown codes return None (NOT default 2 decimals).
"""

from __future__ import annotations

from services.currency_codes import (
    KNOWN_CURRENCIES,
    ZERO_DECIMAL_CURRENCIES,
    currency_decimal_places,
    currency_display_name,
    is_zero_decimal_currency,
)

# ---------- KNOWN_CURRENCIES ----------


def test_known_currencies_count():
    """16 entries chosen for VN AEC procurement relevance."""
    assert len(KNOWN_CURRENCIES) == 16


def test_known_currencies_includes_vnd():
    assert "VND" in KNOWN_CURRENCIES


def test_known_currencies_includes_top_trading_partners():
    """Top VN trading partners: USD, CNY, JPY, KRW."""
    for code in ["USD", "CNY", "JPY", "KRW"]:
        assert code in KNOWN_CURRENCIES, f"{code} should be in KNOWN_CURRENCIES"


def test_known_currencies_includes_asean():
    """ASEAN economic-zone currencies."""
    for code in ["SGD", "THB", "MYR", "IDR", "PHP"]:
        assert code in KNOWN_CURRENCIES, f"{code} should be in KNOWN_CURRENCIES"


def test_known_currencies_uppercase():
    for code in KNOWN_CURRENCIES:
        assert code == code.upper()


def test_known_currencies_is_frozen():
    assert isinstance(KNOWN_CURRENCIES, frozenset)


# ---------- ZERO_DECIMAL_CURRENCIES ----------


def test_zero_decimal_canonical_set():
    """Pin: VND, JPY, KRW, IDR. A refactor that adds USD here
    would silently break every formatter that assumes 0 decimals
    means "VND-style"."""
    assert frozenset({"VND", "JPY", "KRW", "IDR"}) == ZERO_DECIMAL_CURRENCIES


def test_zero_decimal_is_subset_of_known():
    assert ZERO_DECIMAL_CURRENCIES.issubset(KNOWN_CURRENCIES)


def test_zero_decimal_is_frozen():
    assert isinstance(ZERO_DECIMAL_CURRENCIES, frozenset)


# ---------- VND zero-decimal ----------


def test_vnd_is_zero_decimal_cardinal_pin():
    """Cardinal pin: VND has 0 decimals. The historical hào (1/10)
    and xu (1/100) subdivisions are unused in modern pricing.
    A refactor that bumps VND to 2 decimals would silently
    introduce phantom precision into every Vietnamese invoice."""
    assert currency_decimal_places("VND") == 0
    assert is_zero_decimal_currency("VND") is True


def test_jpy_is_zero_decimal():
    """JPY also 0 decimals per ISO 4217."""
    assert currency_decimal_places("JPY") == 0


def test_krw_is_zero_decimal():
    assert currency_decimal_places("KRW") == 0


def test_idr_is_zero_decimal():
    assert currency_decimal_places("IDR") == 0


# ---------- 2-decimal currencies ----------


def test_usd_is_two_decimal():
    assert currency_decimal_places("USD") == 2
    assert is_zero_decimal_currency("USD") is False


def test_eur_is_two_decimal():
    assert currency_decimal_places("EUR") == 2


def test_cny_is_two_decimal():
    """CNY has fen subdivision (1/100). 2 decimals."""
    assert currency_decimal_places("CNY") == 2


def test_all_non_zero_decimal_currencies_are_two():
    """Every known currency that's NOT in ZERO_DECIMAL has 2."""
    for code in KNOWN_CURRENCIES - ZERO_DECIMAL_CURRENCIES:
        assert currency_decimal_places(code) == 2, f"{code} should have 2 decimal places"


# ---------- Case-insensitive ----------


def test_lookups_case_insensitive():
    assert currency_display_name("vnd") == "Vietnamese Đồng"
    assert currency_display_name("VnD") == "Vietnamese Đồng"
    assert currency_decimal_places("usd") == 2
    assert is_zero_decimal_currency("vnd") is True


# ---------- Unknown / None ----------


def test_unknown_code_display_name_returns_none():
    assert currency_display_name("XYZ") is None
    assert currency_display_name("BTC") is None


def test_unknown_code_decimal_places_returns_none():
    """Cardinal pin: unknown returns None, NOT default 2. A
    refactor that defaults to 2 for unknown would silently
    format a typo'd code with wrong precision."""
    assert currency_decimal_places("XYZ") is None
    assert currency_decimal_places("BTC") is None


def test_none_and_empty_inputs():
    assert currency_display_name(None) is None
    assert currency_display_name("") is None
    assert currency_decimal_places(None) is None
    assert currency_decimal_places("") is None
    assert is_zero_decimal_currency(None) is False
    assert is_zero_decimal_currency("") is False


def test_is_zero_decimal_unknown_returns_false():
    """Pin: unknown → False (not None). is_zero_decimal returns
    bool by contract, so unknown is treated as 'not zero-decimal'."""
    assert is_zero_decimal_currency("XYZ") is False


# ---------- Display names ----------


def test_vnd_display_name_uses_dong_sign():
    """Pin: display name uses 'Vietnamese Đồng' with the đ-stroke
    character (NOT 'Dong' or 'Vietnamese Dong')."""
    assert currency_display_name("VND") == "Vietnamese Đồng"


def test_display_name_for_each_known_currency():
    """Every known currency has a display name (non-None)."""
    for code in KNOWN_CURRENCIES:
        name = currency_display_name(code)
        assert name is not None, f"{code} missing display name"
        assert len(name) > 0


# ---------- Cross-cycle composition (AA1 VND formatter) ----------


def test_vnd_zero_decimal_aligns_with_aa1_format_vnd():
    """AA1's `format_vnd` rounds to integer (0 decimals). Pin
    here that the registry agrees — a refactor that changes
    VND to 2 decimals would create a divergence between AA1
    and consumers using this registry."""
    assert is_zero_decimal_currency("VND") is True
    assert currency_decimal_places("VND") == 0
