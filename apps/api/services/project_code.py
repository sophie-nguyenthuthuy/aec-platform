"""Project code generator (cycle PP2).

Generate a unique project code from an org slug + a "taken set"
of existing codes. Today the project create endpoint generates
codes inline with subtly different prefix derivation. This
module is the single source of truth.

  generate_project_code(org_slug, taken)  — "ACME-001" or raises
  ProjectCodeExhausted                    — Exception when capped
  MAX_PROJECT_SEQUENCE                    — 999 (3-digit cap)
  PROJECT_PREFIX_LENGTH                   — 4 chars from slug

Composes with CC3's `canonical_slug` for org-slug normalization
(ASCII fold + lowercase via BB3 indirectly).

Pinned invariants:
  * Format: `<PREFIX>-<NNN>` where prefix is uppercase derived,
    NNN is 3-digit zero-padded sequence.
  * Lowest unused number returned (NOT next-after-max — pin so
    deleted-then-recreated codes get reused).
  * Sequence starts at 001.
  * Cap at 999 → raise `ProjectCodeExhausted`.
  * Empty org_slug or one that canonicalizes to empty → ValueError.
  * Existing codes outside the prefix range ignored.

Pure stdlib + CC3.
"""

from __future__ import annotations

from services.canonical_slug import canonical_slug

MAX_PROJECT_SEQUENCE = 999
PROJECT_PREFIX_LENGTH = 4


class ProjectCodeExhausted(Exception):
    """Raised when no more sequences are available for the prefix."""


def _derive_prefix(org_slug: str) -> str:
    """Derive a project-code prefix from an org slug.

    Algorithm:
      1. Canonicalize via CC3's `canonical_slug` (handles VN
         diacritics + lowercase + non-alphanum collapse).
      2. Strip hyphens.
      3. Uppercase.
      4. Take first PROJECT_PREFIX_LENGTH chars.

    Returns "" for inputs that canonicalize to empty.
    """
    if not org_slug:
        return ""
    canonical = canonical_slug(org_slug)
    if not canonical:
        return ""
    alphanum = canonical.replace("-", "").upper()
    if not alphanum:
        return ""
    return alphanum[:PROJECT_PREFIX_LENGTH]


def generate_project_code(org_slug: str, taken: set[str]) -> str:
    """Generate a unique project code.

    Returns `<PREFIX>-<NNN>` where PREFIX is derived from
    `org_slug` and NNN is the lowest 3-digit sequence not in
    `taken`.

    Raises:
      * `ValueError` if org_slug is empty or canonicalizes to empty.
      * `ProjectCodeExhausted` if all sequences in [001, 999] are
        taken.
    """
    prefix = _derive_prefix(org_slug)
    if not prefix:
        raise ValueError(f"Cannot derive project-code prefix from org_slug: {org_slug!r}")

    for n in range(1, MAX_PROJECT_SEQUENCE + 1):
        candidate = f"{prefix}-{n:03d}"
        if candidate not in taken:
            return candidate

    raise ProjectCodeExhausted(f"Project code sequence exhausted for prefix {prefix!r} (max {MAX_PROJECT_SEQUENCE})")
