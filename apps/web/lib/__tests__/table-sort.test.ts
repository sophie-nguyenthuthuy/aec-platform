/**
 * Frontend table sort helper (cycle KK3).
 *
 * Pinned seams:
 *   1. Input array NOT mutated.
 *   2. Stable: tied rows preserve input order.
 *   3. Null/undefined → END regardless of direction.
 *   4. Empty sortKeys → input copy.
 *   5. Multi-column tie-break.
 *   6. Asc / desc direction respected.
 */

import { describe, expect, it } from "vitest";

import { type SortKey, sortRows } from "../table-sort";


interface Row {
  id: number;
  name: string | null;
  age: number | null;
  group?: string;
}


// ---------- Basic ----------


describe("sortRows — basic", () => {
  it("returns empty for empty input", () => {
    expect(sortRows([], [])).toEqual([]);
  });

  it("returns copy for empty sortKeys", () => {
    const rows: Row[] = [{ id: 2, name: "B", age: 30 }, { id: 1, name: "A", age: 25 }];
    const result = sortRows(rows, []);
    expect(result).toEqual(rows);
    // Pin: returns a NEW array (copy), not the same reference.
    expect(result).not.toBe(rows);
  });

  it("sorts ascending by single key", () => {
    const rows: Row[] = [
      { id: 3, name: "C", age: 30 },
      { id: 1, name: "A", age: 25 },
      { id: 2, name: "B", age: 28 },
    ];
    const result = sortRows(rows, [{ key: "name", direction: "asc" }]);
    expect(result.map((r) => r.name)).toEqual(["A", "B", "C"]);
  });

  it("sorts descending by single key", () => {
    const rows: Row[] = [
      { id: 1, name: "A", age: 25 },
      { id: 2, name: "B", age: 28 },
      { id: 3, name: "C", age: 30 },
    ];
    const result = sortRows(rows, [{ key: "age", direction: "desc" }]);
    expect(result.map((r) => r.age)).toEqual([30, 28, 25]);
  });

  it("sorts numeric values numerically", () => {
    const rows: Row[] = [
      { id: 1, name: null, age: 100 },
      { id: 2, name: null, age: 9 },
      { id: 3, name: null, age: 25 },
    ];
    const result = sortRows(rows, [{ key: "age", direction: "asc" }]);
    expect(result.map((r) => r.age)).toEqual([9, 25, 100]);
  });
});


// ---------- Immutability ----------


describe("sortRows — immutability", () => {
  it("does not mutate the input array", () => {
    const rows: Row[] = [
      { id: 2, name: "B", age: 30 },
      { id: 1, name: "A", age: 25 },
    ];
    const snapshot = rows.map((r) => ({ ...r }));
    sortRows(rows, [{ key: "name", direction: "asc" }]);
    expect(rows).toEqual(snapshot);
  });

  it("returns a new array reference", () => {
    const rows: Row[] = [{ id: 1, name: "A", age: 25 }];
    const result = sortRows(rows, [{ key: "name", direction: "asc" }]);
    expect(result).not.toBe(rows);
  });
});


// ---------- Stability ----------


describe("sortRows — stability", () => {
  it("preserves input order for tied rows (single key)", () => {
    // Three rows with the same `name`, distinct `id` showing
    // input order. After sorting by name, ids should preserve
    // their original sequence.
    const rows: Row[] = [
      { id: 10, name: "A", age: 0 },
      { id: 20, name: "A", age: 0 },
      { id: 30, name: "A", age: 0 },
    ];
    const result = sortRows(rows, [{ key: "name", direction: "asc" }]);
    expect(result.map((r) => r.id)).toEqual([10, 20, 30]);
  });

  it("preserves input order for tied rows (multi-column)", () => {
    const rows: Row[] = [
      { id: 1, name: "A", age: 25 },
      { id: 2, name: "A", age: 25 },
      { id: 3, name: "A", age: 25 },
    ];
    const result = sortRows(rows, [
      { key: "name", direction: "asc" },
      { key: "age", direction: "asc" },
    ]);
    expect(result.map((r) => r.id)).toEqual([1, 2, 3]);
  });

  it("stable sort holds even after desc reversal", () => {
    // Rows with identical sort key. Desc preserves stability
    // (NOT reversed input order) because tied rows have
    // cmp=0 → fall through to original-index tie-break.
    const rows: Row[] = [
      { id: 1, name: "A", age: 25 },
      { id: 2, name: "A", age: 25 },
    ];
    const result = sortRows(rows, [{ key: "name", direction: "desc" }]);
    expect(result.map((r) => r.id)).toEqual([1, 2]);
  });
});


// ---------- Null/undefined ----------


describe("sortRows — null/undefined to end", () => {
  it("sorts null to end on asc", () => {
    const rows: Row[] = [
      { id: 1, name: null, age: 25 },
      { id: 2, name: "B", age: 30 },
      { id: 3, name: "A", age: 28 },
    ];
    const result = sortRows(rows, [{ key: "name", direction: "asc" }]);
    expect(result.map((r) => r.name)).toEqual(["A", "B", null]);
  });

  it("sorts null to end on desc TOO (NOT to start)", () => {
    // Cardinal pin: null is ALWAYS at the end regardless of
    // direction. Defends against `null < anything` in JS string
    // compare silently surfacing nulls at the top of a desc
    // sort.
    const rows: Row[] = [
      { id: 1, name: null, age: 25 },
      { id: 2, name: "B", age: 30 },
      { id: 3, name: "A", age: 28 },
    ];
    const result = sortRows(rows, [{ key: "name", direction: "desc" }]);
    expect(result.map((r) => r.name)).toEqual(["B", "A", null]);
  });

  it("sorts undefined to end same as null", () => {
    const rows: Row[] = [
      { id: 1, name: "A", age: 25, group: undefined },
      { id: 2, name: "B", age: 30, group: "x" },
      { id: 3, name: "C", age: 28, group: "y" },
    ];
    const result = sortRows(rows, [{ key: "group", direction: "asc" }]);
    expect(result.map((r) => r.id)).toEqual([2, 3, 1]);
  });

  it("multiple null rows preserve input order", () => {
    const rows: Row[] = [
      { id: 1, name: null, age: 25 },
      { id: 2, name: "A", age: 30 },
      { id: 3, name: null, age: 28 },
    ];
    const result = sortRows(rows, [{ key: "name", direction: "asc" }]);
    // Non-null first, then nulls in input order.
    expect(result.map((r) => r.id)).toEqual([2, 1, 3]);
  });
});


// ---------- Multi-column ----------


describe("sortRows — multi-column", () => {
  it("primary asc, secondary asc", () => {
    const rows: Row[] = [
      { id: 1, name: "A", age: 30 },
      { id: 2, name: "A", age: 25 },
      { id: 3, name: "B", age: 28 },
    ];
    const result = sortRows(rows, [
      { key: "name", direction: "asc" },
      { key: "age", direction: "asc" },
    ]);
    // Primary "A" group, secondary by age ascending.
    expect(result.map((r) => r.id)).toEqual([2, 1, 3]);
  });

  it("primary asc, secondary desc", () => {
    const rows: Row[] = [
      { id: 1, name: "A", age: 30 },
      { id: 2, name: "A", age: 25 },
      { id: 3, name: "B", age: 28 },
    ];
    const result = sortRows(rows, [
      { key: "name", direction: "asc" },
      { key: "age", direction: "desc" },
    ]);
    expect(result.map((r) => r.id)).toEqual([1, 2, 3]);
  });

  it("secondary key only applied on primary tie", () => {
    // Distinct primary values → secondary irrelevant.
    const rows: Row[] = [
      { id: 1, name: "C", age: 25 },
      { id: 2, name: "A", age: 30 },
      { id: 3, name: "B", age: 28 },
    ];
    const result = sortRows(rows, [
      { key: "name", direction: "asc" },
      { key: "age", direction: "desc" },
    ]);
    // Primary alone determines order: A, B, C.
    expect(result.map((r) => r.name)).toEqual(["A", "B", "C"]);
  });
});


// ---------- Defensive ----------


describe("sortRows — defensive", () => {
  it("handles single-row input", () => {
    const rows: Row[] = [{ id: 1, name: "A", age: 25 }];
    expect(sortRows(rows, [{ key: "name", direction: "asc" }])).toEqual(rows);
  });

  it("handles all-equal input (full ties)", () => {
    const rows: Row[] = [
      { id: 1, name: "X", age: 25 },
      { id: 2, name: "X", age: 25 },
      { id: 3, name: "X", age: 25 },
    ];
    const result = sortRows(rows, [
      { key: "name", direction: "asc" },
      { key: "age", direction: "asc" },
    ]);
    expect(result.map((r) => r.id)).toEqual([1, 2, 3]);
  });

  it("handles all-null input on a sort key", () => {
    const rows: Row[] = [
      { id: 1, name: null, age: 25 },
      { id: 2, name: null, age: 30 },
    ];
    const result = sortRows(rows, [
      { key: "name", direction: "asc" },
      { key: "age", direction: "asc" },
    ]);
    // Both null on name → fall through to age.
    expect(result.map((r) => r.id)).toEqual([1, 2]);
  });
});
