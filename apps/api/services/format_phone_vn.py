"""Vietnamese phone number formatter (cycle BB2, Python half).

Server-side mirror of `apps/web/lib/format-phone-vn.ts`. Used by:

  * The org member API's request validator (rejects invalid
    phones with HTTP 422 before they reach the DB).
  * The notification preference seeder (canonicalises the phone
    to E.164 before storing).
  * The Slack alert renderer (formats phones in international
    form for cross-org admin pings).
  * The audit CSV / pinned-export columns where phone columns
    appear (e.g. `org.member.role_change`).

  format_phone_vn(input, fmt)   — render in one of three forms
  parse_phone_vn(input)         — canonical E.164 for storage
  is_valid_vn_mobile(input)     — bool

Mobile prefix allowlist: {3, 5, 7, 8, 9} per the Ministry of
Information & Communications 2018 reorg (the '1' prefix used
pre-2018 was retired). Out of scope: landlines.

Pure stdlib — no phonenumbers dep.
"""

from __future__ import annotations

import re
from typing import Literal

# Mobile prefix allowlist — first digit after the leading 0 (or
# after +84). Per VN MIC 2018 reorg. Pin so a refactor that adds
# e.g. '1' silently broadens the allowlist.
VN_MOBILE_PREFIXES: frozenset[str] = frozenset({"3", "5", "7", "8", "9"})


PhoneFormat = Literal["national", "international", "e164"]


_CLEAN_RE = re.compile(r"[\s\-().]")
_DIGITS_9 = re.compile(r"^\d{9}$")


def _clean(input_str: str) -> str:
    """Strip whitespace, hyphens, dots, parentheses. Leading +
    is preserved."""
    return _CLEAN_RE.sub("", input_str)


def _extract_9_digits(cleaned: str) -> str | None:
    """Return the 9-digit national number from a cleaned input,
    or None if invalid. The leading 0 / +84 / 84 is stripped."""
    if cleaned.startswith("+84"):
        rest = cleaned[3:]
    elif cleaned.startswith("84") and len(cleaned) == 11:
        # "84xxxxxxxxx" — 11 chars total, no leading + but length
        # matches country-coded form. Disambiguate from a hand-edited
        # number that happens to start with 84 (no valid VN mobile
        # would; 8 followed by 4 isn't in the allowlist anyway).
        rest = cleaned[2:]
    elif cleaned.startswith("0"):
        rest = cleaned[1:]
    else:
        return None
    if not _DIGITS_9.match(rest):
        return None
    if rest[0] not in VN_MOBILE_PREFIXES:
        return None
    return rest


def parse_phone_vn(input_str: str | None) -> str | None:
    """Parse a phone string to canonical E.164 (`+84XXXXXXXXX`).

    Accepts:
      * "0901234567"        → "+84901234567"
      * "+84901234567"      → "+84901234567"
      * "84901234567"       → "+84901234567"
      * "+84 90 123 4567"   → "+84901234567"
      * "0901 234 567"      → "+84901234567"

    Rejects:
      * None / "" / whitespace-only       → None
      * Wrong length                      → None
      * Non-mobile prefix (e.g. "0123…")  → None
      * Non-digit chars after cleaning    → None
    """
    if input_str is None or input_str == "":
        return None
    cleaned = _clean(input_str)
    if cleaned == "":
        return None
    rest = _extract_9_digits(cleaned)
    if rest is None:
        return None
    return f"+84{rest}"


def is_valid_vn_mobile(input_str: str | None) -> bool:
    """True iff `parse_phone_vn(input)` would return a non-None
    E.164. Used by the API request validator."""
    return parse_phone_vn(input_str) is not None


def format_phone_vn(
    input_str: str | None,
    fmt: PhoneFormat = "national",
) -> str:
    """Format a phone string in one of three display forms.

    Default is "national" — most common in Vietnamese UIs (the
    leading 0 is universally recognised).

    Invalid input → "" (no-op for chained renderers — calling
    code can do `format_phone_vn(member.phone)` without a None
    check).
    """
    e164 = parse_phone_vn(input_str)
    if e164 is None:
        return ""
    digits = e164[3:]  # 9 digits after "+84"
    if fmt == "e164":
        return e164
    if fmt == "international":
        # 2-3-4 grouping after "+84 ".
        return f"+84 {digits[:2]} {digits[2:5]} {digits[5:]}"
    # national: 4-3-3 grouping with leading 0.
    return f"0{digits[:3]} {digits[3:6]} {digits[6:]}"
