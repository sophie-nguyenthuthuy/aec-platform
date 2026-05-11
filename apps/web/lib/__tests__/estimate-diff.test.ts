/**
 * Estimate version diff helper (cycle LL1, TS half).
 *
 * Pinned seams:
 *   1. Keyed by SKU.
 *   2. added/removed/changed sorted by SKU.
 *   3. unchanged_count (NOT full list).
 *   4. changed_fields in declaration order.
 */

import { describe, expect, it } from "vitest";

import { type LineItem, diffEstimate } from "../estimate-diff";


function _item(overrides: Partial<LineItem> & { sku: string }): LineItem {
  return {
    description: "default",
    quantity: 1.0,
    unit_price: 100.0,
    note: "",
    ...overrides,
  };
}


// ---------- Empty / identical ----------


describe("diffEstimate — empty / identical", () => {
  it("empty both returns empty diff", () => {
    const d = diffEstimate([], []);
    expect(d.added).toEqual([]);
    expect(d.removed).toEqual([]);
    expect(d.changed).toEqual([]);
    expect(d.unchanged_count).toBe(0);
  });

  it("identical versions yield only unchanged", () => {
    const items = [_item({ sku: "SKU-1" }), _item({ sku: "SKU-2" })];
    const d = diffEstimate(items, items);
    expect(d.added).toEqual([]);
    expect(d.removed).toEqual([]);
    expect(d.changed).toEqual([]);
    expect(d.unchanged_count).toBe(2);
  });
});


// ---------- Add / remove ----------


describe("diffEstimate — add / remove", () => {
  it("empty before → all added", () => {
    const after = [_item({ sku: "SKU-1" }), _item({ sku: "SKU-2" })];
    const d = diffEstimate([], after);
    expect(d.added.map((i) => i.sku)).toEqual(["SKU-1", "SKU-2"]);
  });

  it("empty after → all removed", () => {
    const before = [_item({ sku: "SKU-1" }), _item({ sku: "SKU-2" })];
    const d = diffEstimate(before, []);
    expect(d.removed.map((i) => i.sku)).toEqual(["SKU-1", "SKU-2"]);
  });

  it("added sorted by SKU", () => {
    const after = [
      _item({ sku: "SKU-Z" }),
      _item({ sku: "SKU-A" }),
      _item({ sku: "SKU-M" }),
    ];
    const d = diffEstimate([], after);
    expect(d.added.map((i) => i.sku)).toEqual(["SKU-A", "SKU-M", "SKU-Z"]);
  });

  it("removed sorted by SKU", () => {
    const before = [
      _item({ sku: "SKU-Z" }),
      _item({ sku: "SKU-A" }),
      _item({ sku: "SKU-M" }),
    ];
    const d = diffEstimate(before, []);
    expect(d.removed.map((i) => i.sku)).toEqual(["SKU-A", "SKU-M", "SKU-Z"]);
  });
});


// ---------- Changed ----------


describe("diffEstimate — changed", () => {
  it("quantity change", () => {
    const d = diffEstimate(
      [_item({ sku: "SKU-1", quantity: 10 })],
      [_item({ sku: "SKU-1", quantity: 20 })],
    );
    expect(d.changed.length).toBe(1);
    expect(d.changed[0]!.changed_fields).toEqual(["quantity"]);
  });

  it("multiple field changes", () => {
    const d = diffEstimate(
      [_item({ sku: "SKU-1", quantity: 10, unit_price: 100 })],
      [_item({ sku: "SKU-1", quantity: 20, unit_price: 150 })],
    );
    expect(d.changed[0]!.changed_fields).toEqual(["quantity", "unit_price"]);
  });

  it("changed_fields in declaration order, NOT alphabetical", () => {
    const d = diffEstimate(
      [_item({ sku: "SKU-1", description: "A", quantity: 1, unit_price: 10, note: "x" })],
      [_item({ sku: "SKU-1", description: "B", quantity: 2, unit_price: 20, note: "y" })],
    );
    expect(d.changed[0]!.changed_fields).toEqual([
      "description", "quantity", "unit_price", "note",
    ]);
  });

  it("changed includes before and after", () => {
    const before = _item({ sku: "SKU-1", quantity: 10 });
    const after = _item({ sku: "SKU-1", quantity: 20 });
    const d = diffEstimate([before], [after]);
    expect(d.changed[0]!.before).toEqual(before);
    expect(d.changed[0]!.after).toEqual(after);
  });

  it("description-only change is a change (not add+remove)", () => {
    // SKU is the identity; description can drift.
    const d = diffEstimate(
      [_item({ sku: "SKU-1", description: "Foo" })],
      [_item({ sku: "SKU-1", description: "Bar" })],
    );
    expect(d.added).toEqual([]);
    expect(d.removed).toEqual([]);
    expect(d.changed.length).toBe(1);
    expect(d.changed[0]!.changed_fields).toEqual(["description"]);
  });

  it("changed sorted by SKU", () => {
    const d = diffEstimate(
      [_item({ sku: "SKU-Z", quantity: 1 }), _item({ sku: "SKU-A", quantity: 1 })],
      [_item({ sku: "SKU-Z", quantity: 2 }), _item({ sku: "SKU-A", quantity: 2 })],
    );
    expect(d.changed.map((c) => c.sku)).toEqual(["SKU-A", "SKU-Z"]);
  });
});


// ---------- Mixed ----------


describe("diffEstimate — mixed", () => {
  it("handles add + remove + change + unchanged", () => {
    const before = [
      _item({ sku: "SKU-1", quantity: 10 }),
      _item({ sku: "SKU-2", quantity: 20 }),
      _item({ sku: "SKU-3", quantity: 30 }),
    ];
    const after = [
      _item({ sku: "SKU-1", quantity: 15 }),  // changed
      _item({ sku: "SKU-2", quantity: 20 }),  // unchanged
      _item({ sku: "SKU-4", quantity: 40 }),  // added (SKU-3 removed)
    ];
    const d = diffEstimate(before, after);
    expect(d.added.length).toBe(1);
    expect(d.added[0]!.sku).toBe("SKU-4");
    expect(d.removed.length).toBe(1);
    expect(d.removed[0]!.sku).toBe("SKU-3");
    expect(d.changed.length).toBe(1);
    expect(d.changed[0]!.sku).toBe("SKU-1");
    expect(d.unchanged_count).toBe(1);
  });
});


// ---------- Unchanged count ----------


describe("diffEstimate — unchanged_count", () => {
  it("counts only items identical between versions", () => {
    const d = diffEstimate(
      [
        _item({ sku: "SKU-1" }),
        _item({ sku: "SKU-2" }),
        _item({ sku: "SKU-3", quantity: 10 }),
      ],
      [
        _item({ sku: "SKU-1" }),
        _item({ sku: "SKU-2" }),
        _item({ sku: "SKU-3", quantity: 20 }),
      ],
    );
    expect(d.unchanged_count).toBe(2);
    expect(d.changed.length).toBe(1);
  });

  it("zero when all matched items differ", () => {
    const d = diffEstimate(
      [_item({ sku: "SKU-1", quantity: 1 }), _item({ sku: "SKU-2", quantity: 1 })],
      [_item({ sku: "SKU-1", quantity: 2 }), _item({ sku: "SKU-2", quantity: 2 })],
    );
    expect(d.unchanged_count).toBe(0);
    expect(d.changed.length).toBe(2);
  });
});
