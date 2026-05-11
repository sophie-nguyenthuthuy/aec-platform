/**
 * HSL/RGB color converter (cycle SS3).
 *
 * Pinned seams:
 *   1. H wraps via modulo (handles >360 and negative).
 *   2. S/L out of range → "" / null (NOT clamped).
 *   3. Pure colors round-trip exactly: red/green/blue.
 *   4. Black/white/gray are achromatic (s=0).
 *   5. 3-char shorthand expanded.
 *   6. Invalid input → null / "".
 */

import { describe, expect, it } from "vitest";

import { type HSL, hslToRgbHex, rgbHexToHsl } from "../hsl-rgb";


// ---------- hslToRgbHex — pure colors ----------


describe("hslToRgbHex — pure colors", () => {
  it("red", () => {
    expect(hslToRgbHex(0, 1, 0.5)).toBe("#ff0000");
  });

  it("green", () => {
    expect(hslToRgbHex(120, 1, 0.5)).toBe("#00ff00");
  });

  it("blue", () => {
    expect(hslToRgbHex(240, 1, 0.5)).toBe("#0000ff");
  });

  it("yellow (60°)", () => {
    expect(hslToRgbHex(60, 1, 0.5)).toBe("#ffff00");
  });

  it("cyan (180°)", () => {
    expect(hslToRgbHex(180, 1, 0.5)).toBe("#00ffff");
  });

  it("magenta (300°)", () => {
    expect(hslToRgbHex(300, 1, 0.5)).toBe("#ff00ff");
  });
});


// ---------- hslToRgbHex — achromatic ----------


describe("hslToRgbHex — achromatic", () => {
  it("black (l=0)", () => {
    expect(hslToRgbHex(0, 0, 0)).toBe("#000000");
  });

  it("white (l=1)", () => {
    expect(hslToRgbHex(0, 0, 1)).toBe("#ffffff");
  });

  it("mid gray (l=0.5)", () => {
    expect(hslToRgbHex(0, 0, 0.5)).toBe("#808080");
  });
});


// ---------- hslToRgbHex — hue wrap ----------


describe("hslToRgbHex — hue wrapping", () => {
  it("360 wraps to 0 (red)", () => {
    expect(hslToRgbHex(360, 1, 0.5)).toBe("#ff0000");
  });

  it("720 wraps to 0", () => {
    expect(hslToRgbHex(720, 1, 0.5)).toBe("#ff0000");
  });

  it("negative hue wraps", () => {
    expect(hslToRgbHex(-120, 1, 0.5)).toBe("#0000ff");  // -120 = 240
  });
});


// ---------- hslToRgbHex — invalid ----------


describe("hslToRgbHex — invalid input", () => {
  it("NaN hue → ''", () => {
    expect(hslToRgbHex(Number.NaN, 0.5, 0.5)).toBe("");
  });

  it("Infinity hue → ''", () => {
    expect(hslToRgbHex(Number.POSITIVE_INFINITY, 0.5, 0.5)).toBe("");
  });

  it("S out of [0, 1] → ''", () => {
    // Cardinal pin: NOT clamped — surfaces config bugs.
    expect(hslToRgbHex(0, -0.1, 0.5)).toBe("");
    expect(hslToRgbHex(0, 1.1, 0.5)).toBe("");
  });

  it("L out of [0, 1] → ''", () => {
    expect(hslToRgbHex(0, 0.5, -0.1)).toBe("");
    expect(hslToRgbHex(0, 0.5, 1.1)).toBe("");
  });

  it("S boundary at 0", () => {
    expect(hslToRgbHex(0, 0, 0.5)).toBe("#808080");
  });

  it("S boundary at 1", () => {
    expect(hslToRgbHex(0, 1, 0.5)).toBe("#ff0000");
  });
});


// ---------- rgbHexToHsl ----------


describe("rgbHexToHsl — pure colors", () => {
  it("red", () => {
    const result = rgbHexToHsl("#ff0000");
    expect(result).not.toBeNull();
    expect(result!.h).toBeCloseTo(0, 5);
    expect(result!.s).toBeCloseTo(1, 5);
    expect(result!.l).toBeCloseTo(0.5, 5);
  });

  it("green", () => {
    const result = rgbHexToHsl("#00ff00");
    expect(result!.h).toBeCloseTo(120, 5);
    expect(result!.s).toBeCloseTo(1, 5);
  });

  it("blue", () => {
    const result = rgbHexToHsl("#0000ff");
    expect(result!.h).toBeCloseTo(240, 5);
    expect(result!.s).toBeCloseTo(1, 5);
  });
});


describe("rgbHexToHsl — achromatic", () => {
  it("black", () => {
    const result = rgbHexToHsl("#000000");
    expect(result).toEqual({ h: 0, s: 0, l: 0 });
  });

  it("white", () => {
    const result = rgbHexToHsl("#ffffff");
    expect(result).toEqual({ h: 0, s: 0, l: 1 });
  });

  it("gray has zero saturation", () => {
    const result = rgbHexToHsl("#808080");
    expect(result!.s).toBe(0);
  });
});


// ---------- rgbHexToHsl — input format ----------


describe("rgbHexToHsl — input format", () => {
  it("accepts 3-char shorthand", () => {
    const short = rgbHexToHsl("#f00");
    const long = rgbHexToHsl("#ff0000");
    expect(short).toEqual(long);
  });

  it("accepts no `#` prefix", () => {
    expect(rgbHexToHsl("ff0000")).toEqual(rgbHexToHsl("#ff0000"));
  });

  it("case-insensitive", () => {
    const upper = rgbHexToHsl("#FF0000");
    const lower = rgbHexToHsl("#ff0000");
    expect(upper).toEqual(lower);
  });

  it("strips whitespace", () => {
    expect(rgbHexToHsl("  #ff0000  ")).toEqual(rgbHexToHsl("#ff0000"));
  });
});


describe("rgbHexToHsl — invalid", () => {
  it("null", () => {
    expect(rgbHexToHsl(null)).toBeNull();
  });

  it("undefined", () => {
    expect(rgbHexToHsl(undefined)).toBeNull();
  });

  it("empty", () => {
    expect(rgbHexToHsl("")).toBeNull();
  });

  it("non-hex", () => {
    expect(rgbHexToHsl("not-a-hex")).toBeNull();
  });

  it("wrong length", () => {
    expect(rgbHexToHsl("#fff0")).toBeNull();  // 4 chars
    expect(rgbHexToHsl("#fffff")).toBeNull();  // 5 chars
  });
});


// ---------- Round-trip ----------


describe("round-trip RGB → HSL → RGB", () => {
  it("preserves pure red", () => {
    const hsl = rgbHexToHsl("#ff0000")!;
    expect(hslToRgbHex(hsl.h, hsl.s, hsl.l)).toBe("#ff0000");
  });

  it("preserves pure green", () => {
    const hsl = rgbHexToHsl("#00ff00")!;
    expect(hslToRgbHex(hsl.h, hsl.s, hsl.l)).toBe("#00ff00");
  });

  it("preserves black", () => {
    const hsl = rgbHexToHsl("#000000")!;
    expect(hslToRgbHex(hsl.h, hsl.s, hsl.l)).toBe("#000000");
  });

  it("preserves white", () => {
    const hsl = rgbHexToHsl("#ffffff")!;
    expect(hslToRgbHex(hsl.h, hsl.s, hsl.l)).toBe("#ffffff");
  });

  it("preserves arbitrary color within ±1 RGB unit", () => {
    // Float quantization may drift by 1 — pin tolerance.
    const inputs = ["#3a5c8e", "#fc7d12", "#4caf50"];
    for (const input of inputs) {
      const hsl = rgbHexToHsl(input)!;
      const round = rgbHexToHsl(hslToRgbHex(hsl.h, hsl.s, hsl.l))!;
      expect(Math.abs(round.h - hsl.h)).toBeLessThanOrEqual(1);
      expect(Math.abs(round.s - hsl.s)).toBeLessThanOrEqual(0.01);
      expect(Math.abs(round.l - hsl.l)).toBeLessThanOrEqual(0.01);
    }
  });
});
