/**
 * VND currency formatter (cycle AA1, TS half).
 *
 * Vietnamese-first per project convention: dot thousands
 * separator, `₫` suffix, no decimal places by default. Today the
 * estimate, change-order, dashboard, and quote views each format
 * VND inline with subtly different rules. This module is the
 * single source of truth.
 *
 *   formatVND(amount)  — `12.345.678 ₫`
 *   parseVND(input)    — `"12.345.678 ₫"` → `12345678`
 *
 * Pure TS, no React, no Intl ICU lookup (the conventions are
 * stable enough to inline). Mirrors `apps/api/services/format_vnd.py`.
 *
 * Rounding: half-toward-positive-infinity (JS `Math.round`). Pin
 * matches the Python half via `math.floor(x + 0.5)` so the same
 * fractional input formats identically across languages.
 */


/** Vietnamese đồng sign U+20AB. NOT 'đ' (lowercase d-stroke,
 *  used informally) and NOT 'VND' (text abbreviation). */
export const VND_SYMBOL = "₫";


/** Vietnamese convention is `.` for thousands. Mirrors Python
 *  half — a refactor that swaps to ',' would diverge from every
 *  Vietnamese government-issued financial document. */
export const VND_THOUSANDS_SEPARATOR = ".";


/** Vietnamese convention is `,` for decimal (`1,5` means 1.5).
 *  VND has no decimal in modern pricing, so this is exposed for
 *  callers that format other currencies via the same conventions. */
export const VND_DECIMAL_SEPARATOR = ",";


/**
 * Format a numeric amount as `12.345.678 ₫`.
 *
 *   * `null` / `undefined` / `NaN` / `Infinity` → "" (no-op for
 *     chained renderers — calling code can do
 *     `formatVND(row.amount)` without a null check).
 *   * Fractional input rounds to nearest integer (half-up). VND
 *     has no smaller unit in modern pricing.
 *   * Negative amounts get a leading `-` (no parentheses-style
 *     accounting format — pin Vietnamese convention).
 */
export function formatVND(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "";
  if (!Number.isFinite(amount)) return "";
  const rounded = Math.round(amount);
  const sign = rounded < 0 ? "-" : "";
  const abs = Math.abs(rounded).toString();
  const parts: string[] = [];
  for (let i = abs.length; i > 0; i -= 3) {
    parts.unshift(abs.slice(Math.max(0, i - 3), i));
  }
  return `${sign}${parts.join(VND_THOUSANDS_SEPARATOR)} ${VND_SYMBOL}`;
}


/**
 * Parse a VND-formatted string back to an integer.
 *
 * Round-trips `formatVND` output. Also accepts:
 *   * Plain integer strings: `"12345678"` → 12345678.
 *   * Lowercase `đ`: `"12.345.678 đ"` → 12345678 (informal).
 *   * Text `VND` suffix: `"12345678 VND"` → 12345678.
 *
 * Empty / null / undefined / non-numeric → null (graceful fallback
 * for hand-edited filter URLs).
 */
export function parseVND(input: string | null | undefined): number | null {
  if (input === null || input === undefined || input === "") return null;
  let cleaned = input.replace(VND_SYMBOL, "");
  cleaned = cleaned.replace(/đ|VND/gi, "");
  cleaned = cleaned.split(VND_THOUSANDS_SEPARATOR).join("");
  cleaned = cleaned.trim();
  if (cleaned === "") return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return null;
  return Math.trunc(n);
}
