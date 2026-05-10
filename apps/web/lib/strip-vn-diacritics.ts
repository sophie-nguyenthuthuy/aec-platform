/**
 * Vietnamese diacritic stripping for search (cycle BB3, TS half).
 *
 * The audit / project / member search pages match `"Hà Nội"`
 * against query `"ha noi"` via PostgreSQL's `unaccent` extension
 * server-side. The frontend autocomplete needs the same
 * normalisation client-side so typeahead fuzzy-matches before
 * the server round-trip.
 *
 *   stripVNDiacritics(text)  — ASCII-folded form
 *
 * Critical: `đ` / `Đ` get folded to `d` / `D` explicitly. NFD
 * decomposition does NOT split these — they're a Vietnamese-
 * specific case that babel/unaccent extensions handle out of
 * band but Unicode normalisation alone misses.
 *
 * Pure TS, no React, no DOM. Mirrors
 * `apps/api/services/strip_vn_diacritics.py`.
 */


/**
 * Strip Vietnamese diacritics from a string. Returns ASCII-folded
 * text suitable for case-insensitive comparison.
 *
 *   * "Hà Nội"          → "Ha Noi"
 *   * "Đà Nẵng"         → "Da Nang"
 *   * "Trần Hưng Đạo"   → "Tran Hung Dao"
 *   * "Việt Nam"        → "Viet Nam"
 *   * ""                → ""
 *   * null / undefined  → ""
 *
 * Algorithm:
 *   1. Replace `đ`/`Đ` with `d`/`D` (NFD doesn't decompose these).
 *   2. NFD-normalise — splits accented chars into base + combining mark.
 *   3. Strip combining marks (\p{M}).
 *
 * Idempotent: running twice yields the same result.
 */
export function stripVNDiacritics(text: string | null | undefined): string {
  if (text === null || text === undefined) return "";
  // Step 1: explicit đ/Đ replacement (NFD doesn't decompose them).
  let result = text.replace(/đ/g, "d").replace(/Đ/g, "D");
  // Step 2 + 3: NFD decompose, then strip combining marks.
  result = result.normalize("NFD").replace(/\p{M}/gu, "");
  return result;
}
