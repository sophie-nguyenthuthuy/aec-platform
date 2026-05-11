"""VN address abbreviation expander (cycle WW2).

Expand common VN address abbreviations into canonical form.
Today the address normalizer pipeline expands inline; the
audit row's address-impact detector duplicates the logic.
This module is the single source of truth.

  expand_abbreviations(text)  — expanded canonical text

Composes with MM1's `format_address_vn` — typical pipeline:

    raw = "123 Lê Lợi, P.Bến Nghé, Q.1, TP.HCM"
    expanded = expand_abbreviations(raw)
    # → "123 Lê Lợi, Phường Bến Nghé, Quận 1, Thành phố Hồ Chí Minh"

Closed abbreviation map:
  * `TP.HCM` / `TPHCM` / `TP. HCM` → "Thành phố Hồ Chí Minh"
  * `TP.`  → "Thành phố "  (city)
  * `TT.`  → "Thị trấn "   (town)
  * `Q.`   → "Quận "       (urban district)
  * `P.`   → "Phường "     (urban ward)
  * `H.`   → "Huyện "      (rural district)
  * `X.`   → "Xã "         (rural commune)

Pinned invariants:
  * Case-insensitive matching.
  * Word-boundary anchored (so `BQ.1` doesn't expand).
  * Compound abbreviations (TP.HCM) processed BEFORE singles
    (TP.) — pin order so HCM doesn't end up as bare "HCM".
  * Idempotent: `expand(expand(x)) == expand(x)`.
  * Non-abbreviated text passed through unchanged.
  * None / empty → "".

Pure stdlib.
"""

from __future__ import annotations

import re

_FLAGS = re.IGNORECASE


# Compound first (TP.HCM beats TP.+HCM).
_COMPOUND_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bTP\.\s*HCM\b", _FLAGS), "Thành phố Hồ Chí Minh"),
    (re.compile(r"\bTPHCM\b", _FLAGS), "Thành phố Hồ Chí Minh"),
]


# Single-prefix rules. Order doesn't matter among these (they
# operate on different prefixes), but pinned for stability.
_SINGLE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bTP\.\s*", _FLAGS), "Thành phố "),
    (re.compile(r"\bTT\.\s*", _FLAGS), "Thị trấn "),
    (re.compile(r"\bQ\.\s*", _FLAGS), "Quận "),
    (re.compile(r"\bP\.\s*", _FLAGS), "Phường "),
    (re.compile(r"\bH\.\s*", _FLAGS), "Huyện "),
    (re.compile(r"\bX\.\s*", _FLAGS), "Xã "),
]


def expand_abbreviations(text: str | None) -> str:
    """Expand VN address abbreviations into canonical form.

    None / empty → "".
    """
    if not text:
        return ""

    result = text

    # Compound first so TP.HCM doesn't become "Thành phố HCM".
    for pattern, replacement in _COMPOUND_RULES:
        result = pattern.sub(replacement, result)

    for pattern, replacement in _SINGLE_RULES:
        result = pattern.sub(replacement, result)

    return result
