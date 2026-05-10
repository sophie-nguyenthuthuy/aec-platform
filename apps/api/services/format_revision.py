"""Estimate revision number formatter (cycle BBB2, Python half).

Server-side mirror of `apps/web/lib/format-revision.ts`. Used by:

  * The audit CSV / pinned-export columns where revision-string
    columns appear (estimate.update, change_order.update, etc).
  * The PDF export's revision badge.
  * The email digest's "revised since you last looked" link text.

  RevisionNumber               — frozen dataclass
  parse_revision_number(input) — RevisionNumber | None
  format_revision_number(rev)  — canonical string
  is_valid_revision_number(s)  — bool
  next_revision(rev)           — RevisionNumber

Format: `<PREFIX>-<YYYY>-<NNN>` or `<PREFIX>-<YYYY>-<NNN>/rR`.
  * PREFIX: 2-4 uppercase letters (no digits).
  * YYYY: 4-digit year in [2020, 2099].
  * NNN: 3-digit zero-padded sequence in [1, 999].
  * /rR: optional revision tag, lowercase `r`, R in [1, 999].

Pinned invariants:
  * Base (`revision=0`) renders WITHOUT `/r0` suffix.
  * Revised (`revision>=1`) renders WITH `/rN` suffix (N not padded).
  * Sequence MUST be in [1, 999]; sequence=0 → None on parse.
  * `/r0` explicitly REJECTED on parse (canonical base form omits
    the suffix; pin so a refactor that round-trips `/r0` to base
    surfaces here).
  * Round-trip stable: parse(format(rev)) == rev.
  * Cross-language byte-for-byte parity with TS half.

Pure stdlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

PREFIX_LENGTH_MIN = 2
PREFIX_LENGTH_MAX = 4
SEQUENCE_LENGTH = 3
MAX_SEQUENCE = 999
MAX_REVISION = 999
MIN_YEAR = 2020
MAX_YEAR = 2099


_REVISION_RE = re.compile(r"^([A-Z]{2,4})-(\d{4})-(\d{1,3})(?:/r(\d{1,3}))?$")


@dataclass(frozen=True)
class RevisionNumber:
    """Parsed revision number.

    `revision=0` means "base" (no /r suffix on output).
    """

    prefix: str
    year: int
    sequence: int  # in [1, MAX_SEQUENCE]
    revision: int  # in [0, MAX_REVISION]


def parse_revision_number(
    input_str: str | None,
) -> RevisionNumber | None:
    """Parse a revision number string.

    Accepts:
      * `EST-2026-001`           → revision=0
      * `EST-2026-001/r2`        → revision=2
      * `EST-2026-1`             → sequence=1 (non-padded ok)
      * Whitespace around (stripped).

    Rejects (returns None):
      * Lowercase prefix / prefix with digits.
      * Sequence 0.
      * `/r0` (canonical base omits the suffix).
      * Year outside [2020, 2099].
      * Sequence > 999, revision > 999.
      * Wrong separator (`_`, `.`).
    """
    if not input_str:
        return None
    s = input_str.strip()
    if not s:
        return None
    m = _REVISION_RE.match(s)
    if m is None:
        return None
    prefix = m.group(1)
    year = int(m.group(2))
    sequence = int(m.group(3))
    revision_str = m.group(4)

    if year < MIN_YEAR or year > MAX_YEAR:
        return None
    if sequence < 1 or sequence > MAX_SEQUENCE:
        return None

    revision = 0
    if revision_str is not None:
        revision = int(revision_str)
        # Pin: `/r0` is invalid (base form omits the suffix).
        if revision < 1 or revision > MAX_REVISION:
            return None

    return RevisionNumber(
        prefix=prefix,
        year=year,
        sequence=sequence,
        revision=revision,
    )


def format_revision_number(rev: RevisionNumber) -> str:
    """Format a revision number in canonical form.

    Raises ValueError on out-of-range inputs (format is the
    formatter's responsibility — fail loud rather than silently
    produce a malformed string).
    """
    if not re.fullmatch(r"[A-Z]{2,4}", rev.prefix):
        raise ValueError(f"invalid prefix: {rev.prefix!r}")
    if rev.year < MIN_YEAR or rev.year > MAX_YEAR:
        raise ValueError(f"year out of range: {rev.year}")
    if rev.sequence < 1 or rev.sequence > MAX_SEQUENCE:
        raise ValueError(f"sequence out of range: {rev.sequence}")
    if rev.revision < 0 or rev.revision > MAX_REVISION:
        raise ValueError(f"revision out of range: {rev.revision}")
    base = f"{rev.prefix}-{rev.year}-{rev.sequence:0{SEQUENCE_LENGTH}d}"
    if rev.revision == 0:
        return base
    return f"{base}/r{rev.revision}"


def is_valid_revision_number(input_str: str | None) -> bool:
    """True iff `parse_revision_number(input)` returns non-None."""
    return parse_revision_number(input_str) is not None


def next_revision(rev: RevisionNumber) -> RevisionNumber:
    """Return the next revision: increment by 1.

    Raises ValueError if at MAX_REVISION.
    """
    if rev.revision >= MAX_REVISION:
        raise ValueError(f"revision exhausted at {MAX_REVISION}")
    return replace(rev, revision=rev.revision + 1)
