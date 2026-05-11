/**
 * Audit diff summarization (cycle X1, TS half).
 *
 * Pinned seams:
 *   1. Empty diff → empty text, zero changes.
 *   2. Two-key cap honored; totalChanges still counts beyond cap.
 *   3. ∅ for absent keys, "null" distinct from ∅.
 *   4. Object values JSON-stringified.
 *   5. `Object.is` semantics — NaN equals NaN, +0 ≠ -0.
 */

import { describe, expect, it } from "vitest";

import { formatValue, summarizeDiff, SUMMARY_KEY_CAP } from "../audit-diff";


describe("formatValue", () => {
  it("renders undefined as the ∅ glyph", () => {
    // Distinct from "null" so the diff string visually distinguishes
    // "key was absent" from "key was present and set to null."
    expect(formatValue(undefined)).toBe("∅");
  });

  it("renders null as the literal 'null'", () => {
    expect(formatValue(null)).toBe("null");
  });

  it("JSON-stringifies objects so nested diffs stay one-line", () => {
    expect(formatValue({ status: "approved", count: 3 })).toBe(
      '{"status":"approved","count":3}',
    );
    expect(formatValue([1, 2, 3])).toBe("[1,2,3]");
  });

  it("falls back to '[object]' on circular refs", () => {
    // The row should never crash on a (theoretically possible)
    // circular before/after shape.
    const o: Record<string, unknown> = {};
    o.self = o;
    expect(formatValue(o)).toBe("[object]");
  });

  it("renders primitives via String()", () => {
    expect(formatValue("draft")).toBe("draft");
    expect(formatValue(42)).toBe("42");
    expect(formatValue(true)).toBe("true");
  });
});


describe("summarizeDiff", () => {
  it("returns empty text + zero changes when before equals after", () => {
    const out = summarizeDiff({ role: "member" }, { role: "member" });
    expect(out.text).toBe("");
    expect(out.totalChanges).toBe(0);
  });

  it("renders a single key change with the → glyph", () => {
    const out = summarizeDiff(
      { role: "member" },
      { role: "admin" },
    );
    expect(out.text).toBe("role: member → admin");
    expect(out.totalChanges).toBe(1);
  });

  it("joins up to two changes with the ' · ' separator", () => {
    const out = summarizeDiff(
      { role: "member", status: "draft" },
      { role: "admin", status: "approved" },
    );
    expect(out.text).toBe("role: member → admin · status: draft → approved");
    expect(out.totalChanges).toBe(2);
  });

  it("caps inline parts at SUMMARY_KEY_CAP but counts ALL changes", () => {
    // Three changes — but the inline render only shows the first 2.
    // `totalChanges` reflects all 3 so the caller can render
    // "+ 1 more" alongside.
    const out = summarizeDiff(
      { a: 1, b: 2, c: 3 },
      { a: 10, b: 20, c: 30 },
    );
    const parts = out.text.split(" · ");
    expect(parts).toHaveLength(SUMMARY_KEY_CAP);
    expect(out.totalChanges).toBe(3);
  });

  it("renders absent-before keys as '∅ → X' (added)", () => {
    const out = summarizeDiff({}, { role: "admin" });
    expect(out.text).toBe("role: ∅ → admin");
    expect(out.totalChanges).toBe(1);
  });

  it("renders absent-after keys as 'X → ∅' (removed)", () => {
    const out = summarizeDiff({ role: "admin" }, {});
    expect(out.text).toBe("role: admin → ∅");
  });

  it("treats null as a value distinct from absent", () => {
    // A field that went from absent → null IS a change worth
    // surfacing (governance might require explicit null setting).
    const out = summarizeDiff({}, { role: null });
    expect(out.text).toBe("role: ∅ → null");
    expect(out.totalChanges).toBe(1);
  });

  it("does NOT report a change when both sides are NaN (Object.is)", () => {
    // Defensive: numeric NaN equality is the surprising case.
    // `NaN !== NaN` returns true, but `Object.is(NaN, NaN)` returns
    // true. We use Object.is so a value that's NaN on both sides
    // doesn't spam fake changes.
    const out = summarizeDiff({ x: NaN }, { x: NaN });
    expect(out.text).toBe("");
    expect(out.totalChanges).toBe(0);
  });

  it("DOES report +0 vs -0 as a change (Object.is is strict)", () => {
    // `Object.is(+0, -0)` returns false — the two zeros are
    // distinct under Object.is. Worth pinning so a refactor that
    // switches to `===` (which would treat them as equal)
    // surfaces here.
    const out = summarizeDiff({ x: +0 }, { x: -0 });
    expect(out.totalChanges).toBe(1);
  });
});
