"""HTTP If-Modified-Since parser (cycle AAA2).

Counterpart to VV2's If-None-Match for time-based conditional
GETs. RFC 7232 §3.3.

  parse_if_modified_since(header)                  — datetime or None
  should_return_304_for_modified(if_mod, last_mod) — bool

Composes with FF2's `parsedate_to_datetime` pattern (HTTP-date
parsing) and YY2's tz-aware datetime semantics.

Pinned invariants:
  * HTTP-date format (RFC 7231) parsed via stdlib.
  * Naive datetime (no offset in HTTP-date) interpreted as UTC.
  * Missing / malformed header → None.
  * `last_modified <= if_modified_since` → True (304 — resource
    unchanged since client's cached version).
  * `last_modified > if_modified_since` → False (resource changed,
    serve full body).
  * Second-precision comparison (HTTP-date drops sub-second;
    `last_modified.microsecond` is dropped before compare so a
    sub-second-newer resource isn't treated as "modified").
  * Either side None → False (no precondition / unknown
    last_modified means we can't determine — serve body).

Pure stdlib.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def parse_if_modified_since(header: str | None) -> datetime | None:
    """Parse an If-Modified-Since header value.

    Returns a tz-aware datetime or None.
    """
    if not header:
        return None
    s = header.strip()
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        # HTTP-date with no offset → UTC.
        dt = dt.replace(tzinfo=UTC)
    return dt


def should_return_304_for_modified(
    if_modified_since: datetime | None,
    last_modified: datetime | None,
) -> bool:
    """True iff the GET should return 304 Not Modified.

    Comparison is at second precision (HTTP-date drops sub-second).
    Returns False when either side is None (no precondition or
    unknown last_modified).
    """
    if if_modified_since is None:
        return False
    if last_modified is None:
        return False

    # Drop sub-second precision on `last_modified` (HTTP-date is
    # second-precision). A microsecond newer than the client's
    # cached time isn't a meaningful "modification".
    last_modified_s = last_modified.replace(microsecond=0)

    return last_modified_s <= if_modified_since
