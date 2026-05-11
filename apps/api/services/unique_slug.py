"""Slugify uniqueness disambiguator (cycle UU1).

Generate a unique slug from a name + a taken-set of existing
slugs. Composes with CC3's `canonical_slug` so VN diacritics
and arbitrary input formatting are handled transparently.

Today the org-create flow, the project-create flow, and the
RFQ-create flow each implement disambiguation inline with subtly
different suffix conventions. This module is the single source
of truth.

  unique_slug(name, taken)  — base or "{base}-N" where N >= 2
  MAX_SLUG_SUFFIX           — 999 (cap before raise)
  SlugSuffixExhausted       — Exception raised at cap

Pinned invariants:
  * Base slug returned if not in `taken`.
  * First collision yields `-2` (NOT `-1` — pin against off-by-one).
  * LOWEST unused suffix used (defends against deleted-then-
    recreated holes never getting reused; matches PP2 pattern).
  * Cap at MAX_SLUG_SUFFIX raises `SlugSuffixExhausted`.
  * Empty name (or one canonicalizing to empty) raises ValueError.
  * Composes with CC3 — VN diacritics handled transparently.

Pure stdlib + CC3.
"""

from __future__ import annotations

from services.canonical_slug import canonical_slug

# Cap on the suffix counter. Past 999, the caller should
# reconsider their naming scheme — pin against silent
# overflow to 1000.
MAX_SLUG_SUFFIX = 999


class SlugSuffixExhausted(Exception):
    """Raised when no suffix in [2, MAX_SLUG_SUFFIX] is available."""


def unique_slug(name: str, taken: set[str]) -> str:
    """Generate a unique slug from `name`, disambiguating
    against `taken`.

    Returns the canonical slug if not taken; otherwise appends
    the lowest-unused integer suffix `-2`, `-3`, ...

    Raises:
      * ValueError if `name` is empty or canonicalizes to empty.
      * SlugSuffixExhausted if all suffixes in [2, MAX] are taken.
    """
    base = canonical_slug(name)
    if not base:
        raise ValueError(f"Cannot derive slug from name: {name!r}")

    if base not in taken:
        return base

    for suffix in range(2, MAX_SLUG_SUFFIX + 1):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate

    raise SlugSuffixExhausted(f"Slug suffix exhausted for base {base!r} (max {MAX_SLUG_SUFFIX})")
