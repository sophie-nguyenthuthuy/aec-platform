"""VN postal code validator (cycle OO2).

6-digit Vietnamese postal codes per Vietnam Post 2018 reform.
Pre-2018 5-digit codes explicitly REJECTED — pin so a migration
import that accepts both formats doesn't silently store legacy
codes.

  parse_postal_code(input)         — canonical or None
  is_valid_postal_code(input)      — bool
  postal_code_province_code(input) — 2-digit prefix or None
  POSTAL_CODE_LENGTH               — 6
  POSTAL_PROVINCE_MIN/MAX          — [01, 99]

Pinned invariants:
  * 6 digits exactly (NOT 5 — pre-2018 form rejected).
  * First 2 digits = province prefix in [01, 99] (matches FF1
    CCCD province band).
  * Whitespace stripped on parse.
  * Non-digit characters reject.

Pure stdlib.
"""

from __future__ import annotations

import re

POSTAL_CODE_LENGTH = 6


# Province prefix band — first 2 digits of postal code identify
# the province. Band [01, 99] matches the VN administrative
# divisions table (same band as FF1 CCCD).
POSTAL_PROVINCE_MIN = 1
POSTAL_PROVINCE_MAX = 99


_POSTAL_CODE_RE = re.compile(r"^\d{6}$")
_WHITESPACE_RE = re.compile(r"\s+")


def parse_postal_code(input_str: str | None) -> str | None:
    """Parse a VN postal code string and return canonical or None.

    Accepts:
      * Plain canonical 6 digits.
      * Whitespace anywhere in the input (stripped on parse).

    Rejects:
      * None / empty / non-numeric.
      * Wrong length (NOT 5 — pre-2018 CMND form).
      * Province prefix outside [01, 99].
    """
    if input_str is None or input_str == "":
        return None
    cleaned = _WHITESPACE_RE.sub("", input_str)
    if not _POSTAL_CODE_RE.match(cleaned):
        return None
    province = int(cleaned[:2])
    if not (POSTAL_PROVINCE_MIN <= province <= POSTAL_PROVINCE_MAX):
        return None
    return cleaned


def is_valid_postal_code(input_str: str | None) -> bool:
    """True iff `parse_postal_code` returns a non-None canonical."""
    return parse_postal_code(input_str) is not None


def postal_code_province_code(input_str: str | None) -> str | None:
    """Return the 2-digit province prefix, or None if invalid.

    Used by the audit row's per-province grouping (pairs with
    FF1's CCCD province grouping for the platform-admin
    cross-tenant view).
    """
    parsed = parse_postal_code(input_str)
    if parsed is None:
        return None
    return parsed[:2]
