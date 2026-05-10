/**
 * Date range parser (cycle JJ2, TS half).
 *
 * Pinned seams:
 *   1. MAX_RANGE_DAYS = 365.
 *   2. ISO YYYY-MM-DD format throughout.
 *   3. Closed interval (start and end both inclusive).
 *   4. Both ends optional; at least one required.
 *   5. Relative `Nd` shorthand and `now` keyword.
 *   6. Range > MAX_RANGE_DAYS → null.
 *   7. start > end → null.
 *   8. Malformed dates (e.g. 2026-02-31) → null.
 */

import { describe, expect, it } from "vitest";

import { MAX_RANGE_DAYS, parseDateRange } from "../date-range";


const TODAY = "2026-05-10";


// ---------- Constants ----------


describe("MAX_RANGE_DAYS", () => {
  it("is 365 (defends against multi-year queries)", () => {
    expect(MAX_RANGE_DAYS).toBe(365);
  });
});


// ---------- ISO date inputs ----------


describe("parseDateRange — ISO inputs", () => {
  it("parses both ends as ISO", () => {
    expect(parseDateRange("2026-01-01", "2026-01-31", TODAY)).toEqual({
      start: "2026-01-01",
      end: "2026-01-31",
    });
  });

  it("parses same start and end (single day)", () => {
    expect(parseDateRange("2026-05-10", "2026-05-10", TODAY)).toEqual({
      start: "2026-05-10",
      end: "2026-05-10",
    });
  });
});


// ---------- Relative shorthand ----------


describe("parseDateRange — relative shorthand", () => {
  it("parses Nd as N days before today", () => {
    expect(parseDateRange("7d", "now", TODAY)).toEqual({
      start: "2026-05-03",
      end: "2026-05-10",
    });
  });

  it("supports `now` keyword", () => {
    expect(parseDateRange("2026-05-01", "now", TODAY)).toEqual({
      start: "2026-05-01",
      end: "2026-05-10",
    });
  });

  it("supports relative on both ends", () => {
    expect(parseDateRange("30d", "1d", TODAY)).toEqual({
      start: "2026-04-10",
      end: "2026-05-09",
    });
  });

  it("rejects 0d (below min)", () => {
    expect(parseDateRange("0d", "now", TODAY)).toBeNull();
  });

  it("rejects relative beyond MAX_RANGE_DAYS", () => {
    expect(parseDateRange("400d", "now", TODAY)).toBeNull();
  });
});


// ---------- One-sided ranges ----------


describe("parseDateRange — one-sided", () => {
  it("from only → end defaults to today", () => {
    expect(parseDateRange("7d", null, TODAY)).toEqual({
      start: "2026-05-03",
      end: "2026-05-10",
    });
  });

  it("to only → start defaults to MAX_RANGE_DAYS ago", () => {
    const result = parseDateRange(null, "2026-05-01", TODAY);
    expect(result).not.toBeNull();
    expect(result!.end).toBe("2026-05-01");
  });

  it("returns null when both ends are null/undefined/empty", () => {
    expect(parseDateRange(null, null, TODAY)).toBeNull();
    expect(parseDateRange(undefined, undefined, TODAY)).toBeNull();
    expect(parseDateRange("", "", TODAY)).toBeNull();
  });
});


// ---------- Validation ----------


describe("parseDateRange — validation", () => {
  it("rejects start > end", () => {
    expect(parseDateRange("2026-02-01", "2026-01-01", TODAY)).toBeNull();
  });

  it("rejects range exceeding MAX_RANGE_DAYS", () => {
    expect(parseDateRange("2025-01-01", "2026-12-31", TODAY)).toBeNull();
  });

  it("accepts range exactly at MAX_RANGE_DAYS", () => {
    // 365 days from start to end inclusive.
    const result = parseDateRange("2025-05-10", "2026-05-10", TODAY);
    expect(result).not.toBeNull();
  });

  it("rejects malformed ISO dates", () => {
    expect(parseDateRange("not-a-date", "2026-01-01", TODAY)).toBeNull();
    expect(parseDateRange("2026-13-01", "now", TODAY)).toBeNull();  // bad month
    expect(parseDateRange("2026-02-31", "now", TODAY)).toBeNull();  // bad day
  });

  it("rejects empty strings (treated as missing)", () => {
    expect(parseDateRange("", "", TODAY)).toBeNull();
  });
});


// ---------- Defensive ----------


describe("parseDateRange — defensive", () => {
  it("returns null for invalid today", () => {
    expect(parseDateRange("7d", "now", "not-a-date")).toBeNull();
  });

  it("strips whitespace in values", () => {
    expect(parseDateRange("  7d  ", "  now  ", TODAY)).toEqual({
      start: "2026-05-03",
      end: "2026-05-10",
    });
  });

  it("`now` is case-insensitive", () => {
    expect(parseDateRange("2026-05-01", "NOW", TODAY)?.end).toBe("2026-05-10");
    expect(parseDateRange("2026-05-01", "Now", TODAY)?.end).toBe("2026-05-10");
  });
});
