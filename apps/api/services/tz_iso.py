"""TZ-aware ISO-8601 datetime serializer (cycle YY2).

Serialize / parse ISO-8601 datetimes preserving timezone offset
and microseconds. Used by API responses, webhook payloads, and
audit row JSON.

  to_iso(dt)     — "2026-05-10T12:00:00+00:00" or ""
  parse_iso(s)   — tz-aware datetime or None

Distinct from AA2's `format_iso_for_csv`:
  * AA2 forces UTC and DROPS microseconds (CSV operational form).
  * YY2 PRESERVES timezone offset and microseconds (full
    precision for API / webhook contracts).

Pinned invariants:
  * tz-aware datetimes preserved verbatim (offset preserved).
  * Naive datetimes assumed UTC, emit `+00:00`.
  * `Z` suffix on parse → treated as `+00:00`.
  * Output uses `+00:00` form (NOT `Z`) — canonical per
    Python's `isoformat`. Pin so a refactor that swaps to `Z`
    suffix output surfaces here.
  * Microseconds preserved in both directions.
  * Round-trip stable: `parse_iso(to_iso(dt)) == dt` for
    tz-aware inputs.
  * None / malformed → None on parse, `""` on format.

Pure stdlib.
"""

from __future__ import annotations

from datetime import UTC, datetime


def to_iso(dt: datetime | None) -> str:
    """Serialize a datetime to canonical ISO-8601 with offset.

    Examples:
      * to_iso(datetime(2026,5,10,12,0,0,tzinfo=UTC))
          → "2026-05-10T12:00:00+00:00"
      * to_iso(datetime(2026,5,10,12,0,0))   # naive → UTC
          → "2026-05-10T12:00:00+00:00"
      * to_iso(datetime(2026,5,10,19,0,0,tzinfo=+07:00))
          → "2026-05-10T19:00:00+07:00"
      * to_iso(None) → ""

    Naive datetimes are interpreted as UTC and emit `+00:00`.
    Microseconds are preserved.
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def parse_iso(s: str | None) -> datetime | None:
    """Parse an ISO-8601 string to a tz-aware datetime.

    Accepts both `+00:00` offset and `Z` (zulu) suffix. Naive
    inputs (no offset) are interpreted as UTC.

    Returns None for None / empty / malformed input.
    """
    if not s:
        return None
    text = s.strip()
    if not text:
        return None

    # Python's `datetime.fromisoformat` (pre-3.11) doesn't accept
    # `Z` suffix. Normalize to `+00:00`.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None

    # Naive → UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
