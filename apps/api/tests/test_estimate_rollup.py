"""Estimate cost rollup (cycle NN3).

Pinned seams:
  1. VN_VAT_DEFAULT_RATE = 0.1 (10%).
  2. VN_VAT_REDUCED_RATE = 0.08 (8% stimulus).
  3. VN_VAT_ZERO_RATE = 0.0.
  4. Per-line rounding to integer VND.
  5. VAT computed ONCE on subtotal.
  6. vat_rate=0 → subtotal == total.
  7. vat_rate out of [0, 1] raises ValueError.
  8. Empty list → CostRollup(0, 0, 0).
  9. JS-compatible half-up rounding (AA1 composition).
"""

from __future__ import annotations

import pytest

from services.estimate_diff import LineItem
from services.estimate_rollup import (
    VN_VAT_DEFAULT_RATE,
    VN_VAT_REDUCED_RATE,
    VN_VAT_ZERO_RATE,
    CostRollup,
    compute_rollup,
)
from services.format_vnd import format_vnd


def _item(
    sku: str = "X",
    quantity: float = 1.0,
    unit_price: float = 100.0,
) -> LineItem:
    return LineItem(
        sku=sku,
        description="",
        quantity=quantity,
        unit_price=unit_price,
        note="",
    )


# ---------- Constants ----------


def test_default_vat_rate_is_ten_percent():
    """10% is the VN standard VAT rate."""
    assert VN_VAT_DEFAULT_RATE == 0.1


def test_reduced_vat_rate_is_eight_percent():
    """8% per government stimulus decree."""
    assert VN_VAT_REDUCED_RATE == 0.08


def test_zero_vat_rate():
    assert VN_VAT_ZERO_RATE == 0.0


# ---------- Empty list ----------


def test_empty_list_returns_zero_rollup():
    result = compute_rollup([], vat_rate=0.1)
    assert result == CostRollup(subtotal=0, vat_amount=0, total=0)


def test_empty_list_with_zero_vat():
    result = compute_rollup([], vat_rate=0.0)
    assert result == CostRollup(subtotal=0, vat_amount=0, total=0)


# ---------- Single line ----------


def test_single_line_default_vat():
    """qty=10, price=100 → line_total=1000; vat=100; total=1100."""
    items = [_item(quantity=10, unit_price=100)]
    result = compute_rollup(items, vat_rate=VN_VAT_DEFAULT_RATE)
    assert result.subtotal == 1000
    assert result.vat_amount == 100
    assert result.total == 1100


def test_single_line_zero_vat():
    """vat_rate=0 → subtotal == total, vat_amount = 0."""
    items = [_item(quantity=10, unit_price=100)]
    result = compute_rollup(items, vat_rate=0.0)
    assert result.subtotal == 1000
    assert result.vat_amount == 0
    assert result.total == 1000


def test_single_line_reduced_vat():
    """qty=10, price=1000, vat=8% → subtotal=10000; vat=800."""
    items = [_item(quantity=10, unit_price=1000)]
    result = compute_rollup(items, vat_rate=VN_VAT_REDUCED_RATE)
    assert result.subtotal == 10000
    assert result.vat_amount == 800
    assert result.total == 10800


# ---------- Multiple lines ----------


def test_multiple_lines_summed():
    items = [
        _item(quantity=10, unit_price=100),  # 1000
        _item(quantity=5, unit_price=200),  # 1000
        _item(quantity=2, unit_price=500),  # 1000
    ]
    result = compute_rollup(items, vat_rate=0.1)
    assert result.subtotal == 3000
    assert result.vat_amount == 300
    assert result.total == 3300


# ---------- Rounding ----------


def test_per_line_rounding_half_up():
    """Cardinal pin: each line rounds via JS-compatible half-up
    BEFORE summing. qty=1, price=1234.5 → line_total=1235."""
    items = [_item(quantity=1, unit_price=1234.5)]
    result = compute_rollup(items, vat_rate=0)
    assert result.subtotal == 1235


def test_rounding_matches_aa1_format_vnd():
    """Cardinal cross-cycle pin: NN3's per-line rounding uses
    the same JS-compatible half-up algorithm as AA1's
    `format_vnd`. A divergence would produce footer totals
    that disagree with line-by-line VND display sums by 1 unit
    at boundary cases."""
    # AA1: format_vnd(1234.5) == "1.235 ₫" (rounds 1234.5 to 1235)
    assert format_vnd(1234.5) == "1.235 ₫"

    # NN3: same input rounds the same way.
    items = [_item(quantity=1, unit_price=1234.5)]
    result = compute_rollup(items, vat_rate=0)
    assert result.subtotal == 1235


def test_rounding_round_down_at_below_half():
    items = [_item(quantity=1, unit_price=1234.4)]
    result = compute_rollup(items, vat_rate=0)
    assert result.subtotal == 1234


def test_rounding_at_exact_half_rounds_up():
    """0.5 → 1 (JS half-up, NOT banker's even)."""
    items = [_item(quantity=1, unit_price=0.5)]
    result = compute_rollup(items, vat_rate=0)
    assert result.subtotal == 1


def test_vat_rounded_once_on_subtotal_not_per_line():
    """Cardinal pin: VAT computed on summed subtotal. Per-line
    VAT would compound rounding error.

    With per-line VAT: 3 × round(0.5) = 3 × 1 = 3.
    With sum-then-VAT: round(3 × 1 × 0.1) = round(0.3) = 0.
    Pin: subtotal=3, VAT applied once → vat_amount=0."""
    items = [
        _item(quantity=1, unit_price=1),
        _item(quantity=1, unit_price=1),
        _item(quantity=1, unit_price=1),
    ]
    # subtotal = 3, vat = round(3 * 0.1) = round(0.3) = 0
    result = compute_rollup(items, vat_rate=0.1)
    assert result.subtotal == 3
    assert result.vat_amount == 0
    assert result.total == 3


# ---------- VAT rate validation ----------


def test_vat_rate_negative_raises():
    """Pin: negative VAT rate is a config bug — raise rather
    than silently produce a negative VAT amount."""
    with pytest.raises(ValueError):
        compute_rollup([_item()], vat_rate=-0.1)


def test_vat_rate_above_one_raises():
    """100%+ VAT is a config bug. Raise so it surfaces during
    setup rather than silently inflating invoices."""
    with pytest.raises(ValueError):
        compute_rollup([_item()], vat_rate=1.5)


def test_vat_rate_at_zero_boundary_allowed():
    result = compute_rollup([_item(quantity=10, unit_price=100)], vat_rate=0.0)
    assert result.vat_amount == 0


def test_vat_rate_at_one_boundary_allowed():
    """100% VAT is unusual but technically valid (some special
    schemes). Pin so the boundary value [0, 1] inclusive is
    honoured."""
    result = compute_rollup([_item(quantity=1, unit_price=100)], vat_rate=1.0)
    assert result.subtotal == 100
    assert result.vat_amount == 100
    assert result.total == 200


# ---------- Composition with LL1 ----------


def test_composes_with_ll1_line_item():
    """Cardinal cross-cycle pin: takes LL1 LineItem dataclasses
    directly. A refactor that changes LineItem field shape would
    surface here via type / attribute errors."""
    items = [
        LineItem(
            sku="SKU-1",
            description="Concrete",
            quantity=100,
            unit_price=50000,
            note="",
        ),
        LineItem(
            sku="SKU-2",
            description="Rebar",
            quantity=50,
            unit_price=30000,
            note="",
        ),
    ]
    result = compute_rollup(items, vat_rate=0.1)
    # 100*50000 + 50*30000 = 5000000 + 1500000 = 6500000
    # vat = 650000; total = 7150000
    assert result.subtotal == 6500000
    assert result.vat_amount == 650000
    assert result.total == 7150000


# ---------- Frozen ----------


def test_cost_rollup_is_frozen():
    r = CostRollup(subtotal=100, vat_amount=10, total=110)
    try:
        r.total = 200  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("CostRollup should be frozen")
