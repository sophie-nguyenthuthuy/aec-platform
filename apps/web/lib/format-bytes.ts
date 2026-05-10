/**
 * File size formatter (cycle DD3, TS half).
 *
 * Today the submittal attachment list, the audit export size
 * hint, the webhook payload size badge, and the dead-letter row
 * size column each format bytes inline with subtly different
 * unit thresholds (one uses 1024, another uses 1000; one shows
 * "1.5 MB", another "1,5 MB"). This module is the single source
 * of truth.
 *
 *   formatBytes(n, locale)  — render bytes in B / KB / MB / GB / TB
 *   BYTE_UNITS              — closed unit table
 *
 * Convention:
 *   * SI base 1000 (NOT 1024) — file managers across macOS /
 *     Windows / Linux now display SI-base sizes by default;
 *     pin so a refactor to "binary base" (1024, KiB) surfaces.
 *   * `locale='vi'` (default) uses comma decimal: "1,23 KB".
 *   * `locale='en'` uses dot decimal: "1.23 KB".
 *   * Bytes < 1000 render as "512 B" (no decimal — bytes are
 *     atomic, no fractional bytes).
 *   * TB is the cap: 8 PB renders as "8000.00 TB", not "8 PB".
 *     Pin: AEC platform doesn't expect PB-scale files; surfacing
 *     a 4-digit TB number is a "hey, something's wrong" signal.
 *
 * Pure TS, no React. Mirrors `apps/api/services/format_bytes.py`.
 */


/** Closed unit table. Order matters — promotion walks
 *  left-to-right at the SI 1000 boundary. Pin so a refactor
 *  that inserts e.g. 'KiB' surfaces here. */
export const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

export type ByteLocale = "vi" | "en";


/**
 * Format a byte count as a localized human-readable string.
 *
 *   * formatBytes(0)        → "0 B"
 *   * formatBytes(512)      → "512 B"
 *   * formatBytes(1500)     → "1,50 KB"      (vi default)
 *   * formatBytes(1500, "en") → "1.50 KB"
 *   * formatBytes(1_234_567)        → "1,23 MB"
 *   * formatBytes(1_234_567_890)    → "1,23 GB"
 *   * formatBytes(1_234_567_890_123) → "1,23 TB"
 *   * formatBytes(8e15)     → "8000,00 TB"   (PB capped at TB)
 *   * formatBytes(null)     → ""
 *   * formatBytes(NaN)      → ""
 *   * formatBytes(-1)       → ""             (negative is a bug)
 */
export function formatBytes(
  bytes: number | null | undefined,
  locale: ByteLocale = "vi",
): string {
  if (bytes === null || bytes === undefined) return "";
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 0) return "";
  if (bytes < 1000) return `${Math.floor(bytes)} B`;

  let value = bytes;
  let unitIdx = 0;
  while (value >= 1000 && unitIdx < BYTE_UNITS.length - 1) {
    value /= 1000;
    unitIdx++;
  }

  // Round to 2 decimals — half-toward-positive-infinity (matches
  // JS Math.round and the Python half's `_js_round_2dp`).
  const rounded = Math.round(value * 100) / 100;
  const decimal = locale === "vi" ? "," : ".";
  const text = rounded.toFixed(2).replace(".", decimal);
  return `${text} ${BYTE_UNITS[unitIdx]}`;
}
