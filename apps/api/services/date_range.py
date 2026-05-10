"""Date range parser (cycle JJ2, Python half).

Server-side mirror of `apps/web/lib/date-range.ts`. Used by the
audit list endpoint, deliveries list endpoint, and dead-letter
list endpoint to parse `?from=...&to=...` URL params.

  parse_date_range(from_v, to_v, today)  — DateRange or None
  MAX_RANGE_DAYS                         — 365
  DateRange                              — frozen dataclass

Closed interval: start INCLUSIVE, end INCLUSIVE. Differs from
II1's audit-search half-open `since` semantics. Pin documented;
callers use the result to build SQL `BETWEEN` clauses.

Pure stdlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

# Maximum range size. Defends against multi-year queries that
# would park the audit DB scan.
MAX_RANGE_DAYS = 365


_REL_DAYS_RE = re.compile(r"^(\d+)d$")


@dataclass(frozen=True)
class DateRange:
    """Closed interval [start, end] (both inclusive)."""

    start: date
    end: date


def _parse_date_value(value: str, today: date) -> date | None:
    """Parse a single date value: ISO `YYYY-MM-DD`, `Nd`
    relative shorthand, or `now` keyword."""
    s = value.strip().lower()
    if not s:
        return None
    if s == "now":
        return today
    rel = _REL_DAYS_RE.match(s)
    if rel:
        n = int(rel.group(1))
        if 1 <= n <= MAX_RANGE_DAYS:
            return today - timedelta(days=n)
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_date_range(
    from_value: str | None,
    to_value: str | None,
    today: date | None = None,
) -> DateRange | None:
    """Parse `from`/`to` URL params into a DateRange.

    `today` defaults to `date.today()` (exposed for deterministic
    testing of relative shorthand).

    Returns None when:
      * Both `from` and `to` are None/empty.
      * Either value is malformed.
      * Resolved start > resolved end.
      * Resolved range exceeds MAX_RANGE_DAYS.
    """
    today = today or date.today()

    has_from = from_value not in (None, "")
    has_to = to_value not in (None, "")

    if not has_from and not has_to:
        return None

    if has_from:
        start = _parse_date_value(from_value, today)  # type: ignore[arg-type]
        if start is None:
            return None
    else:
        start = today - timedelta(days=MAX_RANGE_DAYS)

    if has_to:
        end = _parse_date_value(to_value, today)  # type: ignore[arg-type]
        if end is None:
            return None
    else:
        end = today

    if start > end:
        return None

    if (end - start).days > MAX_RANGE_DAYS:
        return None

    return DateRange(start=start, end=end)
