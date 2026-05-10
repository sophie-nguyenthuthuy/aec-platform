/**
 * Estimate version diff helper (cycle LL1, TS half).
 *
 * Diff two estimate versions, returning structured added/
 * removed/changed line-item lists. Today the estimate detail
 * page's version-compare view + the audit row's diff display
 * each duplicate the logic inline. This module is the single
 * source of truth.
 *
 *   diffEstimate(before, after) — EstimateDiff
 *
 * Pure TS, no React. Mirrors `apps/api/services/estimate_diff.py`.
 *
 * Pinned invariants:
 *   * Line items keyed by SKU (NOT description).
 *   * Output deterministic: added/removed/changed sorted by SKU.
 *   * `unchanged_count` (NOT a full list) for snapshot stability.
 *   * `changed_fields` in declaration order (NOT alphabetical).
 */


export interface LineItem {
  sku: string;
  description: string;
  quantity: number;
  unit_price: number;
  note: string;
}


export interface LineItemChange {
  sku: string;
  before: LineItem;
  after: LineItem;
  /** Field names that differ, in declaration order. */
  changed_fields: readonly string[];
}


export interface EstimateDiff {
  added: readonly LineItem[];
  removed: readonly LineItem[];
  changed: readonly LineItemChange[];
  unchanged_count: number;
}


/** Canonical field-declaration order. Diff iterates in this
 *  exact order so the `changed_fields` array is predictable. */
const _FIELDS_TO_DIFF: readonly (keyof LineItem)[] = [
  "description",
  "quantity",
  "unit_price",
  "note",
];


function _diffFields(before: LineItem, after: LineItem): string[] {
  return _FIELDS_TO_DIFF.filter((f) => before[f] !== after[f]);
}


/**
 * Diff two estimate versions.
 *
 *   * diffEstimate([], [])               → all empty
 *   * diffEstimate([], [item])           → 1 added
 *   * diffEstimate([item], [])           → 1 removed
 *   * diffEstimate([before], [after])    → 1 changed (if differ)
 */
export function diffEstimate(
  before: readonly LineItem[],
  after: readonly LineItem[],
): EstimateDiff {
  const beforeBySku = new Map<string, LineItem>();
  for (const item of before) beforeBySku.set(item.sku, item);

  const afterBySku = new Map<string, LineItem>();
  for (const item of after) afterBySku.set(item.sku, item);

  const beforeSkus = new Set(beforeBySku.keys());
  const afterSkus = new Set(afterBySku.keys());

  const addedSkus = [...afterSkus].filter((s) => !beforeSkus.has(s)).sort();
  const removedSkus = [...beforeSkus].filter((s) => !afterSkus.has(s)).sort();
  const commonSkus = [...beforeSkus].filter((s) => afterSkus.has(s)).sort();

  const added: LineItem[] = addedSkus.map((s) => afterBySku.get(s)!);
  const removed: LineItem[] = removedSkus.map((s) => beforeBySku.get(s)!);

  const changed: LineItemChange[] = [];
  let unchanged_count = 0;
  for (const sku of commonSkus) {
    const beforeItem = beforeBySku.get(sku)!;
    const afterItem = afterBySku.get(sku)!;
    const changedFields = _diffFields(beforeItem, afterItem);
    if (changedFields.length > 0) {
      changed.push({
        sku,
        before: beforeItem,
        after: afterItem,
        changed_fields: changedFields,
      });
    } else {
      unchanged_count++;
    }
  }

  return { added, removed, changed, unchanged_count };
}
