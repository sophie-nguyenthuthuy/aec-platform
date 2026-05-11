/**
 * Time-window helpers (cycle Z3, TS half).
 *
 * Pinned seams:
 *   1. TIME_WINDOW_OPTIONS chip set + order.
 *   2. parseSinceDays accepts [1, 365], rejects out-of-range.
 *   3. formatRelativeAge thresholds: <60s vừa xong, <60m phút,
 *      <24h giờ, <30d ngày, <12mo tháng, else năm.
 *   4. Future-dated → "trong tương lai" (clock skew defense).
 *   5. Malformed timestamp → "" (no crash).
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_SINCE_DAYS,
  MAX_SINCE_DAYS,
  TIME_WINDOW_OPTIONS,
  formatRelativeAge,
  parseSinceDays,
} from "../time-window";


// ---------- Constants ----------


describe("TIME_WINDOW_OPTIONS", () => {
  it("has the canonical 4-chip set in the canonical order", () => {
    // Order matters — a refactor that swaps "24h" and "7d" would
    // make the chip layout drift across pages.
    expect(TIME_WINDOW_OPTIONS).toEqual([
      { value: 1, label: "24h" },
      { value: 7, label: "7d" },
      { value: 30, label: "30d" },
      { value: null, label: "Tất cả" },
    ]);
  });

  it("includes a null sentinel for 'all time'", () => {
    // The null entry is the wire-level "no filter" — pin so a
    // refactor that removes it forces every page to special-case
    // the unfiltered render.
    const allTimeChip = TIME_WINDOW_OPTIONS.find((o) => o.value === null);
    expect(allTimeChip).toBeDefined();
  });
});


describe("MAX_SINCE_DAYS", () => {
  it("is pinned to 365 (matches API Query(le=365))", () => {
    expect(MAX_SINCE_DAYS).toBe(365);
  });
});


describe("DEFAULT_SINCE_DAYS", () => {
  it("is 7 — the converged 'last week' default across pages", () => {
    expect(DEFAULT_SINCE_DAYS).toBe(7);
  });
});


// ---------- parseSinceDays ----------


describe("parseSinceDays", () => {
  it("returns null for null / undefined / empty string (all-time)", () => {
    expect(parseSinceDays(null)).toBeNull();
    expect(parseSinceDays(undefined)).toBeNull();
    expect(parseSinceDays("")).toBeNull();
  });

  it("accepts numeric input within [1, 365]", () => {
    expect(parseSinceDays(1)).toBe(1);
    expect(parseSinceDays(7)).toBe(7);
    expect(parseSinceDays(365)).toBe(365);
  });

  it("accepts numeric strings", () => {
    // URL query strings arrive as strings; pin coercion.
    expect(parseSinceDays("7")).toBe(7);
    expect(parseSinceDays("30")).toBe(30);
  });

  it("rejects out-of-range values (graceful fallback to null)", () => {
    // Below floor.
    expect(parseSinceDays(0)).toBeNull();
    expect(parseSinceDays(-1)).toBeNull();
    // Above ceiling — pin to MAX_SINCE_DAYS.
    expect(parseSinceDays(366)).toBeNull();
    expect(parseSinceDays(10_000)).toBeNull();
  });

  it("rejects non-numeric strings (graceful fallback)", () => {
    // A stale URL with an invalid since_days shouldn't crash —
    // graceful fallback to "all time."
    expect(parseSinceDays("abc")).toBeNull();
    expect(parseSinceDays("7d")).toBeNull();
  });

  it("truncates fractional input to integer", () => {
    // The API expects integer days; floats from a URL typo get
    // floored rather than rejected.
    expect(parseSinceDays(7.9)).toBe(7);
    expect(parseSinceDays("7.5")).toBe(7);
  });

  it("handles infinity / NaN safely", () => {
    expect(parseSinceDays(Number.POSITIVE_INFINITY)).toBeNull();
    expect(parseSinceDays(Number.NaN)).toBeNull();
  });
});


// ---------- formatRelativeAge ----------


const NOW = new Date("2026-05-09T12:00:00Z");


describe("formatRelativeAge", () => {
  it("returns 'vừa xong' for <60s ago", () => {
    expect(
      formatRelativeAge("2026-05-09T11:59:30Z", NOW),
    ).toBe("vừa xong");
  });

  it("returns 'N phút trước' for <60m", () => {
    expect(
      formatRelativeAge("2026-05-09T11:37:00Z", NOW),
    ).toBe("23 phút trước");
  });

  it("returns 'N giờ trước' for <24h", () => {
    expect(
      formatRelativeAge("2026-05-09T09:00:00Z", NOW),
    ).toBe("3 giờ trước");
  });

  it("returns 'N ngày trước' for <30d", () => {
    expect(
      formatRelativeAge("2026-05-04T12:00:00Z", NOW),
    ).toBe("5 ngày trước");
  });

  it("returns 'N tháng trước' for <12mo", () => {
    // ~3 months ago: 90 days.
    expect(
      formatRelativeAge("2026-02-08T12:00:00Z", NOW),
    ).toBe("3 tháng trước");
  });

  it("returns 'N năm trước' for >=1 year", () => {
    // ~2 years ago.
    expect(
      formatRelativeAge("2024-05-09T12:00:00Z", NOW),
    ).toBe("2 năm trước");
  });

  it("returns 'trong tương lai' for future-dated input", () => {
    // Defensive: a row with a clock-skewed future timestamp
    // shouldn't render "X giờ trước" with a negative N.
    expect(
      formatRelativeAge("2026-05-09T13:00:00Z", NOW),
    ).toBe("trong tương lai");
  });

  it("returns '' for null / undefined / empty", () => {
    // Calling code can chain `formatRelativeAge(row.last_used_at)`
    // without null checks — empty string slots into the JSX
    // without crashing.
    expect(formatRelativeAge(null, NOW)).toBe("");
    expect(formatRelativeAge(undefined, NOW)).toBe("");
    expect(formatRelativeAge("", NOW)).toBe("");
  });

  it("returns '' for malformed timestamps", () => {
    // A corrupt audit row with a bad timestamp shouldn't crash
    // the row render.
    expect(formatRelativeAge("not-a-date", NOW)).toBe("");
  });

  it("uses the supplied 'now' for determinism", () => {
    // Two calls with the same `now` MUST return the same string —
    // pin so a refactor that introduces side-effects (Date.now())
    // breaks here.
    const a = formatRelativeAge("2026-05-09T09:00:00Z", NOW);
    const b = formatRelativeAge("2026-05-09T09:00:00Z", NOW);
    expect(a).toBe(b);
  });
});
