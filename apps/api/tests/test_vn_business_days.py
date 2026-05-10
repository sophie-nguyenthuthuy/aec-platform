"""Vietnamese business-day calculator (cycle DD2).

Pinned seams:
  1. VN_PUBLIC_HOLIDAYS contains 2026 + 2027 holidays as a frozen set.
  2. Saturday / Sunday are non-business.
  3. Public holidays on weekdays are non-business.
  4. Tết multi-day stretch (5 consecutive holiday days) handled atomically.
  5. add_business_days(d, 0) returns d unchanged (no auto-skip).
  6. Negative add_business_days walks backwards.
  7. business_days_between is half-open [start, end).
  8. business_days_between(a, b) returns 0 when b <= a (no negatives).
"""

from __future__ import annotations

from datetime import date

from services.vn_business_days import (
    VN_PUBLIC_HOLIDAYS,
    add_business_days,
    business_days_between,
    is_business_day,
    next_business_day,
)

# ---------- VN_PUBLIC_HOLIDAYS ----------


def test_vn_public_holidays_is_frozen():
    """frozenset so a refactor can't `VN_PUBLIC_HOLIDAYS.add(...)`
    and silently shift the SLA timer."""
    assert isinstance(VN_PUBLIC_HOLIDAYS, frozenset)


def test_vn_public_holidays_includes_fixed_date_holidays_2026():
    """Pin the 4 fixed-date holidays for 2026 — these don't
    depend on the lunar calendar so should be stable across
    operator re-runs of the holiday table."""
    assert date(2026, 1, 1) in VN_PUBLIC_HOLIDAYS  # New Year
    assert date(2026, 4, 30) in VN_PUBLIC_HOLIDAYS  # Reunification
    assert date(2026, 5, 1) in VN_PUBLIC_HOLIDAYS  # Labour Day
    assert date(2026, 9, 2) in VN_PUBLIC_HOLIDAYS  # National Day


def test_vn_public_holidays_includes_tet_2026_stretch():
    """Pin the 5-day Tết stretch for 2026. A refactor that
    drops one of the days would silently shorten the SLA-pause
    window during the busiest VN holiday."""
    for day in [16, 17, 18, 19, 20]:
        assert date(2026, 2, day) in VN_PUBLIC_HOLIDAYS, f"2026-02-{day:02d} should be in VN_PUBLIC_HOLIDAYS"


def test_vn_public_holidays_includes_tet_2027_stretch():
    for day in [5, 6, 7, 8, 9]:
        assert date(2027, 2, day) in VN_PUBLIC_HOLIDAYS, f"2027-02-{day:02d} should be in VN_PUBLIC_HOLIDAYS"


def test_vn_public_holidays_excludes_random_weekdays():
    """Sanity: a random Tuesday isn't a holiday."""
    assert date(2026, 6, 9) not in VN_PUBLIC_HOLIDAYS
    assert date(2026, 7, 14) not in VN_PUBLIC_HOLIDAYS


# ---------- is_business_day ----------


def test_is_business_day_true_for_random_weekday():
    # 2026-05-11 is a Monday, not a holiday.
    assert is_business_day(date(2026, 5, 11)) is True


def test_is_business_day_false_for_saturday():
    # 2026-05-09 is a Saturday.
    assert is_business_day(date(2026, 5, 9)) is False


def test_is_business_day_false_for_sunday():
    # 2026-05-10 is a Sunday.
    assert is_business_day(date(2026, 5, 10)) is False


def test_is_business_day_false_for_holiday_on_weekday():
    """1/5/2026 is Friday + Labour Day → False."""
    d = date(2026, 5, 1)
    assert d.weekday() == 4  # Friday
    assert is_business_day(d) is False


def test_is_business_day_false_throughout_tet():
    """Pin: every day of the Tết stretch is non-business
    regardless of weekday classification."""
    for day in [16, 17, 18, 19, 20]:
        assert is_business_day(date(2026, 2, day)) is False


# ---------- next_business_day ----------


def test_next_business_day_after_friday_skips_weekend():
    # 2026-05-08 is a Friday (not a holiday).
    fri = date(2026, 5, 8)
    assert next_business_day(fri) == date(2026, 5, 11)  # Monday


def test_next_business_day_skips_holiday():
    # 2026-04-29 is Wednesday. Next is 4/30 (Reunification, holiday)
    # → 5/1 (Labour Day, holiday) → 5/2 Saturday → 5/3 Sunday → 5/4 Mon.
    wed = date(2026, 4, 29)
    assert next_business_day(wed) == date(2026, 5, 4)


def test_next_business_day_after_tet_eve():
    """From Feb 15 (Sunday before Tết), next business day is
    Feb 23 (Monday after the 5-day Tết + weekend). Pin the
    multi-day skip atomically."""
    sun = date(2026, 2, 15)
    assert next_business_day(sun) == date(2026, 2, 23)


def test_next_business_day_strictly_after():
    """`next_business_day(business_day)` returns the NEXT one,
    not the same day. Pin: 'next' means strictly after."""
    mon = date(2026, 5, 11)  # Monday
    assert is_business_day(mon) is True
    assert next_business_day(mon) == date(2026, 5, 12)  # Tuesday


# ---------- add_business_days ----------


def test_add_zero_business_days_returns_same_date():
    """Pin: n=0 returns d unchanged even if d is a weekend or
    holiday. Caller decides whether to auto-skip — no implicit
    snapping."""
    sat = date(2026, 5, 9)
    assert add_business_days(sat, 0) == sat
    holiday = date(2026, 5, 1)
    assert add_business_days(holiday, 0) == holiday
    weekday = date(2026, 5, 11)
    assert add_business_days(weekday, 0) == weekday


def test_add_one_business_day_from_weekday():
    mon = date(2026, 5, 11)  # Monday
    assert add_business_days(mon, 1) == date(2026, 5, 12)  # Tuesday


def test_add_one_business_day_from_friday_skips_weekend():
    fri = date(2026, 5, 8)
    assert add_business_days(fri, 1) == date(2026, 5, 11)  # Monday


def test_add_five_business_days_skips_one_weekend():
    """Mon + 5 business days = next Monday (5 weekdays)."""
    mon = date(2026, 5, 11)
    assert add_business_days(mon, 5) == date(2026, 5, 18)


def test_add_business_days_across_tet():
    """Feb 13 (Friday before Tết Eve) + 1 business day = Feb 23
    (Monday after Tết). The 5-day Tết + weekend = 7-day skip."""
    fri = date(2026, 2, 13)
    assert is_business_day(fri) is True
    assert add_business_days(fri, 1) == date(2026, 2, 23)


def test_add_negative_business_days_walks_back():
    """Negative n walks backwards. Pin so a refactor that adds
    a default-positive guard doesn't silently treat -3 as +3."""
    mon = date(2026, 5, 18)  # Monday
    assert add_business_days(mon, -1) == date(2026, 5, 15)  # Friday
    assert add_business_days(mon, -5) == date(2026, 5, 11)  # Mon prior


def test_add_negative_one_from_monday_skips_weekend_back():
    mon = date(2026, 5, 11)
    assert add_business_days(mon, -1) == date(2026, 5, 8)  # Friday


# ---------- business_days_between ----------


def test_business_days_between_same_week():
    """Mon → Fri (half-open): counts Mon, Tue, Wed, Thu = 4."""
    mon = date(2026, 5, 11)
    fri = date(2026, 5, 15)
    assert business_days_between(mon, fri) == 4


def test_business_days_between_inclusive_start_exclusive_end():
    """Pin half-open: business_days_between(d, d+1) = 1 if d is
    a business day, else 0."""
    mon = date(2026, 5, 11)
    assert business_days_between(mon, date(2026, 5, 12)) == 1
    sat = date(2026, 5, 9)
    assert business_days_between(sat, date(2026, 5, 10)) == 0


def test_business_days_between_zero_for_equal_dates():
    """[d, d) is empty."""
    d = date(2026, 5, 11)
    assert business_days_between(d, d) == 0


def test_business_days_between_zero_for_reversed_range():
    """end < start → 0 (not negative). Pin so a caller bug
    surfaces as a zero rather than a wraparound."""
    assert business_days_between(date(2026, 5, 11), date(2026, 5, 1)) == 0


def test_business_days_between_skips_tet():
    """Feb 13 (Fri) → Feb 24 (Tue): the half-open range covers
    Feb 13 (Fri) + Feb 23 (Mon) = 2 business days. Tết and the
    weekend in between are skipped."""
    start = date(2026, 2, 13)
    end = date(2026, 2, 24)
    assert business_days_between(start, end) == 2


def test_business_days_between_full_week_spanning_weekend():
    """Mon → Mon next: 5 business days (Mon-Fri inclusive,
    Mon next exclusive)."""
    start = date(2026, 5, 11)
    end = date(2026, 5, 18)
    assert business_days_between(start, end) == 5
