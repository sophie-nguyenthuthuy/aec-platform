"""Estimate version diff helper (cycle LL1, Python half).

Pinned seams:
  1. Keyed by SKU (NOT description).
  2. added/removed/changed sorted by SKU.
  3. unchanged_count (NOT full list) preserved.
  4. changed_fields in canonical declaration order.
  5. Empty before / empty after cases handled.
"""

from __future__ import annotations

from services.estimate_diff import (
    EstimateDiff,
    LineItem,
    LineItemChange,
    diff_estimate,
)


def _item(
    sku: str,
    description: str = "default",
    quantity: float = 1.0,
    unit_price: float = 100.0,
    note: str = "",
) -> LineItem:
    return LineItem(
        sku=sku,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        note=note,
    )


# ---------- Empty / identical ----------


def test_empty_both_returns_empty_diff():
    result = diff_estimate([], [])
    assert result == EstimateDiff(
        added=(),
        removed=(),
        changed=(),
        unchanged_count=0,
    )


def test_identical_versions_yield_only_unchanged():
    items = [_item("SKU-1"), _item("SKU-2")]
    result = diff_estimate(items, items)
    assert result.added == ()
    assert result.removed == ()
    assert result.changed == ()
    assert result.unchanged_count == 2


# ---------- Pure add ----------


def test_empty_before_all_added():
    after = [_item("SKU-1"), _item("SKU-2")]
    result = diff_estimate([], after)
    assert result.added == tuple(after)
    assert result.removed == ()
    assert result.changed == ()
    assert result.unchanged_count == 0


def test_added_sorted_by_sku():
    """Cardinal pin: added list is sorted by SKU regardless of
    input order. Snapshot tests rely on this."""
    after = [_item("SKU-Z"), _item("SKU-A"), _item("SKU-M")]
    result = diff_estimate([], after)
    assert [it.sku for it in result.added] == ["SKU-A", "SKU-M", "SKU-Z"]


# ---------- Pure remove ----------


def test_empty_after_all_removed():
    before = [_item("SKU-1"), _item("SKU-2")]
    result = diff_estimate(before, [])
    assert result.added == ()
    assert result.removed == tuple(sorted(before, key=lambda i: i.sku))
    assert result.changed == ()


def test_removed_sorted_by_sku():
    before = [_item("SKU-Z"), _item("SKU-A"), _item("SKU-M")]
    result = diff_estimate(before, [])
    assert [it.sku for it in result.removed] == ["SKU-A", "SKU-M", "SKU-Z"]


# ---------- Changed ----------


def test_quantity_change():
    before = [_item("SKU-1", quantity=10)]
    after = [_item("SKU-1", quantity=20)]
    result = diff_estimate(before, after)
    assert result.added == ()
    assert result.removed == ()
    assert len(result.changed) == 1
    assert result.changed[0].sku == "SKU-1"
    assert result.changed[0].changed_fields == ("quantity",)


def test_multiple_field_changes():
    before = [_item("SKU-1", quantity=10, unit_price=100)]
    after = [_item("SKU-1", quantity=20, unit_price=150)]
    result = diff_estimate(before, after)
    assert result.changed[0].changed_fields == ("quantity", "unit_price")


def test_changed_fields_in_declaration_order():
    """Cardinal pin: changed_fields tuple matches the
    declaration order (description, quantity, unit_price, note),
    NOT alphabetical. The audit-trail diff display expects this
    column-aligned ordering."""
    before = _item("SKU-1", description="A", quantity=1, unit_price=10, note="x")
    after = _item("SKU-1", description="B", quantity=2, unit_price=20, note="y")
    result = diff_estimate([before], [after])
    assert result.changed[0].changed_fields == (
        "description",
        "quantity",
        "unit_price",
        "note",
    )


def test_changed_includes_before_and_after():
    """Pin: change entries carry both versions for diff rendering."""
    before = _item("SKU-1", quantity=10)
    after = _item("SKU-1", quantity=20)
    result = diff_estimate([before], [after])
    assert result.changed[0].before == before
    assert result.changed[0].after == after


def test_description_only_change_appears_as_changed():
    """Pin: description CAN change while SKU stays. SKU is the
    identity, description is descriptive metadata."""
    before = _item("SKU-1", description="Foo")
    after = _item("SKU-1", description="Bar")
    result = diff_estimate([before], [after])
    assert len(result.changed) == 1
    assert result.changed[0].changed_fields == ("description",)


def test_note_only_change_appears_as_changed():
    before = _item("SKU-1", note="")
    after = _item("SKU-1", note="Updated note")
    result = diff_estimate([before], [after])
    assert len(result.changed) == 1
    assert result.changed[0].changed_fields == ("note",)


def test_changed_sorted_by_sku():
    before = [_item("SKU-Z", quantity=1), _item("SKU-A", quantity=1)]
    after = [_item("SKU-Z", quantity=2), _item("SKU-A", quantity=2)]
    result = diff_estimate(before, after)
    assert [c.sku for c in result.changed] == ["SKU-A", "SKU-Z"]


# ---------- Mixed ----------


def test_mixed_add_remove_change():
    before = [
        _item("SKU-1", quantity=10),  # changed
        _item("SKU-2", quantity=20),  # unchanged
        _item("SKU-3", quantity=30),  # removed
    ]
    after = [
        _item("SKU-1", quantity=15),  # changed
        _item("SKU-2", quantity=20),  # unchanged
        _item("SKU-4", quantity=40),  # added
    ]
    result = diff_estimate(before, after)
    assert len(result.added) == 1
    assert result.added[0].sku == "SKU-4"
    assert len(result.removed) == 1
    assert result.removed[0].sku == "SKU-3"
    assert len(result.changed) == 1
    assert result.changed[0].sku == "SKU-1"
    assert result.unchanged_count == 1


# ---------- Unchanged count ----------


def test_unchanged_count_excludes_changed_items():
    """Pin: unchanged_count counts ONLY items identical between
    versions. Items with any field differing → changed, not
    unchanged."""
    before = [_item("SKU-1"), _item("SKU-2"), _item("SKU-3", quantity=10)]
    after = [_item("SKU-1"), _item("SKU-2"), _item("SKU-3", quantity=20)]
    result = diff_estimate(before, after)
    assert result.unchanged_count == 2  # SKU-1, SKU-2 unchanged
    assert len(result.changed) == 1  # SKU-3 changed


def test_unchanged_count_zero_when_all_changed():
    before = [_item("SKU-1", quantity=1), _item("SKU-2", quantity=1)]
    after = [_item("SKU-1", quantity=2), _item("SKU-2", quantity=2)]
    result = diff_estimate(before, after)
    assert result.unchanged_count == 0
    assert len(result.changed) == 2


# ---------- SKU identity invariants ----------


def test_sku_is_the_identity_not_description():
    """Cardinal pin: SKU identifies the item. Two items with the
    same SKU but different descriptions are the SAME item with a
    description change — NOT one removed + one added."""
    before = [_item("SKU-1", description="Old name")]
    after = [_item("SKU-1", description="New name")]
    result = diff_estimate(before, after)
    assert result.added == ()
    assert result.removed == ()
    assert len(result.changed) == 1
    assert result.changed[0].changed_fields == ("description",)


# ---------- Frozen invariants ----------


def test_estimate_diff_is_frozen():
    d = EstimateDiff(added=(), removed=(), changed=(), unchanged_count=0)
    try:
        d.unchanged_count = 5  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("EstimateDiff should be frozen")


def test_line_item_change_is_frozen():
    item = _item("SKU-1")
    c = LineItemChange(sku="SKU-1", before=item, after=item, changed_fields=())
    try:
        c.sku = "SKU-2"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("LineItemChange should be frozen")
