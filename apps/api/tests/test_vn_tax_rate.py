"""VN VAT rate calculator (cycle BBB1).

Pinned seams:
  1. CATEGORIES = {standard, reduced, zero, exempt}.
  2. Rates match NN3's VN_VAT_*_RATE constants.
  3. `zero` rate=0.0, applicable=True (line shows 0₫ VAT).
  4. `exempt` rate=None, applicable=False (no VAT line).
  5. Unknown category → rate=None, applicable=False.
  6. compute_vat uses JS-rounding (matches NN3 + AA1).
  7. compute_vat on exempt / negative → ValueError.
"""

from __future__ import annotations

import pytest

from services.estimate_rollup import (
    VN_VAT_DEFAULT_RATE,
    VN_VAT_REDUCED_RATE,
    VN_VAT_ZERO_RATE,
)
from services.vn_tax_rate import (
    CATEGORIES,
    CATEGORY_RATES,
    EXEMPT,
    REDUCED,
    STANDARD,
    ZERO,
    compute_vat,
    is_vat_applicable,
    vat_rate_for,
)

# ---------- Category set ----------


def test_categories_closed_set_of_four():
    assert frozenset({STANDARD, REDUCED, ZERO, EXEMPT}) == CATEGORIES


def test_category_string_values_pinned():
    """Cardinal pin: string values are stable (serialized in DB)."""
    assert STANDARD == "standard"
    assert REDUCED == "reduced"
    assert ZERO == "zero"
    assert EXEMPT == "exempt"


def test_category_rates_match_nn3():
    """Cross-cycle pin: rates equal NN3's VN_VAT_*_RATE constants."""
    assert CATEGORY_RATES[STANDARD] == VN_VAT_DEFAULT_RATE
    assert CATEGORY_RATES[REDUCED] == VN_VAT_REDUCED_RATE
    assert CATEGORY_RATES[ZERO] == VN_VAT_ZERO_RATE
    assert CATEGORY_RATES[EXEMPT] is None


def test_specific_rate_values():
    """Pin: 10% / 8% / 0% / None."""
    assert CATEGORY_RATES[STANDARD] == 0.1
    assert CATEGORY_RATES[REDUCED] == 0.08
    assert CATEGORY_RATES[ZERO] == 0.0
    assert CATEGORY_RATES[EXEMPT] is None


# ---------- vat_rate_for ----------


def test_vat_rate_standard():
    assert vat_rate_for(STANDARD) == 0.1


def test_vat_rate_reduced():
    assert vat_rate_for(REDUCED) == 0.08


def test_vat_rate_zero():
    """Cardinal pin: zero-rated returns 0.0 (NOT None)."""
    assert vat_rate_for(ZERO) == 0.0


def test_vat_rate_exempt_is_none():
    """Cardinal pin: exempt returns None (out-of-scope)."""
    assert vat_rate_for(EXEMPT) is None


def test_vat_rate_unknown_is_none():
    assert vat_rate_for("invalid") is None
    assert vat_rate_for("STANDARD") is None  # case-sensitive
    assert vat_rate_for(None) is None
    assert vat_rate_for("") is None


# ---------- is_vat_applicable ----------


def test_is_vat_applicable_standard():
    assert is_vat_applicable(STANDARD) is True


def test_is_vat_applicable_reduced():
    assert is_vat_applicable(REDUCED) is True


def test_is_vat_applicable_zero():
    """Cardinal pin: zero-rated IS applicable (renders 0₫ line)."""
    assert is_vat_applicable(ZERO) is True


def test_is_vat_applicable_exempt():
    """Cardinal pin: exempt is NOT applicable (no VAT line)."""
    assert is_vat_applicable(EXEMPT) is False


def test_is_vat_applicable_unknown():
    assert is_vat_applicable("invalid") is False
    assert is_vat_applicable(None) is False
    assert is_vat_applicable("") is False


# ---------- zero vs exempt distinction ----------


def test_zero_and_exempt_have_different_applicable():
    """Cardinal pin: a refactor that conflates them MUST fail
    here. Zero-rated and exempt are NOT the same; the invoice
    template renders them differently."""
    assert is_vat_applicable(ZERO) != is_vat_applicable(EXEMPT)


def test_zero_and_exempt_have_different_rates():
    """zero=0.0, exempt=None — distinct."""
    assert vat_rate_for(ZERO) is not None
    assert vat_rate_for(EXEMPT) is None


# ---------- compute_vat ----------


def test_compute_vat_standard_rate():
    """10% on 1,000,000 VND = 100,000 VND."""
    assert compute_vat(1_000_000, STANDARD) == 100_000


def test_compute_vat_reduced_rate():
    """8% on 1,000,000 VND = 80,000 VND."""
    assert compute_vat(1_000_000, REDUCED) == 80_000


def test_compute_vat_zero_rate():
    """0% on any amount = 0 VND."""
    assert compute_vat(1_000_000, ZERO) == 0
    assert compute_vat(0, ZERO) == 0


def test_compute_vat_js_rounding():
    """Cross-cycle pin: JS-compatible half-up rounding.
    Python's round() would yield banker's rounding."""
    # 10% of 12345 = 1234.5 → 1235 (JS round half up), NOT 1234
    # (Python banker's round-to-even).
    assert compute_vat(12345, STANDARD) == 1235


def test_compute_vat_zero_amount():
    """0 VND × any rate = 0."""
    assert compute_vat(0, STANDARD) == 0
    assert compute_vat(0, REDUCED) == 0


def test_compute_vat_exempt_raises():
    """Cardinal pin: exempt has NO VAT amount (not zero)."""
    with pytest.raises(ValueError, match="exempt"):
        compute_vat(1_000_000, EXEMPT)


def test_compute_vat_unknown_raises():
    with pytest.raises(ValueError, match="unknown"):
        compute_vat(1_000_000, "invalid")
    with pytest.raises(ValueError):
        compute_vat(1_000_000, None)


def test_compute_vat_negative_amount_raises():
    """Pin: negative amount is a credit-note path; don't silently
    round."""
    with pytest.raises(ValueError, match="amount"):
        compute_vat(-1, STANDARD)


# ---------- Realistic VN scenarios ----------


def test_realistic_construction_invoice():
    """Realistic: 50M VND scope of work, standard 10% VAT."""
    subtotal = 50_000_000
    vat = compute_vat(subtotal, STANDARD)
    assert vat == 5_000_000
    assert subtotal + vat == 55_000_000


def test_realistic_export_zero_rated():
    """Realistic: export invoice. zero-rated line still appears."""
    subtotal = 100_000_000
    assert is_vat_applicable(ZERO) is True
    assert compute_vat(subtotal, ZERO) == 0


def test_realistic_land_transfer_exempt():
    """Realistic: land use right transfer is exempt — no VAT line."""
    assert is_vat_applicable(EXEMPT) is False
    with pytest.raises(ValueError):
        compute_vat(500_000_000, EXEMPT)
