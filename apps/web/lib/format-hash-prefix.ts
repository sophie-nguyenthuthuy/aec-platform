/**
 * File hash prefix display (cycle PP1, TS half).
 *
 * Format a hex digest as a short display prefix mimicking
 * `git log --oneline`. Used by file attachment displays, audit
 * row resource hashes (when the resource is content-addressed),
 * and the Slack alert digest's file reference.
 *
 *   formatHashPrefix(digest, length)  — "a1b2c3d…" or ""
 *   MIN_HASH_PREFIX_LENGTH            — 4
 *   MAX_HASH_PREFIX_LENGTH            — 64
 *   DEFAULT_HASH_PREFIX_LENGTH        — 7 (matches git default)
 *   ELLIPSIS                          — "…" (U+2026)
 *
 * Pure TS. Mirrors `apps/api/services/format_hash_prefix.py`.
 *
 * Pinned invariants:
 *   * Lowercased on output.
 *   * Whitespace + outer quotes stripped on input.
 *   * Non-hex → "" (surfaces malformed input).
 *   * Length out of [MIN, MAX] → "" (NOT clamped — surfaces config bug).
 *   * Ellipsis is U+2026 single char (NOT three dots).
 *   * Cross-language byte-for-byte parity.
 */


export const MIN_HASH_PREFIX_LENGTH = 4;
export const MAX_HASH_PREFIX_LENGTH = 64;
export const DEFAULT_HASH_PREFIX_LENGTH = 7;


/** Unicode horizontal ellipsis (U+2026). Single char (NOT three
 *  ASCII dots). Pin so a refactor that swaps to `...` would
 *  surface in the parity test. */
export const ELLIPSIS = "…";


const _HEX_RE = /^[0-9a-f]+$/;


/**
 * Format a hex digest as a short prefix with ellipsis suffix.
 *
 *   * formatHashPrefix("a1b2c3d4e5f6")        → "a1b2c3d…"
 *   * formatHashPrefix("A1B2C3D4E5F6")        → "a1b2c3d…"  (lowercased)
 *   * formatHashPrefix("a1b2c3d4e5f6", 4)     → "a1b2…"
 *   * formatHashPrefix("a1b2c3", 7)           → "a1b2c3"   (no ellipsis, full)
 *   * formatHashPrefix("not-hex")             → ""
 *   * formatHashPrefix(null)                  → ""
 *   * formatHashPrefix("a1b2c3", 3)           → ""         (below MIN)
 *   * formatHashPrefix("a1b2c3", 65)          → ""         (above MAX)
 */
export function formatHashPrefix(
  digest: string | null | undefined,
  length: number = DEFAULT_HASH_PREFIX_LENGTH,
): string {
  if (!digest) return "";
  if (length < MIN_HASH_PREFIX_LENGTH || length > MAX_HASH_PREFIX_LENGTH) {
    return "";
  }

  let cleaned = digest.trim();

  // Strip outer matching quotes (both `"` and `'`).
  if (
    (cleaned.startsWith('"') && cleaned.endsWith('"')) ||
    (cleaned.startsWith("'") && cleaned.endsWith("'"))
  ) {
    cleaned = cleaned.slice(1, -1);
  }

  cleaned = cleaned.toLowerCase();

  if (!_HEX_RE.test(cleaned)) return "";

  if (cleaned.length <= length) return cleaned;
  return cleaned.slice(0, length) + ELLIPSIS;
}
