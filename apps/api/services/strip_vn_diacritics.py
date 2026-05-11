"""Vietnamese diacritic stripping for search (cycle BB3, Python half).

Server-side mirror of `apps/web/lib/strip-vn-diacritics.ts`. Used
by the audit / project / member search endpoints when the
PostgreSQL `unaccent` extension isn't available (test envs, local
dev) and by the Slack alert digest's quick-search-link generator
(which needs the canonical form for URL fragments).

  strip_vn_diacritics(text)  — ASCII-folded form

Critical: `đ` / `Đ` get folded to `d` / `D` explicitly. Unicode
NFD decomposition does NOT split these — they're a Vietnamese-
specific case that PostgreSQL's `unaccent` handles out of band
but `unicodedata.normalize` alone misses.

Pure stdlib — no babel.localedata / unidecode dep.
"""

from __future__ import annotations

import unicodedata


def strip_vn_diacritics(text: str | None) -> str:
    """Strip Vietnamese diacritics from a string. Returns
    ASCII-folded text suitable for case-insensitive comparison.

      * "Hà Nội"          → "Ha Noi"
      * "Đà Nẵng"         → "Da Nang"
      * "Trần Hưng Đạo"   → "Tran Hung Dao"
      * "Việt Nam"        → "Viet Nam"
      * ""                → ""
      * None              → ""

    Algorithm:
      1. Replace `đ`/`Đ` with `d`/`D` (NFD doesn't decompose them).
      2. NFD-normalise — splits accented chars into base + combining mark.
      3. Filter out combining marks (Unicode category 'Mn').

    Idempotent: running twice yields the same result.
    """
    if text is None:
        return ""
    # Step 1: explicit đ/Đ replacement (NFD doesn't decompose them).
    result = text.replace("đ", "d").replace("Đ", "D")
    # Step 2: NFD decompose.
    nfd = unicodedata.normalize("NFD", result)
    # Step 3: filter out combining marks (category Mn = Nonspacing_Mark).
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")
