"""Vietnamese tax ID (Mã số thuế / MST) validator (cycle EE2).

VN MST format:
  * Core: 10 digits, last digit is a checksum.
  * Optional branch suffix: hyphen + 3 digits (e.g. `-001` for
    a sub-unit / branch office).

Used by:
  * The org-create endpoint validator (rejects malformed MST
    with HTTP 422 before the row is persisted).
  * The invoice template's MST line.
  * The audit row's "tax-affected change" detector (some
    actions emit different audit shapes when the org's MST is
    legally significant).

  parse_mst(input)         — canonical form or None
  is_valid_mst(input)      — bool
  _compute_check_digit(d9) — int 0-9 (10 → 0 per VN convention)

Checksum algorithm: weighted-sum mod 11. Weights for digits 0..8
are (31, 29, 23, 19, 17, 13, 7, 5, 3). Check digit = 10 - (sum mod
11). If the result is >= 10, the MST is invalid in the strict
sense; this implementation maps that case to 0 (matching the
official validator's fallback).

Pure stdlib.
"""

from __future__ import annotations

import re

# Per-position weights for the MST checksum. Pin so a refactor
# that flips two weights silently breaks every existing
# pre-validated MST in the DB.
_MST_WEIGHTS: tuple[int, ...] = (31, 29, 23, 19, 17, 13, 7, 5, 3)


# Strict structural regex: 10 digits, optional `-XXX` branch suffix.
_MST_RE = re.compile(r"^(\d{10})(-\d{3})?$")


# Strip ANY whitespace inside the input on parse — users paste
# from PDFs and contracts which often contain spaces.
_WHITESPACE_RE = re.compile(r"\s+")


def _compute_check_digit(nine_digits: str) -> int:
    """Compute the 10th (checksum) digit from the first 9.

    Returns 0-9. The strict algorithm produces 0-10; the value
    10 maps to 0 per the official VN validator's fallback (so
    `_compute_check_digit("100000004") == 0`, not 10).
    """
    s = sum(int(d) * w for d, w in zip(nine_digits, _MST_WEIGHTS, strict=True))
    check = 10 - (s % 11)
    if check >= 10:
        return 0
    return check


def _verify_checksum(ten_digits: str) -> bool:
    """True iff the 10th digit matches the checksum of the first 9."""
    return _compute_check_digit(ten_digits[:9]) == int(ten_digits[9])


def parse_mst(input_str: str | None) -> str | None:
    """Parse an MST string and return canonical form or None.

    Canonical forms:
      * `"0123456787"`     — 10-digit core only.
      * `"0123456787-001"` — core + branch suffix.

    Accepts:
      * Plain canonical form.
      * Whitespace anywhere in the input (stripped on parse).

    Rejects:
      * None / empty / non-numeric.
      * Wrong length (not 10 / not 14 with hyphen).
      * Branch suffix not exactly 3 digits.
      * Failed checksum.
    """
    if input_str is None or input_str == "":
        return None
    cleaned = _WHITESPACE_RE.sub("", input_str)
    if not cleaned:
        return None
    m = _MST_RE.match(cleaned)
    if not m:
        return None
    core = m.group(1)
    if not _verify_checksum(core):
        return None
    return cleaned


def is_valid_mst(input_str: str | None) -> bool:
    """True iff `parse_mst(input)` returns a non-None canonical form."""
    return parse_mst(input_str) is not None
