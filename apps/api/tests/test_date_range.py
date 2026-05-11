"""Date range parser (cycle JJ2, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/date-range.test.ts`):
  1. MAX_RANGE_DAYS = 365.
  2. ISO YYYY-MM-DD format.
  3. Closed interval.
  4. Both ends optional; at least one required.
  5. Relative `Nd` shorthand and `now` keyword.
  6. Range > MAX_RANGE_DAYS → None.
  7. start > end → None.
  8. Malformed → None.
"""

from __future__ import annotations

from datetime import date

from services.date_range import (
    MAX_RANGE_DAYS,
    DateRange,
    parse_date_range,
)

TODAY = date(2026, 5, 10)


# ---------- Constants ----------


def test_max_range_days_is_365():
    assert MAX_RANGE_DAYS == 365


# ---------- ISO inputs ----------


def test_parse_iso_both_ends():
    result = parse_date_range("2026-01-01", "2026-01-31", TODAY)
    assert result == DateRange(start=date(2026, 1, 1), end=date(2026, 1, 31))


def test_parse_same_day():
    result = parse_date_range("2026-05-10", "2026-05-10", TODAY)
    assert result == DateRange(start=date(2026, 5, 10), end=date(2026, 5, 10))


# ---------- Relative shorthand ----------


def test_relative_n_days_before_today():
    result = parse_date_range("7d", "now", TODAY)
    assert result == DateRange(start=date(2026, 5, 3), end=date(2026, 5, 10))


def test_now_keyword():
    result = parse_date_range("2026-05-01", "now", TODAY)
    assert result is not None
    assert result.end == TODAY


def test_relative_on_both_ends():
    result = parse_date_range("30d", "1d", TODAY)
    assert result == DateRange(
        start=date(2026, 4, 10),
        end=date(2026, 5, 9),
    )


def test_zero_days_rejected():
    """Pin: 0d is below min — rejected."""
    assert parse_date_range("0d", "now", TODAY) is None


def test_relative_beyond_max_rejected():
    assert parse_date_range("400d", "now", TODAY) is None


# ---------- One-sided ----------


def test_from_only_end_defaults_today():
    result = parse_date_range("7d", None, TODAY)
    assert result == DateRange(start=date(2026, 5, 3), end=TODAY)


def test_to_only_start_defaults_max_range_ago():
    result = parse_date_range(None, "2026-05-01", TODAY)
    assert result is not None
    assert result.end == date(2026, 5, 1)


def test_both_none_returns_none():
    assert parse_date_range(None, None, TODAY) is None


def test_both_empty_returns_none():
    assert parse_date_range("", "", TODAY) is None


# ---------- Validation ----------


def test_start_after_end_rejected():
    assert parse_date_range("2026-02-01", "2026-01-01", TODAY) is None


def test_range_exceeding_max_rejected():
    assert parse_date_range("2025-01-01", "2026-12-31", TODAY) is None


def test_range_exactly_at_max_accepted():
    """365-day range exactly is accepted; 366 rejected."""
    result = parse_date_range("2025-05-10", "2026-05-10", TODAY)
    assert result is not None
    assert (result.end - result.start).days == 365


def test_range_366_days_rejected():
    """One past max."""
    assert parse_date_range("2025-05-09", "2026-05-10", TODAY) is None


# ---------- Malformed ----------


def test_malformed_iso_rejected():
    assert parse_date_range("not-a-date", "2026-01-01", TODAY) is None


def test_invalid_month_rejected():
    assert parse_date_range("2026-13-01", "now", TODAY) is None


def test_invalid_day_rejected():
    """Feb 31 doesn't exist — pin so a refactor that loosens
    parsing surfaces here."""
    assert parse_date_range("2026-02-31", "now", TODAY) is None


# ---------- Whitespace / case ----------


def test_strips_whitespace():
    result = parse_date_range("  7d  ", "  now  ", TODAY)
    assert result == DateRange(start=date(2026, 5, 3), end=TODAY)


def test_now_keyword_case_insensitive():
    assert parse_date_range("2026-05-01", "NOW", TODAY) is not None
    assert parse_date_range("2026-05-01", "Now", TODAY) is not None


# ---------- DateRange shape ----------


def test_date_range_is_frozen():
    r = DateRange(start=date(2026, 1, 1), end=date(2026, 1, 2))
    try:
        r.start = date(2026, 2, 1)  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("DateRange should be frozen")
