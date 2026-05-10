/**
 * Slug canonicalizer (cycle CC3, TS half).
 *
 * Used for org slugs, project slugs, RFQ reference codes —
 * anywhere a free-form Vietnamese name needs to become a stable
 * URL-safe identifier. Today the org-create form, the project
 * settings page, and the RFQ creation flow each canonicalize
 * inline with subtly different rules. This module is the single
 * source of truth.
 *
 *   canonicalSlug(input)  — normalize a name to a URL-safe slug
 *   MAX_SLUG_LENGTH       — 64 (matches the API column length)
 *
 * Algorithm:
 *   1. Strip Vietnamese diacritics (delegates to BB3
 *      `stripVNDiacritics`, including the đ → d explicit fold).
 *   2. Lowercase.
 *   3. Replace any run of non-alphanumeric chars with single hyphen.
 *   4. Trim leading/trailing hyphens.
 *   5. Cap at MAX_SLUG_LENGTH (re-trim trailing hyphen if cap landed on one).
 *
 * Idempotent: `canonicalSlug(canonicalSlug(x)) === canonicalSlug(x)`.
 *
 * Pure TS, no React. Mirrors `apps/api/services/canonical_slug.py`.
 */

import { stripVNDiacritics } from "./strip-vn-diacritics";


/** Cap matches the API's slug column length (`varchar(64)`).
 *  Pin so a refactor that bumps the column without updating
 *  this constant surfaces in the test (mismatched length would
 *  cause an API 422 on edge-case inputs). */
export const MAX_SLUG_LENGTH = 64;


/**
 * Canonicalize a free-form name to a URL-safe slug.
 *
 *   * "Hà Nội Construction Co."  → "ha-noi-construction-co"
 *   * "Foo  Bar"                 → "foo-bar"
 *   * "Foo!@#Bar"                → "foo-bar"
 *   * "ĐÔNG ANH"                 → "dong-anh"
 *   * "  Foo  "                  → "foo"
 *   * "Foo--Bar"                 → "foo-bar"
 *   * ""                         → ""
 *   * null / undefined           → ""
 *   * "!!!"                      → "" (strips to empty)
 *
 * Idempotent: applying twice yields the same result.
 */
export function canonicalSlug(input: string | null | undefined): string {
  if (!input) return "";
  // Step 1: strip VN diacritics (handles đ → d).
  let text = stripVNDiacritics(input);
  // Step 2: lowercase.
  text = text.toLowerCase();
  // Step 3: collapse non-alphanumeric runs to single hyphen.
  text = text.replace(/[^a-z0-9]+/g, "-");
  // Step 4: trim leading/trailing hyphens.
  text = text.replace(/^-+|-+$/g, "");
  // Step 5: cap at MAX_SLUG_LENGTH; re-trim trailing hyphen if
  // the cap landed on one (e.g. cutting "abc-def-ghi" at len=7
  // → "abc-def" via slice(0,7) which keeps the trailing "-" if
  // present).
  if (text.length > MAX_SLUG_LENGTH) {
    text = text.slice(0, MAX_SLUG_LENGTH).replace(/-+$/, "");
  }
  return text;
}
