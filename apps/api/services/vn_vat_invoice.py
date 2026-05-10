"""VN VAT invoice number validator (cycle AAA3).

Vietnamese tax invoice numbers per Decree 123/2020/NĐ-CP.
Format: `<series>/<sequence>` where:

  * series   — 6-8 alphanumeric uppercase chars (e.g. `C25TAA`)
  * sequence — 7-digit zero-padded number (e.g. `0000123`)

Example: `C25TAA/0000123`.

  parse_invoice_number(input)            — InvoiceNumber or None
  is_valid_invoice_number(input)         — bool
  format_invoice_number(invoice)         — canonical string
  next_invoice_number(series, last_seq)  — InvoiceNumber
  InvoiceSequenceExhausted               — Exception at MAX

Pinned invariants:
  * Series is `[A-Z0-9]{6,8}` (uppercase only — pin against
    case-mixed series; tax authority assigns canonical
    uppercase).
  * Sequence is 1..9999999 (7 digits zero-padded).
  * Slash `/` separator only (no hyphen / dash variant).
  * Whitespace stripped on parse.
  * Sequence 0 REJECTED (sequence starts at 1).
  * Sequence overflow at MAX_SEQUENCE raises
    `InvoiceSequenceExhausted`.

Echoes PP2's project-code zero-padded sequence pattern.

Pure stdlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SERIES_LENGTH_MIN = 6
SERIES_LENGTH_MAX = 8
SEQUENCE_LENGTH = 7
MAX_SEQUENCE = 9_999_999  # 7 nines


_SERIES_RE = re.compile(r"^[A-Z0-9]{6,8}$")
_SEQUENCE_RE = re.compile(r"^\d{1,7}$")
_WHITESPACE_RE = re.compile(r"\s+")


class InvoiceSequenceExhausted(Exception):
    """Raised when sequence exceeds MAX_SEQUENCE for a series."""


@dataclass(frozen=True)
class InvoiceNumber:
    """Parsed invoice number."""

    series: str
    sequence: int  # in [1, MAX_SEQUENCE]


def parse_invoice_number(input_str: str | None) -> InvoiceNumber | None:
    """Parse a VN VAT invoice number.

    Accepts:
      * Canonical: `C25TAA/0000123`
      * Sequence non-zero-padded: `C25TAA/123` (canonicalize via format).
      * Whitespace anywhere (stripped).

    Rejects:
      * Series too short / long / lowercase / non-alphanumeric.
      * Sequence non-numeric / zero / over MAX.
      * Wrong separator (only `/`).
    """
    if not input_str:
        return None
    cleaned = _WHITESPACE_RE.sub("", input_str)
    if "/" not in cleaned:
        return None
    series, _, seq_str = cleaned.partition("/")
    if not _SERIES_RE.match(series):
        return None
    if not _SEQUENCE_RE.match(seq_str):
        return None
    sequence = int(seq_str)
    if sequence < 1 or sequence > MAX_SEQUENCE:
        return None
    return InvoiceNumber(series=series, sequence=sequence)


def is_valid_invoice_number(input_str: str | None) -> bool:
    """True iff `parse_invoice_number(input)` returns non-None."""
    return parse_invoice_number(input_str) is not None


def format_invoice_number(invoice: InvoiceNumber) -> str:
    """Format an invoice with canonical zero-padded sequence."""
    return f"{invoice.series}/{invoice.sequence:0{SEQUENCE_LENGTH}d}"


def next_invoice_number(series: str, last_seq: int) -> InvoiceNumber:
    """Return the next invoice number in `series`.

    Raises:
      * ValueError if `series` is malformed or `last_seq < 0`.
      * InvoiceSequenceExhausted if `last_seq + 1 > MAX_SEQUENCE`.
    """
    if not _SERIES_RE.match(series):
        raise ValueError(f"invalid series: {series!r}")
    if last_seq < 0:
        raise ValueError(f"last_seq must be >= 0, got {last_seq}")
    next_seq = last_seq + 1
    if next_seq > MAX_SEQUENCE:
        raise InvoiceSequenceExhausted(f"Series {series!r} exhausted (max {MAX_SEQUENCE})")
    return InvoiceNumber(series=series, sequence=next_seq)
