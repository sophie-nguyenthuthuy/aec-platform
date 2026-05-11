"""HTTP ETag / If-Match parser (cycle LL2).

Parse RFC 7232 `ETag` and `If-Match` headers for optimistic
concurrency. Today the PATCH endpoints on estimates, RFQs, and
change orders each parse inline with subtly different
weak-prefix handling. This module is the single source of truth.

  parse_etag(header)        — ETag or None
  parse_if_match(header)    — IfMatchList or None (None = invalid)
  ETag                      — frozen dataclass (value, weak)
  IfMatchList               — frozen dataclass (etags, is_wildcard)

Pinned invariants:
  * Strong format: `"value"` (double-quoted).
  * Weak format: `W/"value"` (W/ prefix, then quoted value).
  * `*` wildcard for If-Match must be EXCLUSIVE (not mixed with
    other entries).
  * Comma-separated If-Match list with whitespace tolerance.
  * Empty / missing header → IfMatchList((), False)  (no precondition).
  * Malformed (unclosed quote, garbage) → None.
  * Weak prefix detected and recorded; value strips the W/.

Pure stdlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Strong: `"value"`
# Weak:   `W/"value"`
# Note: regex is fullmatch-anchored elsewhere so `^` / `$` here
# are redundant but kept for clarity.
_ETAG_RE = re.compile(r'(W/)?"([^"]*)"')


@dataclass(frozen=True)
class ETag:
    """A parsed ETag.

    `value` is the unquoted value. `weak` is True iff the
    original header was prefixed with `W/`.
    """

    value: str
    weak: bool


@dataclass(frozen=True)
class IfMatchList:
    """A parsed If-Match header.

    `etags` is the parsed list (empty when no header or wildcard).
    `is_wildcard` is True iff the header was a bare `*`.
    Both `etags` and `is_wildcard` are mutually exclusive (when
    wildcard is True, etags is always empty).
    """

    etags: tuple[ETag, ...]
    is_wildcard: bool


def parse_etag(header: str | None) -> ETag | None:
    """Parse a single ETag header value.

    Returns ETag or None for malformed / empty input.
    """
    if header is None:
        return None
    s = header.strip()
    if not s:
        return None
    m = _ETAG_RE.fullmatch(s)
    if not m:
        return None
    return ETag(value=m.group(2), weak=m.group(1) is not None)


def parse_if_match(header: str | None) -> IfMatchList | None:
    """Parse an If-Match header value.

    Returns:
      * `IfMatchList((), False)` for None / empty header (no precondition).
      * `IfMatchList((), True)` for bare `*` (wildcard).
      * `IfMatchList(etags, False)` for valid comma-separated list.
      * `None` for malformed headers (mixed wildcard, malformed etag).
    """
    if header is None:
        return IfMatchList(etags=(), is_wildcard=False)
    s = header.strip()
    if not s:
        return IfMatchList(etags=(), is_wildcard=False)

    # Bare wildcard.
    if s == "*":
        return IfMatchList(etags=(), is_wildcard=True)

    parts = [p.strip() for p in s.split(",")]

    # Wildcard cannot be mixed with other entries.
    if "*" in parts:
        return None

    etags: list[ETag] = []
    for part in parts:
        etag = parse_etag(part)
        if etag is None:
            # Any malformed entry → entire header invalid.
            return None
        etags.append(etag)

    return IfMatchList(etags=tuple(etags), is_wildcard=False)
