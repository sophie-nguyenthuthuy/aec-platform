"""RFQ deadline calculator (cycle GG1).

Composes with `services.vn_business_days` (DD2) for VN-holiday-
aware deadline math. Today the RFQ list page's "due in N days"
badge, the deadline-overrun Slack alert, and the audit row's
deadline-impact detector each duplicate this logic inline with
subtly different defaults / clamping. This module is the single
source of truth.

  DEFAULT_DEADLINE_BUSINESS_DAYS  — 5 (one business week)
  MIN_DEADLINE_BUSINESS_DAYS      — 1
  MAX_DEADLINE_BUSINESS_DAYS      — 30 (legal procurement-window cap)
  effective_business_days(o)      — clamps override to band
  compute_deadline(issued, o)     — date
  is_overdue(deadline, now)       — bool (strict `>` boundary)
  business_days_remaining(...)    — int, negative when overdue

Override clamping rules (mirrors EE1's retention pattern):
  * `override is None` → DEFAULT (NOT MIN — pin against a refactor
    that treats absent override as "minimum window").
  * `override < MIN` → clamps UP to MIN (typo defense — admin
    types `0` thinking days but means weeks).
  * `override > MAX` → clamps DOWN to MAX (legal procurement
    ceiling — past 30 days is operationally a different process).

Pure stdlib + DD2.
"""

from __future__ import annotations

from datetime import date

from services.vn_business_days import (
    add_business_days,
    business_days_between,
)

# Default RFQ response window — one business week. Pin so a
# refactor that drops to e.g. 3 days surfaces in review (would
# silently shorten every untouched org's procurement timeline).
DEFAULT_DEADLINE_BUSINESS_DAYS = 5


# Floor — even an aggressive RFQ has at least a 1-business-day
# window. Defends against `0` override (which would set the
# deadline to issue date itself).
MIN_DEADLINE_BUSINESS_DAYS = 1


# Ceiling — 30 business days ≈ 6 calendar weeks. Past this, the
# procurement is operationally a different process (long-tender)
# and shouldn't be configured via the RFQ deadline override.
MAX_DEADLINE_BUSINESS_DAYS = 30


def effective_business_days(override: int | None) -> int:
    """Resolve the effective deadline business-day bound.

    See module docstring for clamping rules.
    """
    if override is None:
        return DEFAULT_DEADLINE_BUSINESS_DAYS
    if override < MIN_DEADLINE_BUSINESS_DAYS:
        return MIN_DEADLINE_BUSINESS_DAYS
    if override > MAX_DEADLINE_BUSINESS_DAYS:
        return MAX_DEADLINE_BUSINESS_DAYS
    return override


def compute_deadline(issued_at: date, override: int | None = None) -> date:
    """Return the deadline date for an RFQ issued on `issued_at`.

    Skips weekends + VN public holidays (delegates to DD2's
    `add_business_days`). Pin: `compute_deadline(Mon, None)`
    returns the following Monday (5 business days = full
    business week).
    """
    days = effective_business_days(override)
    return add_business_days(issued_at, days)


def is_overdue(deadline: date, now: date) -> bool:
    """True iff `now` is STRICTLY past `deadline`.

    Boundary pin: a deadline AT `now` is NOT yet overdue — the
    RFQ has until end-of-deadline-day to respond. A refactor
    that flips to `>=` would surprise-overdue at the boundary.
    """
    return now > deadline


def business_days_remaining(deadline: date, now: date) -> int:
    """Return business days from `now` to `deadline`.

    Sign convention:
      * Positive: due in N business days (e.g. 4 = "due in 4 days").
      * 0:        deadline IS today (not overdue).
      * Negative: overdue by N business days (e.g. -1 = "1 day overdue").

    Uses DD2's half-open `business_days_between(start, end)` so
    the count correctly excludes the deadline date from the
    "remaining" count and includes the deadline date in the
    "overdue" count (Friday-deadline-now-Monday-next returns -1
    because Friday is one business day past).
    """
    if now > deadline:
        return -business_days_between(deadline, now)
    if now == deadline:
        return 0
    return business_days_between(now, deadline)
