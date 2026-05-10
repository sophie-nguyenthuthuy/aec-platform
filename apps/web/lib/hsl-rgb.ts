/**
 * HSL/RGB color converter (cycle SS3, TS half).
 *
 * Convert between HSL (hue/saturation/lightness) and RGB hex.
 * Today the chart palette generator, status-pill tint computer,
 * and org branding color picker each implement HSL/RGB inline.
 * This module is the single source of truth.
 *
 *   hslToRgbHex(h, s, l)    — "#abcdef" or ""
 *   rgbHexToHsl(hex)        — { h, s, l } or null
 *   HSL                     — interface { h, s, l }
 *
 * Pure TS. Mirrors `apps/api/services/hsl_rgb.py`.
 *
 * Pinned invariants:
 *   * H ∈ [0, 360); S, L ∈ [0, 1].
 *   * H out of range wraps via modulo (negative hue handled).
 *   * S/L out of range → "" / null (NOT clamped — surfaces
 *     config bugs).
 *   * Output hex lowercased with `#` prefix.
 *   * Round-trip RGB→HSL→RGB stable within ±1 RGB unit
 *     (HSL→RGB→HSL may drift slightly due to float quantization).
 *   * Cross-language byte-for-byte parity for the standard
 *     pure colors (red, green, blue, black, white, gray).
 */


export interface HSL {
  /** Hue in [0, 360). */
  h: number;
  /** Saturation in [0, 1]. */
  s: number;
  /** Lightness in [0, 1]. */
  l: number;
}


function _jsRound(x: number): number {
  return Math.floor(x + 0.5);
}


function _hueToRgb(p: number, q: number, t: number): number {
  if (t < 0) t += 1;
  if (t > 1) t -= 1;
  if (t < 1 / 6) return p + (q - p) * 6 * t;
  if (t < 1 / 2) return q;
  if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
  return p;
}


/**
 * Convert HSL to RGB hex string.
 *
 *   * hslToRgbHex(0, 1, 0.5)     → "#ff0000"  (pure red)
 *   * hslToRgbHex(120, 1, 0.5)   → "#00ff00"  (pure green)
 *   * hslToRgbHex(240, 1, 0.5)   → "#0000ff"  (pure blue)
 *   * hslToRgbHex(0, 0, 0)       → "#000000"  (black)
 *   * hslToRgbHex(0, 0, 1)       → "#ffffff"  (white)
 *   * hslToRgbHex(360, 1, 0.5)   → "#ff0000"  (hue wrap)
 *   * hslToRgbHex(NaN, 0.5, 0.5) → ""
 *   * hslToRgbHex(0, 1.5, 0.5)   → ""         (S out of range)
 */
export function hslToRgbHex(h: number, s: number, l: number): string {
  if (!Number.isFinite(h) || !Number.isFinite(s) || !Number.isFinite(l)) {
    return "";
  }
  if (s < 0 || s > 1 || l < 0 || l > 1) return "";

  // Normalize hue to [0, 360).
  let hue = h % 360;
  if (hue < 0) hue += 360;

  let r: number;
  let g: number;
  let b: number;

  if (s === 0) {
    r = g = b = l;
  } else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    const hNorm = hue / 360;
    r = _hueToRgb(p, q, hNorm + 1 / 3);
    g = _hueToRgb(p, q, hNorm);
    b = _hueToRgb(p, q, hNorm - 1 / 3);
  }

  const ri = _jsRound(r * 255);
  const gi = _jsRound(g * 255);
  const bi = _jsRound(b * 255);

  return (
    "#" +
    ri.toString(16).padStart(2, "0") +
    gi.toString(16).padStart(2, "0") +
    bi.toString(16).padStart(2, "0")
  );
}


/**
 * Convert RGB hex string to HSL.
 *
 *   * rgbHexToHsl("#ff0000")  → { h: 0, s: 1, l: 0.5 }
 *   * rgbHexToHsl("#00ff00")  → { h: 120, s: 1, l: 0.5 }
 *   * rgbHexToHsl("#000000")  → { h: 0, s: 0, l: 0 }
 *   * rgbHexToHsl("#ffffff")  → { h: 0, s: 0, l: 1 }
 *   * rgbHexToHsl("not-hex")  → null
 *   * rgbHexToHsl(null)       → null
 *
 * Accepts 3-char shorthand and optional `#` prefix
 * (consistent with OO1's hex parsing convention).
 */
export function rgbHexToHsl(hex: string | null | undefined): HSL | null {
  if (!hex) return null;
  let s = hex.trim();
  if (!s) return null;
  if (s.startsWith("#")) s = s.slice(1);
  s = s.toLowerCase();
  // 3-char shorthand.
  if (s.length === 3) {
    s = s[0]! + s[0]! + s[1]! + s[1]! + s[2]! + s[2]!;
  }
  if (s.length !== 6) return null;
  if (!/^[0-9a-f]{6}$/.test(s)) return null;

  const r = parseInt(s.slice(0, 2), 16) / 255;
  const g = parseInt(s.slice(2, 4), 16) / 255;
  const b = parseInt(s.slice(4, 6), 16) / 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;

  let h = 0;
  let sat = 0;
  if (max !== min) {
    const d = max - min;
    sat = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) {
      h = (g - b) / d + (g < b ? 6 : 0);
    } else if (max === g) {
      h = (b - r) / d + 2;
    } else {
      h = (r - g) / d + 4;
    }
    h /= 6;
  }

  return { h: h * 360, s: sat, l };
}
