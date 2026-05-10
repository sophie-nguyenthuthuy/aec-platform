/**
 * WCAG color contrast helper (cycle OO1, TS-only).
 *
 * Compute WCAG 2.1 contrast ratio between two colors and check
 * AA/AAA compliance. Today the status-pill renderer, audit row
 * tone selector, and Slack alert tone helper each compute
 * inline with subtly different luminance formulae. This module
 * is the single source of truth.
 *
 *   contrastRatio(fg, bg)            — WCAG ratio in [1.0, 21.0]
 *   meetsAA(fg, bg, isLargeText)     — bool
 *   meetsAAA(fg, bg, isLargeText)    — bool
 *   WCAG_AA_NORMAL  / WCAG_AA_LARGE  — 4.5 / 3.0
 *   WCAG_AAA_NORMAL / WCAG_AAA_LARGE — 7.0 / 4.5
 *
 * Frontend-only — color contrast is a render-tier concern.
 *
 * Pinned invariants:
 *   * Relative-luminance per WCAG formula:
 *     - sRGB normalize to [0, 1]
 *     - linear gamma: cs <= 0.03928 → cs/12.92, else ((cs+0.055)/1.055)^2.4
 *     - weighted: 0.2126 R + 0.7152 G + 0.0722 B
 *   * Contrast ratio: (L_lighter + 0.05) / (L_darker + 0.05)
 *   * Symmetric: contrastRatio(a, b) === contrastRatio(b, a).
 *   * Black-on-white = 21.0 (max); same-color = 1.0 (min).
 *   * 3-char hex shorthand `#abc` expanded to `#aabbcc`.
 *   * Optional `#` prefix; case-insensitive.
 *   * Invalid input → 1.0 (worst, fails everything — defensive
 *     against silently permissive defaults).
 */


export const WCAG_AA_NORMAL = 4.5;
export const WCAG_AA_LARGE = 3.0;
export const WCAG_AAA_NORMAL = 7.0;
export const WCAG_AAA_LARGE = 4.5;


interface RGB {
  r: number;
  g: number;
  b: number;
}


function _parseHex(hex: string): RGB | null {
  let s = hex.trim();
  if (!s) return null;
  if (s.startsWith("#")) s = s.slice(1);
  s = s.toLowerCase();
  // 3-char shorthand `abc` → `aabbcc`.
  if (s.length === 3) {
    s = s[0]! + s[0]! + s[1]! + s[1]! + s[2]! + s[2]!;
  }
  if (s.length !== 6) return null;
  if (!/^[0-9a-f]{6}$/.test(s)) return null;
  return {
    r: parseInt(s.slice(0, 2), 16),
    g: parseInt(s.slice(2, 4), 16),
    b: parseInt(s.slice(4, 6), 16),
  };
}


function _channelToLinear(c: number): number {
  const cs = c / 255;
  if (cs <= 0.03928) return cs / 12.92;
  return Math.pow((cs + 0.055) / 1.055, 2.4);
}


function _relativeLuminance(rgb: RGB): number {
  const r = _channelToLinear(rgb.r);
  const g = _channelToLinear(rgb.g);
  const b = _channelToLinear(rgb.b);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}


/**
 * Compute WCAG 2.1 contrast ratio between two colors.
 *
 * Returns a ratio in [1.0, 21.0]:
 *   * 1.0 = same color (no contrast).
 *   * 21.0 = black on white (max contrast).
 *
 * Invalid input (null, malformed hex) → 1.0 (worst, fails
 * everything — defensive default).
 */
export function contrastRatio(
  fgHex: string | null | undefined,
  bgHex: string | null | undefined,
): number {
  if (!fgHex || !bgHex) return 1.0;
  const fg = _parseHex(fgHex);
  const bg = _parseHex(bgHex);
  if (!fg || !bg) return 1.0;
  const fgLum = _relativeLuminance(fg);
  const bgLum = _relativeLuminance(bg);
  const lighter = Math.max(fgLum, bgLum);
  const darker = Math.min(fgLum, bgLum);
  return (lighter + 0.05) / (darker + 0.05);
}


/**
 * True iff the FG/BG pair meets WCAG 2.1 AA contrast.
 *
 *   * Normal text: ratio >= 4.5
 *   * Large text:  ratio >= 3.0
 */
export function meetsAA(
  fgHex: string | null | undefined,
  bgHex: string | null | undefined,
  isLargeText: boolean = false,
): boolean {
  const ratio = contrastRatio(fgHex, bgHex);
  return ratio >= (isLargeText ? WCAG_AA_LARGE : WCAG_AA_NORMAL);
}


/**
 * True iff the FG/BG pair meets WCAG 2.1 AAA contrast.
 *
 *   * Normal text: ratio >= 7.0
 *   * Large text:  ratio >= 4.5
 */
export function meetsAAA(
  fgHex: string | null | undefined,
  bgHex: string | null | undefined,
  isLargeText: boolean = false,
): boolean {
  const ratio = contrastRatio(fgHex, bgHex);
  return ratio >= (isLargeText ? WCAG_AAA_LARGE : WCAG_AAA_NORMAL);
}
