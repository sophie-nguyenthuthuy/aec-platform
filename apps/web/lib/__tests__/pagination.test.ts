/**
 * Frontend pagination helper (cycle FF3).
 *
 * Pinned seams:
 *   1. totalPages = 1 → [1] (no ellipsis).
 *   2. totalPages = 0 / negative → [].
 *   3. currentPage is always in the output.
 *   4. First (1) and last (totalPages) are always in the output.
 *   5. Ellipsis only when adjacent rendered numbers have gap >1.
 *   6. No consecutive ellipses.
 *   7. currentPage out of range clamps.
 *   8. siblingCount=0 still renders current + first + last.
 */

import { describe, expect, it } from "vitest";

import { type PageToken, buildPageRange } from "../pagination";


// ---------- Edge cases ----------


describe("buildPageRange — degenerate", () => {
  it("returns [1] for totalPages = 1", () => {
    expect(buildPageRange(1, 1)).toEqual([1]);
  });

  it("returns [] for totalPages = 0", () => {
    expect(buildPageRange(1, 0)).toEqual([]);
  });

  it("returns [] for negative totalPages", () => {
    expect(buildPageRange(1, -1)).toEqual([]);
  });
});


// ---------- Small ranges (no ellipsis) ----------


describe("buildPageRange — small totals", () => {
  it("renders all pages when total is small enough", () => {
    expect(buildPageRange(3, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  it("renders without ellipsis when range fits", () => {
    expect(buildPageRange(2, 4)).toEqual([1, 2, 3, 4]);
    expect(buildPageRange(1, 3)).toEqual([1, 2, 3]);
  });
});


// ---------- One-side ellipsis ----------


describe("buildPageRange — leading ellipsis", () => {
  it("shows leading ellipsis when current is near the end", () => {
    expect(buildPageRange(20, 20)).toEqual([1, "ellipsis", 19, 20]);
  });

  it("shows trailing ellipsis when current is near the start", () => {
    expect(buildPageRange(1, 20)).toEqual([1, 2, "ellipsis", 20]);
  });

  it("shows trailing ellipsis with current=2", () => {
    // 1, 2, 3, ..., 20 — 1 and 2 and 3 are adjacent, gap to 20.
    expect(buildPageRange(2, 20)).toEqual([1, 2, 3, "ellipsis", 20]);
  });
});


// ---------- Both-side ellipsis ----------


describe("buildPageRange — both ellipses", () => {
  it("shows both leading and trailing ellipsis when current is in the middle", () => {
    expect(buildPageRange(5, 20)).toEqual([1, "ellipsis", 4, 5, 6, "ellipsis", 20]);
  });

  it("shows both ellipses for far-middle page", () => {
    expect(buildPageRange(10, 20)).toEqual([1, "ellipsis", 9, 10, 11, "ellipsis", 20]);
  });
});


// ---------- siblingCount ----------


describe("buildPageRange — siblingCount", () => {
  it("default siblingCount = 1", () => {
    // Confirm default by comparing explicit and default calls.
    expect(buildPageRange(5, 20)).toEqual(buildPageRange(5, 20, 1));
  });

  it("siblingCount = 0 still shows first, last, and current", () => {
    expect(buildPageRange(5, 20, 0)).toEqual([1, "ellipsis", 5, "ellipsis", 20]);
  });

  it("siblingCount = 3 shows wider neighbour band", () => {
    expect(buildPageRange(5, 20, 3)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, "ellipsis", 20,
    ]);
  });
});


// ---------- Clamping ----------


describe("buildPageRange — currentPage clamping", () => {
  it("clamps currentPage = 0 to 1", () => {
    expect(buildPageRange(0, 5)).toEqual(buildPageRange(1, 5));
  });

  it("clamps currentPage > totalPages to totalPages", () => {
    expect(buildPageRange(99, 5)).toEqual(buildPageRange(5, 5));
  });

  it("clamps negative currentPage to 1", () => {
    expect(buildPageRange(-3, 10)).toEqual(buildPageRange(1, 10));
  });
});


// ---------- Invariants ----------


describe("buildPageRange — invariants", () => {
  const cases = [
    { current: 1, total: 1 },
    { current: 1, total: 5 },
    { current: 3, total: 5 },
    { current: 5, total: 20 },
    { current: 10, total: 20 },
    { current: 20, total: 20 },
    { current: 1, total: 100 },
    { current: 50, total: 100 },
  ];

  it("currentPage is always in the output", () => {
    for (const { current, total } of cases) {
      const result = buildPageRange(current, total);
      expect(result).toContain(current);
    }
  });

  it("first page (1) is always in the output", () => {
    for (const { current, total } of cases) {
      const result = buildPageRange(current, total);
      expect(result).toContain(1);
    }
  });

  it("last page (totalPages) is always in the output", () => {
    for (const { current, total } of cases) {
      const result = buildPageRange(current, total);
      expect(result).toContain(total);
    }
  });

  it("never has consecutive ellipses", () => {
    // A refactor that double-inserts an ellipsis between the
    // same adjacent number pair would surface here.
    const allCases = [
      ...cases,
      { current: 5, total: 20, sibling: 0 },
      { current: 5, total: 20, sibling: 3 },
    ];
    for (const c of allCases) {
      const result = buildPageRange(
        c.current,
        c.total,
        (c as { sibling?: number }).sibling,
      );
      for (let i = 0; i < result.length - 1; i++) {
        if (result[i] === "ellipsis" && result[i + 1] === "ellipsis") {
          throw new Error(
            `consecutive ellipses at ${i} for ${JSON.stringify(c)}: ${JSON.stringify(result)}`,
          );
        }
      }
    }
  });

  it("ellipsis only when adjacent number gap > 1", () => {
    for (const { current, total } of cases) {
      const result: PageToken[] = buildPageRange(current, total);
      for (let i = 0; i < result.length - 1; i++) {
        const a = result[i];
        const b = result[i + 1];
        if (typeof a === "number" && typeof b === "number") {
          // Adjacent numbers — gap MUST be 1.
          expect(b - a).toBe(1);
        }
      }
    }
  });

  it("output is strictly ascending in number positions", () => {
    // Pin sort: numbers appear in ascending order; an "ellipsis"
    // only appears between strictly-ascending number pairs.
    for (const { current, total } of cases) {
      const result = buildPageRange(current, total);
      const nums = result.filter((x): x is number => typeof x === "number");
      for (let i = 0; i < nums.length - 1; i++) {
        expect(nums[i]!).toBeLessThan(nums[i + 1]!);
      }
    }
  });
});
