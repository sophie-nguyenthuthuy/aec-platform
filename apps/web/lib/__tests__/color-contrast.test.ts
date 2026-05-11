/**
 * WCAG color contrast helper (cycle OO1).
 *
 * Pinned seams:
 *   1. Black/white max ratio = 21.0.
 *   2. Same-color min ratio = 1.0.
 *   3. Symmetric: contrastRatio(a, b) === contrastRatio(b, a).
 *   4. WCAG_AA_NORMAL = 4.5; AA_LARGE = 3.0.
 *   5. WCAG_AAA_NORMAL = 7.0; AAA_LARGE = 4.5.
 *   6. 3-char hex shorthand expanded.
 *   7. Optional `#` prefix; case-insensitive.
 *   8. Invalid input → 1.0 (defensive worst).
 */

import { describe, expect, it } from "vitest";

import {
  WCAG_AAA_LARGE,
  WCAG_AAA_NORMAL,
  WCAG_AA_LARGE,
  WCAG_AA_NORMAL,
  contrastRatio,
  meetsAA,
  meetsAAA,
} from "../color-contrast";


// ---------- Constants ----------


describe("WCAG thresholds", () => {
  it("AA normal = 4.5", () => {
    expect(WCAG_AA_NORMAL).toBe(4.5);
  });

  it("AA large = 3.0", () => {
    expect(WCAG_AA_LARGE).toBe(3.0);
  });

  it("AAA normal = 7.0", () => {
    expect(WCAG_AAA_NORMAL).toBe(7.0);
  });

  it("AAA large = 4.5", () => {
    expect(WCAG_AAA_LARGE).toBe(4.5);
  });

  it("AAA stricter than AA at each text size", () => {
    expect(WCAG_AAA_NORMAL).toBeGreaterThan(WCAG_AA_NORMAL);
    expect(WCAG_AAA_LARGE).toBeGreaterThan(WCAG_AA_LARGE);
  });
});


// ---------- Boundary ratios ----------


describe("contrastRatio — boundaries", () => {
  it("black on white = 21.0 (maximum)", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21.0, 5);
  });

  it("white on black = 21.0 (symmetric maximum)", () => {
    expect(contrastRatio("#FFFFFF", "#000000")).toBeCloseTo(21.0, 5);
  });

  it("same color = 1.0 (minimum)", () => {
    expect(contrastRatio("#FFFFFF", "#FFFFFF")).toBeCloseTo(1.0, 5);
    expect(contrastRatio("#000000", "#000000")).toBeCloseTo(1.0, 5);
    expect(contrastRatio("#777777", "#777777")).toBeCloseTo(1.0, 5);
  });

  it("symmetric: contrastRatio(a, b) === contrastRatio(b, a)", () => {
    const a = contrastRatio("#FF0000", "#00FF00");
    const b = contrastRatio("#00FF00", "#FF0000");
    expect(a).toBeCloseTo(b, 10);
  });
});


// ---------- Realistic color pairs ----------


describe("contrastRatio — realistic pairs", () => {
  it("medium gray on white ≈ 4.48 (just below AA normal)", () => {
    // #777 = 0x77 = 119. Computed luminance ≈ 0.184.
    // ratio = 1.05 / 0.234 ≈ 4.48.
    const ratio = contrastRatio("#777777", "#FFFFFF");
    expect(ratio).toBeGreaterThan(4.4);
    expect(ratio).toBeLessThan(4.6);
  });

  it("light gray on white ≈ 3.0", () => {
    // #999 ≈ ratio 2.84
    const ratio = contrastRatio("#999999", "#FFFFFF");
    expect(ratio).toBeLessThan(3.0);
  });
});


// ---------- Hex format handling ----------


describe("contrastRatio — hex format", () => {
  it("3-char shorthand `#abc` expands to `#aabbcc`", () => {
    const short = contrastRatio("#000", "#FFF");
    const long = contrastRatio("#000000", "#FFFFFF");
    expect(short).toBeCloseTo(long, 10);
  });

  it("optional `#` prefix", () => {
    const withHash = contrastRatio("#000000", "#FFFFFF");
    const noHash = contrastRatio("000000", "FFFFFF");
    expect(noHash).toBeCloseTo(withHash, 10);
  });

  it("case-insensitive", () => {
    const lower = contrastRatio("#abcdef", "#FFFFFF");
    const upper = contrastRatio("#ABCDEF", "#FFFFFF");
    expect(lower).toBeCloseTo(upper, 10);
  });
});


// ---------- Invalid input ----------


describe("contrastRatio — invalid input", () => {
  it("returns 1.0 for null fg", () => {
    // Cardinal pin: invalid → 1.0 (worst). Defends against
    // silently permissive defaults.
    expect(contrastRatio(null, "#FFFFFF")).toBe(1.0);
  });

  it("returns 1.0 for null bg", () => {
    expect(contrastRatio("#000000", null)).toBe(1.0);
  });

  it("returns 1.0 for malformed hex", () => {
    expect(contrastRatio("#GGGGGG", "#FFFFFF")).toBe(1.0);
    expect(contrastRatio("#12345", "#FFFFFF")).toBe(1.0);  // 5 chars
    expect(contrastRatio("not-a-color", "#FFFFFF")).toBe(1.0);
  });

  it("returns 1.0 for empty input", () => {
    expect(contrastRatio("", "#FFFFFF")).toBe(1.0);
    expect(contrastRatio("   ", "#FFFFFF")).toBe(1.0);
  });
});


// ---------- meetsAA ----------


describe("meetsAA", () => {
  it("black on white passes (max ratio)", () => {
    expect(meetsAA("#000000", "#FFFFFF")).toBe(true);
  });

  it("medium gray on white fails AA normal", () => {
    expect(meetsAA("#777777", "#FFFFFF")).toBe(false);
  });

  it("medium gray on white passes AA large (3.0)", () => {
    expect(meetsAA("#777777", "#FFFFFF", true)).toBe(true);
  });

  it("invalid input fails (1.0 < 4.5)", () => {
    expect(meetsAA(null, "#FFFFFF")).toBe(false);
  });
});


// ---------- meetsAAA ----------


describe("meetsAAA", () => {
  it("black on white passes (max ratio)", () => {
    expect(meetsAAA("#000000", "#FFFFFF")).toBe(true);
  });

  it("medium gray on white fails AAA normal", () => {
    // ~4.48 < 7.0
    expect(meetsAAA("#777777", "#FFFFFF")).toBe(false);
  });

  it("medium gray on white fails AAA large too", () => {
    // ~4.48 < 4.5 (very close, just under)
    expect(meetsAAA("#777777", "#FFFFFF", true)).toBe(false);
  });

  it("AAA stricter than AA — same pair may pass AA fail AAA", () => {
    // #757575 ≈ ratio 4.61 — passes AA normal (4.5), fails AAA (7.0).
    const fg = "#757575";
    expect(meetsAA(fg, "#FFFFFF")).toBe(true);    // > 4.5
    expect(meetsAAA(fg, "#FFFFFF")).toBe(false);  // < 7.0
  });
});


// ---------- Tailwind tone sanity ----------


describe("realistic Tailwind palette pairs", () => {
  it("emerald-600 (#059669) on white fails AA normal but passes AA large", () => {
    // Cardinal pin: ratio ≈ 3.86. Fails 4.5 normal threshold,
    // passes 3.0 large threshold. Pin so a refactor that shifts
    // the formula constants would surface here.
    expect(meetsAA("#059669", "#FFFFFF")).toBe(false);
    expect(meetsAA("#059669", "#FFFFFF", true)).toBe(true);
  });

  it("amber-500 (#F59E0B) on white fails AA (low contrast)", () => {
    // Cardinal pin: amber-500 ratio ≈ 2.14, fails AA. The
    // status-pill component should pair amber with a dark FG,
    // NOT white.
    expect(meetsAA("#F59E0B", "#FFFFFF")).toBe(false);
  });

  it("rose-700 (#BE123C) on white passes AA normal", () => {
    // ratio ≈ 6.29 — passes AA normal but fails AAA normal.
    expect(meetsAA("#BE123C", "#FFFFFF")).toBe(true);
    expect(meetsAAA("#BE123C", "#FFFFFF")).toBe(false);
  });
});
