"""HTTP Range header parser (cycle ZZ2).

Parse RFC 7233 `Range: bytes=START-END` headers for resumable
file downloads. Used by attachment download endpoints, audit
CSV resumable export, and the dead-letter dump endpoint.

  parse_range(header, total_size)  — Range or None
  Range                            — frozen dataclass: start/end/length

Supported forms:
  * Closed:     `bytes=0-499`     (first 500 bytes)
  * Open-ended: `bytes=500-`      (from 500 to EOF)
  * Suffix:     `bytes=-200`      (last 200 bytes)

Pinned invariants:
  * `start <= end` STRICT (RFC 7233 says invalid otherwise → None).
  * `end >= total_size` clamped to `total_size - 1` (RFC 7233 §2.1).
  * Suffix length larger than total clamped to total.
  * Only `bytes=` unit (RFC allows others; practice uses bytes only).
  * Multipart range (`bytes=0-99,200-299`) REJECTED — caller
    re-implements multipart if needed.
  * `total_size <= 0` → None (degenerate file).
  * Empty range (`bytes=`) → None.
  * Zero suffix (`bytes=-0`) → None (RFC says invalid).
  * Case-insensitive on `bytes=` token.

Pure stdlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Range:
    """A byte range. `start` and `end` are INCLUSIVE per RFC 7233."""

    start: int
    end: int
    length: int  # end - start + 1


# `bytes=START-END` where either side may be empty (suffix /
# open-ended).
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$", re.IGNORECASE)


def parse_range(
    header: str | None,
    total_size: int,
) -> Range | None:
    """Parse a Range header against `total_size`.

    Returns a Range or None for malformed / degenerate input.
    """
    if total_size <= 0:
        return None
    if not header:
        return None
    s = header.strip()
    if not s:
        return None

    m = _RANGE_RE.match(s)
    if not m:
        return None

    start_str = m.group(1)
    end_str = m.group(2)

    if start_str == "" and end_str == "":
        # `bytes=-` → empty range, invalid.
        return None

    if start_str == "":
        # Suffix form: `bytes=-N` (last N bytes).
        try:
            n = int(end_str)
        except ValueError:
            return None
        if n <= 0:
            return None
        if n > total_size:
            n = total_size
        start = total_size - n
        end = total_size - 1
    elif end_str == "":
        # Open-ended: `bytes=START-`.
        try:
            start = int(start_str)
        except ValueError:
            return None
        if start < 0 or start >= total_size:
            return None
        end = total_size - 1
    else:
        # Closed: `bytes=START-END`.
        try:
            start = int(start_str)
            end = int(end_str)
        except ValueError:
            return None
        if start < 0 or end < 0:
            return None
        if start > end:
            return None
        if start >= total_size:
            return None
        if end >= total_size:
            end = total_size - 1

    return Range(start=start, end=end, length=end - start + 1)
