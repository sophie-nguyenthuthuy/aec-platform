"""VN bank account number formatter (cycle HH2, Python half).

Server-side mirror of `apps/web/lib/format-bank-account.ts`. Used
by the invoice email template, the audit row's bank-account
column rendering, and the org payment-settings validator.

  format_bank_account(input)   — "1234 5678 9012 3456"
  parse_bank_account(input)    — canonical digits or None
  bank_display_name(code)      — registry lookup
  VN_BANKS                     — closed bank-code → display name

Pure stdlib.
"""

from __future__ import annotations

import re

# Closed registry of major Vietnamese banks. Pin via test —
# adding a bank requires consulting the BIN registry.
VN_BANKS: dict[str, str] = {
    "VCB": "Vietcombank",
    "TCB": "Techcombank",
    "BIDV": "BIDV",
    "ACB": "ACB",
    "MB": "MB Bank",
    "VIB": "VIB",
    "STB": "Sacombank",
    "TPB": "TPBank",
    "OCB": "OCB",
    "HDB": "HDBank",
    "EXB": "Eximbank",
    "VPB": "VPBank",
}


# Length band — legacy 8-digit accounts at older banks; modern
# long-form accounts up to 19 digits.
MIN_BANK_ACCOUNT_LENGTH = 8
MAX_BANK_ACCOUNT_LENGTH = 19


_CLEAN_RE = re.compile(r"[\s\-]")
_DIGITS_RE = re.compile(r"^\d+$")


def parse_bank_account(input_str: str | None) -> str | None:
    """Parse a bank account string and return canonical digits or None.

    Accepts whitespace and hyphens (stripped). Rejects non-digit
    characters and out-of-range lengths.
    """
    if input_str is None or input_str == "":
        return None
    cleaned = _CLEAN_RE.sub("", input_str)
    if not cleaned:
        return None
    if not _DIGITS_RE.match(cleaned):
        return None
    if len(cleaned) < MIN_BANK_ACCOUNT_LENGTH:
        return None
    if len(cleaned) > MAX_BANK_ACCOUNT_LENGTH:
        return None
    return cleaned


def format_bank_account(input_str: str | None) -> str:
    """Format a bank account in 4-digit right-aligned groups.

      * "12345678"             → "1234 5678"
      * "123456789"            → "1 2345 6789"
      * "12345678901"          → "123 4567 8901"
      * "1234567890123456"     → "1234 5678 9012 3456"
      * None / invalid         → ""

    Right-aligned: the LAST group always has 4 digits; the FIRST
    group has 1-4 depending on total length.
    """
    cleaned = parse_bank_account(input_str)
    if cleaned is None:
        return ""
    groups: list[str] = []
    i = len(cleaned)
    while i > 0:
        start = max(0, i - 4)
        groups.append(cleaned[start:i])
        i -= 4
    groups.reverse()
    return " ".join(groups)


def bank_display_name(code: str | None) -> str | None:
    """Look up a bank's display name by code (case-insensitive).

    Returns None for unknown codes.
    """
    if not code:
        return None
    return VN_BANKS.get(code.upper())
