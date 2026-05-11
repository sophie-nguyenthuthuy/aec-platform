"""Vietnamese business-day calculator (cycle DD2).

Closed table of VN public holidays + helpers for skipping
weekends + holidays. Used by:

  * RFQ deadline calculator (5 business days from issue).
  * Change order SLA timer (7 business days in `reviewing` →
    stuck-order Slack alert).
  * Submittal review SLA (10 business days in `under_review` →
    deadline-overrun alert).
  * The audit verification trail's stuck-row detector (it uses
    business days, not calendar days, so a long Tết stretch
    doesn't surface stuck items as false positives).

  VN_PUBLIC_HOLIDAYS         — closed frozenset of dates
  is_business_day(d)         — bool: not weekend, not holiday
  next_business_day(d)       — first business day strictly after d
  add_business_days(d, n)    — d + n business days (skipping weekends + holidays)
  business_days_between(a,b) — count business days in [a, b)

Pure stdlib. The holiday table is a closed pinned set — operators
update it annually based on VN government decree. The actual
holiday dates depend on (a) the lunar calendar (Tết, Hùng Kings)
and (b) discretionary "compensation days" added each year.

Important: `add_business_days(d, 0)` returns d unchanged even
if d is a weekend or holiday. The caller decides whether to
auto-skip; pin so a "0 means start tomorrow" misreading doesn't
slip past.
"""

from __future__ import annotations

from datetime import date, timedelta

# Closed table of VN public holidays for 2026 + 2027. Operators
# extend this annually based on the government's Tết and
# compensation-day decree.
#
# Sources / notes:
#   * 1/1 — Tết Dương lịch (Gregorian New Year).
#   * Lunar Tết — multi-day stretch around the lunar new year
#     (typically eve + 4 days). 2026 Tết = Feb 17; 2027 Tết = Feb 6.
#   * 10/3 lunar — Hùng Kings Commemoration. 2026 = Apr 26;
#     2027 = Apr 16.
#   * 30/4 — Reunification Day.
#   * 1/5 — Labour Day.
#   * 2/9 — National Day.
VN_PUBLIC_HOLIDAYS: frozenset[date] = frozenset(
    {
        # ---------- 2026 ----------
        date(2026, 1, 1),  # Tết Dương lịch
        date(2026, 2, 16),  # Tết Eve (lunar)
        date(2026, 2, 17),  # Tết Day 1
        date(2026, 2, 18),  # Tết Day 2
        date(2026, 2, 19),  # Tết Day 3
        date(2026, 2, 20),  # Tết Day 4
        date(2026, 4, 26),  # Hùng Kings (10/3 lunar)
        date(2026, 4, 30),  # Reunification Day
        date(2026, 5, 1),  # Labour Day
        date(2026, 9, 2),  # National Day
        # ---------- 2027 ----------
        date(2027, 1, 1),  # Tết Dương lịch
        date(2027, 2, 5),  # Tết Eve (lunar)
        date(2027, 2, 6),  # Tết Day 1
        date(2027, 2, 7),  # Tết Day 2
        date(2027, 2, 8),  # Tết Day 3
        date(2027, 2, 9),  # Tết Day 4
        date(2027, 4, 16),  # Hùng Kings (10/3 lunar)
        date(2027, 4, 30),  # Reunification Day
        date(2027, 5, 1),  # Labour Day
        date(2027, 9, 2),  # National Day
    }
)


def is_business_day(d: date) -> bool:
    """True iff `d` is a weekday (Mon-Fri) AND not a public holiday.

    Saturday / Sunday → False. Public holiday on a weekday → False.
    Public holiday that falls on a weekend → False (still not a
    business day; the date column matters more than the
    weekend-vs-holiday classification).
    """
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return d not in VN_PUBLIC_HOLIDAYS


def next_business_day(d: date) -> date:
    """First business day STRICTLY AFTER `d`.

    `next_business_day(Friday)` returns the following Monday (or
    Tuesday if Monday is a holiday). `next_business_day(holiday)`
    returns the next non-holiday weekday.
    """
    nxt = d + timedelta(days=1)
    while not is_business_day(nxt):
        nxt += timedelta(days=1)
    return nxt


def _previous_business_day(d: date) -> date:
    """First business day STRICTLY BEFORE `d`. Internal helper
    for negative `add_business_days`."""
    prev = d - timedelta(days=1)
    while not is_business_day(prev):
        prev -= timedelta(days=1)
    return prev


def add_business_days(d: date, n: int) -> date:
    """Return `d` plus `n` business days.

    `n == 0` returns `d` unchanged, even if `d` is a weekend or
    holiday. The caller is responsible for deciding whether to
    auto-skip on a zero-step (pin: don't auto-skip; surface
    surprises in the SLA timer rather than silently shifting).

    Negative `n` walks backwards.
    """
    if n == 0:
        return d
    if n > 0:
        result = d
        for _ in range(n):
            result = next_business_day(result)
        return result
    # n < 0
    result = d
    for _ in range(abs(n)):
        result = _previous_business_day(result)
    return result


def business_days_between(start: date, end: date) -> int:
    """Count business days in the half-open interval [start, end).

    `start` is inclusive, `end` is exclusive. If `end <= start`,
    returns 0 (no negative counts — the caller's bug surfaces as
    a zero, not a negative SLA breach).
    """
    if end <= start:
        return 0
    count = 0
    cur = start
    while cur < end:
        if is_business_day(cur):
            count += 1
        cur += timedelta(days=1)
    return count
