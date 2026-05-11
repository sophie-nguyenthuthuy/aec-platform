"""ISO 4217 currency code lookup (cycle LL3).

Closed registry of currencies relevant to VN AEC procurement.
Today the multi-currency invoice formatter, the audit row's
amount-display tone, and the dashboard's currency dropdown
each duplicate the code list inline. This module is the single
source of truth.

  KNOWN_CURRENCIES                — closed frozenset
  ZERO_DECIMAL_CURRENCIES         — currencies with 0 decimals
  currency_display_name(code)     — display name or None
  currency_decimal_places(code)   — 0 / 2 / None
  is_zero_decimal_currency(code)  — bool

Composes with AA1's `format_vnd` (which assumes 0 decimals — pin
so a refactor that adds USD support to that helper has a check
against this registry's `is_zero_decimal_currency`).

Pinned invariants:
  * VND has 0 decimals (NOT 2 — the historical hào/xu are unused).
  * JPY/KRW/IDR also 0 decimals (matches ISO 4217 minor unit).
  * Lookups case-insensitive.
  * Unknown codes return None for both display name and decimals
    (pin so callers handle unknown explicitly rather than
    silently defaulting to 2 decimals).

Pure stdlib.
"""

from __future__ import annotations

# Closed registry of currencies relevant to VN AEC procurement.
# Codes per ISO 4217. Ordered by VN-import frequency: VND first,
# then USD/EUR/JPY/CNY (top trading partners), then ASEAN, then
# other major.
KNOWN_CURRENCIES: frozenset[str] = frozenset(
    {
        "VND",  # Vietnamese Đồng (home currency)
        "USD",  # US Dollar
        "EUR",  # Euro
        "JPY",  # Japanese Yen
        "CNY",  # Chinese Yuan
        "KRW",  # South Korean Won
        "SGD",  # Singapore Dollar
        "THB",  # Thai Baht
        "MYR",  # Malaysian Ringgit
        "IDR",  # Indonesian Rupiah
        "PHP",  # Philippine Peso
        "INR",  # Indian Rupee
        "AUD",  # Australian Dollar
        "GBP",  # British Pound Sterling
        "CAD",  # Canadian Dollar
        "CHF",  # Swiss Franc
    }
)


# Currencies with 0 decimal places per ISO 4217. The historical
# subdivisions (hào/xu for VND, sen for JPY) are unused in modern
# pricing.
ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset(
    {
        "VND",
        "JPY",
        "KRW",
        "IDR",
    }
)


_DISPLAY_NAMES: dict[str, str] = {
    "VND": "Vietnamese Đồng",
    "USD": "US Dollar",
    "EUR": "Euro",
    "JPY": "Japanese Yen",
    "CNY": "Chinese Yuan",
    "KRW": "South Korean Won",
    "SGD": "Singapore Dollar",
    "THB": "Thai Baht",
    "MYR": "Malaysian Ringgit",
    "IDR": "Indonesian Rupiah",
    "PHP": "Philippine Peso",
    "INR": "Indian Rupee",
    "AUD": "Australian Dollar",
    "GBP": "British Pound Sterling",
    "CAD": "Canadian Dollar",
    "CHF": "Swiss Franc",
}


def currency_display_name(code: str | None) -> str | None:
    """Return the display name for a currency code (case-insensitive).

    Returns None for unknown codes, None / empty input.
    """
    if not code:
        return None
    return _DISPLAY_NAMES.get(code.upper())


def currency_decimal_places(code: str | None) -> int | None:
    """Return the number of decimal places for a currency.

      * 0 for VND, JPY, KRW, IDR.
      * 2 for all other known currencies.
      * None for unknown / empty input.

    Pin: unknown returns None (NOT a default of 2). Caller must
    handle unknown explicitly — defends against a typo'd code
    silently formatting with the wrong precision.
    """
    if not code:
        return None
    upper = code.upper()
    if upper not in KNOWN_CURRENCIES:
        return None
    if upper in ZERO_DECIMAL_CURRENCIES:
        return 0
    return 2


def is_zero_decimal_currency(code: str | None) -> bool:
    """True iff the code is a known zero-decimal currency.

    None / empty / unknown → False.
    """
    if not code:
        return False
    return code.upper() in ZERO_DECIMAL_CURRENCIES
