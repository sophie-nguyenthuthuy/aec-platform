"""Estimate cost rollup (cycle NN3).

Compute `subtotal = sum(qty * unit_price)` over a list of
LL1 LineItems with optional VAT. Today the estimate detail
page's footer total, the audit row's amount-impact detector,
and the email digest's cost summary each compute inline with
subtly different rounding behaviour. This module is the single
source of truth.

  compute_rollup(line_items, vat_rate)  — CostRollup
  CostRollup                            — frozen: (subtotal, vat_amount, total)
  VN_VAT_DEFAULT_RATE                   — 0.1 (10%)
  VN_VAT_REDUCED_RATE                   — 0.08 (stimulus rate)
  VN_VAT_ZERO_RATE                      — 0.0

Composes with:
  * LL1 (`estimate_diff.LineItem`) — consumes the dataclass directly.
  * AA1 (`format_vnd._js_round` pattern) — JS-compatible half-up
    rounding so per-line rounding is deterministic and matches
    the AA1 display formatter.

Pinned invariants:
  * Per-line rounding to integer VND (no fractional cumulation).
  * VAT computed ONCE on subtotal (NOT per-line).
  * vat_rate=0 → vat_amount=0, subtotal == total.
  * vat_rate out of [0, 1] raises ValueError (config bug surface).
  * Empty list → CostRollup(0, 0, 0).
  * JS-compatible half-up rounding (matches AA1).

Pure stdlib + LL1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from services.estimate_diff import LineItem

# Standard VN VAT rate. 10% on most goods/services.
VN_VAT_DEFAULT_RATE = 0.1


# Reduced rate per government stimulus decree (2024-2026).
# Pin so a refactor that drops it surfaces in review.
VN_VAT_REDUCED_RATE = 0.08


# Zero rate (export goods, certain financial services).
VN_VAT_ZERO_RATE = 0.0


@dataclass(frozen=True)
class CostRollup:
    """Cost rollup result. All values are integer VND."""

    subtotal: int
    vat_amount: int
    total: int


def _js_round(x: float) -> int:
    """JS Math.round-compatible half-up rounding.

    Mirrors AA1's internal `_js_round` so per-line rounding here
    matches the format_vnd display formatter. A refactor that
    diverges would silently produce footer totals that differ
    from the line-by-line VND display sum by 1 unit at boundary
    cases.
    """
    return int(math.floor(x + 0.5))


def compute_rollup(
    line_items: list[LineItem],
    vat_rate: float = VN_VAT_DEFAULT_RATE,
) -> CostRollup:
    """Compute cost rollup from line items + VAT rate.

    Algorithm:
      1. For each line, compute `qty * unit_price` and round to
         integer VND (per-line rounding).
      2. Sum line totals → subtotal (integer).
      3. Apply VAT once to subtotal (NOT per-line) and round
         → vat_amount (integer).
      4. total = subtotal + vat_amount.

    Why per-line + once-on-subtotal: matches VN tax invoice
    convention. Per-line for line-display alignment; once-on-
    subtotal so `subtotal + vat = total` arithmetically without
    a 1-VND drift from compounding rounding errors.
    """
    if not (0 <= vat_rate <= 1):
        raise ValueError(f"vat_rate must be in [0, 1], got {vat_rate!r}")

    subtotal = 0
    for item in line_items:
        line_total = _js_round(item.quantity * item.unit_price)
        subtotal += line_total

    vat_amount = _js_round(subtotal * vat_rate)
    total = subtotal + vat_amount

    return CostRollup(
        subtotal=subtotal,
        vat_amount=vat_amount,
        total=total,
    )
