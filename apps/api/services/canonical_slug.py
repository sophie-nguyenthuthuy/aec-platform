"""Slug canonicalizer (cycle CC3, Python half).

Server-side mirror of `apps/web/lib/canonical-slug.ts`. Used by:

  * The org create endpoint's slug auto-derivation (when the user
    hasn't typed an explicit slug).
  * The project create endpoint's slug auto-derivation.
  * The RFQ reference-code generator.
  * The audit row export's resource_id-to-slug fallback (so a
    deep link can be reconstructed even when only the human-
    readable name is recorded).

  canonical_slug(input)   — normalize a name to a URL-safe slug
  MAX_SLUG_LENGTH         — 64 (matches the API column length)

Algorithm:
  1. Strip Vietnamese diacritics (delegates to BB3
     `strip_vn_diacritics`, including the đ → d explicit fold).
  2. Lowercase.
  3. Replace any run of non-alphanumeric chars with single hyphen.
  4. Trim leading/trailing hyphens.
  5. Cap at MAX_SLUG_LENGTH (re-trim trailing hyphen if cap landed on one).

Idempotent: `canonical_slug(canonical_slug(x)) == canonical_slug(x)`.

Pure stdlib + the BB3 helper.
"""

from __future__ import annotations

import re

from services.strip_vn_diacritics import strip_vn_diacritics

# Cap matches the API's slug column length (`varchar(64)`). Pin
# so a refactor that bumps the column without updating this
# constant surfaces in the test (mismatched length would cause
# an API 422 on edge-case long inputs).
MAX_SLUG_LENGTH = 64


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_TRAILING_HYPHEN_RE = re.compile(r"-+$")


def canonical_slug(input_str: str | None) -> str:
    """Canonicalize a free-form name to a URL-safe slug.

      * "Hà Nội Construction Co."  → "ha-noi-construction-co"
      * "Foo  Bar"                 → "foo-bar"
      * "Foo!@#Bar"                → "foo-bar"
      * "ĐÔNG ANH"                 → "dong-anh"
      * "  Foo  "                  → "foo"
      * "Foo--Bar"                 → "foo-bar"
      * ""                         → ""
      * None                       → ""
      * "!!!"                      → "" (strips to empty)

    Idempotent: applying twice yields the same result.
    """
    if not input_str:
        return ""
    # Step 1: strip VN diacritics (handles đ → d).
    text = strip_vn_diacritics(input_str)
    # Step 2: lowercase.
    text = text.lower()
    # Step 3: collapse non-alphanumeric runs to single hyphen.
    text = _NON_ALNUM_RE.sub("-", text)
    # Step 4: trim leading/trailing hyphens.
    text = text.strip("-")
    # Step 5: cap at MAX_SLUG_LENGTH; re-trim trailing hyphen if
    # the cap landed on one.
    if len(text) > MAX_SLUG_LENGTH:
        text = _TRAILING_HYPHEN_RE.sub("", text[:MAX_SLUG_LENGTH])
    return text
