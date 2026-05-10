"""Estimate version diff helper (cycle LL1, Python half).

Diff two estimate versions, returning structured added/removed/
changed line-item lists. Today the estimate detail page's
version-compare view, the audit row's `estimate.version.compare`
emit, and the email digest's "what changed" summary each
duplicate the diff logic inline. This module is the single
source of truth.

  LineItem            — frozen dataclass: (sku, description, quantity, unit_price, note)
  LineItemChange      — frozen: (sku, before, after, changed_fields)
  EstimateDiff        — frozen: (added, removed, changed, unchanged_count)
  diff_estimate(b, a) — main entry point

Composes with X1's `audit_diff` field-comparison conventions.

Pinned invariants:
  * Line items keyed by SKU (NOT description — description is a
    free-form field that may drift between versions).
  * Output deterministic: added/removed/changed all sorted by SKU.
  * `unchanged_count` (NOT a full unchanged list) so snapshot
    tests stay stable when most items are unchanged.
  * `changed_fields` ordered by canonical declaration order,
    NOT alphabetical (pin so audit-trail diff displays consistent).

Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass

# Canonical field-declaration order. Diff iterates in this exact
# order so the `changed_fields` tuple has predictable shape.
# NOT alphabetical — declaration order matches the UI's column
# layout in the estimate-detail line-item table.
_FIELDS_TO_DIFF: tuple[str, ...] = (
    "description",
    "quantity",
    "unit_price",
    "note",
)


@dataclass(frozen=True)
class LineItem:
    """One row of an estimate. SKU is the identity key."""

    sku: str
    description: str
    quantity: float
    unit_price: float
    note: str


@dataclass(frozen=True)
class LineItemChange:
    """A line item that exists in both versions but with at least
    one differing field."""

    sku: str
    before: LineItem
    after: LineItem
    # Tuple of field names that differ. Order matches
    # _FIELDS_TO_DIFF declaration order (NOT alphabetical).
    changed_fields: tuple[str, ...]


@dataclass(frozen=True)
class EstimateDiff:
    """Structured diff result.

    `unchanged_count` is the count of SKUs identical between
    versions (rather than a full unchanged list — keeps snapshot
    tests stable when most items are unchanged).
    """

    added: tuple[LineItem, ...]
    removed: tuple[LineItem, ...]
    changed: tuple[LineItemChange, ...]
    unchanged_count: int


def _diff_fields(before: LineItem, after: LineItem) -> tuple[str, ...]:
    """Return tuple of field names that differ between two
    line items (in declaration order)."""
    return tuple(f for f in _FIELDS_TO_DIFF if getattr(before, f) != getattr(after, f))


def diff_estimate(
    before: list[LineItem],
    after: list[LineItem],
) -> EstimateDiff:
    """Diff two estimate versions.

    Returns `EstimateDiff` with added/removed/changed lists
    sorted by SKU and an `unchanged_count` for matched-identical
    items.
    """
    before_by_sku = {item.sku: item for item in before}
    after_by_sku = {item.sku: item for item in after}

    before_skus = set(before_by_sku.keys())
    after_skus = set(after_by_sku.keys())

    added_skus = sorted(after_skus - before_skus)
    removed_skus = sorted(before_skus - after_skus)
    common_skus = sorted(before_skus & after_skus)

    added = tuple(after_by_sku[s] for s in added_skus)
    removed = tuple(before_by_sku[s] for s in removed_skus)

    changed: list[LineItemChange] = []
    unchanged_count = 0
    for sku in common_skus:
        before_item = before_by_sku[sku]
        after_item = after_by_sku[sku]
        changed_fields = _diff_fields(before_item, after_item)
        if changed_fields:
            changed.append(
                LineItemChange(
                    sku=sku,
                    before=before_item,
                    after=after_item,
                    changed_fields=changed_fields,
                )
            )
        else:
            unchanged_count += 1

    return EstimateDiff(
        added=added,
        removed=removed,
        changed=tuple(changed),
        unchanged_count=unchanged_count,
    )
