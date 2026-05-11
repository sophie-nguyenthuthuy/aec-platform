"""VN VAT rate calculator (cycle BBB1).

Closed map of VN VAT categories → applicable rate. Today the
estimate detail page's VAT picker, the invoice template's
rate-stamp column, and the audit row's amount-impact detector
each duplicate the category list inline (one omits `exempt`,
another conflates `zero` with `exempt`). This module is the
single source of truth.

  CATEGORIES                     — closed frozenset (4)
  CATEGORY_RATES                 — closed category → rate
  STANDARD, REDUCED, ZERO, EXEMPT — string constants
  vat_rate_for(category)         — float | None (None = exempt)
  is_vat_applicable(category)    — bool (False for exempt only)
  compute_vat(amount, category)  — integer VND (JS-rounded)

Composes with:
  * NN3 (`estimate_rollup.VN_VAT_*_RATE`) — re-uses the same
    canonical rate values (10% / 8% / 0%). A refactor that
    diverges NN3 from this module would break VAT-amount
    audit-row equality across the estimate detail page and the
    invoice template.
  * LL3 (`currency_codes.is_zero_decimal_currency`) — VND is
    zero-decimal; rounding here mirrors that assumption.
  * AA1 (`format_vnd._js_round` pattern) — JS-compatible
    half-up rounding so VAT amounts match the AA1 display.

Categories (per Decree 123/2020/NĐ-CP and 2024-2026 stimulus):
  * `standard` — 10% — most goods + services (default).
  * `reduced` — 8% — government stimulus rate (specific HS codes).
  * `zero` — 0% — export goods, international transport, some
    financial services. VAT IS applicable (line shows `0 ₫` VAT)
    but the rate is zero.
  * `exempt` — None — out of scope of VAT entirely (e.g. land
    use right transfers, agricultural production). Line is NOT
    a VAT line; the invoice template hides the VAT column.

Cardinal pin: `zero` (rate=0) and `exempt` (rate=None) are
DIFFERENT. A `zero`-rated line shows VAT column `0 ₫`; an
`exempt` line has no VAT column. A refactor that conflates them
would mis-render every export invoice's VAT compliance summary.

Pure stdlib + NN3.
"""

from __future__ import annotations

import math

from services.estimate_rollup import (
    VN_VAT_DEFAULT_RATE,
    VN_VAT_REDUCED_RATE,
    VN_VAT_ZERO_RATE,
)

# ---------- Category constants ----------

STANDARD = "standard"
REDUCED = "reduced"
ZERO = "zero"
EXEMPT = "exempt"


# Closed set of valid categories. Adding a new VN VAT category
# requires touching the tax authority's published list — pin so
# a sneaky add doesn't slip past review.
CATEGORIES: frozenset[str] = frozenset({STANDARD, REDUCED, ZERO, EXEMPT})


# Category → applicable rate (float in [0, 1]) or None for exempt.
# Pin so a refactor that drops `exempt` to 0.0 surfaces here: a
# `0.0`-rated line and an `exempt` line have DIFFERENT invoice
# rendering semantics (see module docstring).
CATEGORY_RATES: dict[str, float | None] = {
    STANDARD: VN_VAT_DEFAULT_RATE,  # 0.10
    REDUCED: VN_VAT_REDUCED_RATE,  # 0.08
    ZERO: VN_VAT_ZERO_RATE,  # 0.00
    EXEMPT: None,  # out-of-scope
}


def _js_round(x: float) -> int:
    """JS Math.round-compatible half-up rounding.

    Mirrors NN3's `_js_round` so VAT amounts here match the
    estimate rollup's vat_amount and AA1's format_vnd display.
    """
    return int(math.floor(x + 0.5))


def vat_rate_for(category: str | None) -> float | None:
    """Return the VAT rate for `category`, or None for exempt /
    unknown.

    Cardinal pin: returns None BOTH for `exempt` (out-of-scope)
    AND for unknown categories. Callers MUST check
    `is_vat_applicable(category)` first if they need to
    distinguish "exempt by design" from "unknown category typo".
    """
    if category not in CATEGORIES:
        return None
    return CATEGORY_RATES[category]


def is_vat_applicable(category: str | None) -> bool:
    """True iff `category` is a known VAT-applicable category.

    Returns True for `standard`, `reduced`, `zero` (zero-rated
    is still APPLICABLE — line shows `0 ₫` VAT).
    Returns False for `exempt` AND for unknown categories.
    """
    if category not in CATEGORIES:
        return False
    return CATEGORY_RATES[category] is not None


def compute_vat(amount: int, category: str | None) -> int:
    """Compute VAT in integer VND for `amount` at `category`'s rate.

    `amount` is the pre-VAT line/subtotal in integer VND.
    Rounding uses JS-compatible half-up (matches NN3 + AA1).

    Raises:
      * ValueError if `category` is unknown or `exempt` (callers
        must check `is_vat_applicable` first — exempt lines have
        no VAT amount, not a zero VAT amount).
      * ValueError if `amount` is negative (VAT on a negative
        amount is a credit-note line which uses a different code
        path; pin so we don't silently round a negative).
    """
    if amount < 0:
        raise ValueError(f"amount must be >= 0, got {amount}")
    if category not in CATEGORIES:
        raise ValueError(f"unknown VAT category: {category!r}")
    rate = CATEGORY_RATES[category]
    if rate is None:
        raise ValueError(f"category {category!r} is exempt (no VAT amount); check is_vat_applicable() first")
    return _js_round(amount * rate)
