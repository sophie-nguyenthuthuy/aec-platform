"""Vietnamese citizen ID (Căn cước công dân / CCCD) validator (cycle FF1).

VN CCCD format (12 digits, no checksum — unlike MST):

  Position 1-3 : Province code  (001-099 per VN administrative divisions)
  Position 4   : Gender/century code (0/1 = 20th c. M/F; 2/3 = 21st c. M/F)
  Position 5-6 : Year-of-birth  (2-digit, century resolved via pos 4)
  Position 7-12: Serial number  (6 digits, unique within the above prefix)

Used by:
  * Submittal author identity (the "submitted by" line).
  * Change-order signer identity (the contract counterparty).
  * The audit row's "human-affected event" detector — actions
    that emit a CCCD reference get a different tone class.

  parse_cccd(input)        — canonical 12-digit form or None
  is_valid_cccd(input)     — bool
  cccd_province_code(in)   — 3-digit province prefix or None
  cccd_birth_year(input)   — century-resolved 4-digit year or None

Pure stdlib. NOT TO BE CONFUSED WITH:
  * MST (10 digits, services.vn_tax_id) — corporate tax ID.
  * CMND (9 digits, pre-2016) — legacy citizen ID format,
    explicitly rejected here.
"""

from __future__ import annotations

import re

CCCD_LENGTH = 12


# Province codes are assigned per VN administrative divisions —
# the published table runs `001`-`099` (with gaps at currently
# unassigned codes). Pin the band edges; the gaps are the
# operator's problem to maintain in a separate enumeration if
# needed.
CCCD_PROVINCE_MIN = 1
CCCD_PROVINCE_MAX = 99


# Gender + century code at position 4:
#   0 = male,   20th century (1900-1999)
#   1 = female, 20th century
#   2 = male,   21st century (2000-2099)
#   3 = female, 21st century
# 4-9 are reserved for 22nd-25th centuries respectively. Pin the
# closed set so a refactor that accepts e.g. "4" for forward
# compatibility surfaces in review.
GENDER_CENTURY_CODES: frozenset[str] = frozenset({"0", "1", "2", "3"})


_CCCD_RE = re.compile(r"^\d{12}$")
_WHITESPACE_RE = re.compile(r"\s+")


def parse_cccd(input_str: str | None) -> str | None:
    """Parse a CCCD string and return canonical 12-digit form
    or None.

    Accepts:
      * Plain canonical 12 digits.
      * Whitespace anywhere in the input (stripped on parse).

    Rejects:
      * None / empty / non-numeric.
      * Wrong length (NOT 9 — pre-2016 CMND; NOT 10 — MST).
      * Province code outside [1, 99].
      * Gender/century code not in {0, 1, 2, 3}.
    """
    if input_str is None or input_str == "":
        return None
    cleaned = _WHITESPACE_RE.sub("", input_str)
    if not _CCCD_RE.match(cleaned):
        return None
    province = int(cleaned[:3])
    if not (CCCD_PROVINCE_MIN <= province <= CCCD_PROVINCE_MAX):
        return None
    if cleaned[3] not in GENDER_CENTURY_CODES:
        return None
    return cleaned


def is_valid_cccd(input_str: str | None) -> bool:
    """True iff `parse_cccd(input)` returns a non-None canonical."""
    return parse_cccd(input_str) is not None


def cccd_province_code(input_str: str | None) -> str | None:
    """Return the 3-digit province prefix, or None if invalid.

    Used by the audit row's per-province grouping (the platform-
    admin dashboard groups submittals by province for the
    cross-tenant view).
    """
    parsed = parse_cccd(input_str)
    return parsed[:3] if parsed is not None else None


def cccd_birth_year(input_str: str | None) -> int | None:
    """Return the century-resolved 4-digit birth year, or None
    if invalid.

      * gender/century code 0 or 1 → 19YY
      * gender/century code 2 or 3 → 20YY

    Examples:
      * cccd_birth_year("079092345678") → 1992
      * cccd_birth_year("079203456789") → 2003
    """
    parsed = parse_cccd(input_str)
    if parsed is None:
        return None
    gender_century = parsed[3]
    yy = int(parsed[4:6])
    century = 1900 if gender_century in {"0", "1"} else 2000
    return century + yy
