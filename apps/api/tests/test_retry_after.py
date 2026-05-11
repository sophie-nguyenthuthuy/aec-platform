"""Webhook Retry-After header parser (cycle FF2).

Pinned seams:
  1. MAX_RETRY_AFTER_SECONDS = 3600 (1-hour cap).
  2. Integer form: `Retry-After: 60` → 60.
  3. HTTP-date form: `Retry-After: <date>` → seconds-from-now.
  4. Past date → 0 (deliver now, don't sleep).
  5. Future date past MAX → clamped to MAX.
  6. Negative integer → None (RFC 7231 non-negative).
  7. Malformed → None.
  8. None / empty → None.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.retry_after import (
    MAX_RETRY_AFTER_SECONDS,
    parse_retry_after,
)

# 2026-05-10 is a Sunday — pick this so the day-of-week in test
# HTTP-dates matches.
NOW = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)


# ---------- Constants ----------


def test_max_retry_after_seconds_is_one_hour():
    """1 hour cap. Pin so a refactor that bumps to 24h surfaces
    in review — multi-hour Retry-After parks the delivery queue
    and breaks SLA visibility."""
    assert MAX_RETRY_AFTER_SECONDS == 3600


# ---------- Integer form ----------


def test_parse_integer_seconds():
    assert parse_retry_after("60", NOW) == 60
    assert parse_retry_after("0", NOW) == 0
    assert parse_retry_after("1", NOW) == 1


def test_parse_integer_at_cap():
    assert parse_retry_after("3600", NOW) == 3600


def test_parse_integer_above_cap_clamps():
    """Pin: a buggy server returning `Retry-After: 86400` (one
    day) clamps to MAX. Without this, the queue would park for
    a day."""
    assert parse_retry_after("86400", NOW) == MAX_RETRY_AFTER_SECONDS
    assert parse_retry_after("999999", NOW) == MAX_RETRY_AFTER_SECONDS


def test_parse_negative_integer_returns_none():
    """RFC 7231: Retry-After is non-negative. A negative value
    is malformed → None (caller falls back to default backoff).
    Pin so a refactor that accepts negative as "0" doesn't slip
    past — a negative is a real bug worth surfacing."""
    assert parse_retry_after("-1", NOW) is None
    assert parse_retry_after("-60", NOW) is None


def test_parse_integer_with_trailing_units_returns_none():
    """`60s` is not a valid Retry-After value — pin so we don't
    accidentally accept a sloppy server's typo."""
    assert parse_retry_after("60s", NOW) is None
    assert parse_retry_after("60ms", NOW) is None


def test_parse_integer_with_leading_zeros():
    """`060` is technically a valid integer per the spec.
    Accept."""
    assert parse_retry_after("060", NOW) == 60


def test_parse_integer_with_surrounding_whitespace():
    """Strip whitespace before parsing."""
    assert parse_retry_after("  60  ", NOW) == 60
    assert parse_retry_after("\t60\n", NOW) == 60


# ---------- HTTP-date form ----------


def test_parse_http_date_future_returns_seconds():
    """A future HTTP-date returns the seconds-until-it. May 10
    2026 is Sunday."""
    # 60 seconds in the future.
    header = "Sun, 10 May 2026 12:01:00 GMT"
    assert parse_retry_after(header, NOW) == 60


def test_parse_http_date_past_returns_zero():
    """Pin: a past HTTP-date returns 0 (deliver now). A
    misconfigured server clock shouldn't park the queue."""
    header = "Sun, 10 May 2026 11:59:00 GMT"  # 60s in the past
    assert parse_retry_after(header, NOW) == 0


def test_parse_http_date_far_past_returns_zero():
    header = "Wed, 01 Jan 2020 00:00:00 GMT"
    assert parse_retry_after(header, NOW) == 0


def test_parse_http_date_far_future_clamps():
    """A future date past MAX clamps to MAX. Pin so a server
    returning a date 24h in the future doesn't park the queue."""
    far = NOW + timedelta(hours=2)
    header = far.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert parse_retry_after(header, NOW) == MAX_RETRY_AFTER_SECONDS


def test_parse_http_date_at_cap_boundary():
    """Exactly MAX seconds in future → MAX (not clamped lower)."""
    cap_dt = NOW + timedelta(seconds=MAX_RETRY_AFTER_SECONDS)
    header = cap_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert parse_retry_after(header, NOW) == MAX_RETRY_AFTER_SECONDS


def test_parse_http_date_naive_assumed_utc():
    """A naive HTTP-date (no timezone in the string) is treated
    as UTC per RFC 7231. Pin so a refactor that uses local time
    surfaces here."""
    # Some servers omit the timezone — should still parse.
    # `parsedate_to_datetime` may include a default tzinfo;
    # pin behaviour either way via a forward-dated string.
    header = "Sun, 10 May 2026 12:01:00 -0000"
    # -0000 is UTC equivalent.
    assert parse_retry_after(header, NOW) == 60


# ---------- Malformed ----------


def test_parse_malformed_returns_none():
    """Garbage strings return None — caller falls back to
    default backoff."""
    assert parse_retry_after("not-a-date", NOW) is None
    assert parse_retry_after("garbage", NOW) is None


def test_parse_partial_date_returns_none():
    """A partial / non-RFC date returns None."""
    assert parse_retry_after("2026-05-10", NOW) is None
    assert parse_retry_after("tomorrow", NOW) is None


# ---------- None / empty ----------


def test_parse_none_returns_none():
    assert parse_retry_after(None, NOW) is None


def test_parse_empty_returns_none():
    assert parse_retry_after("", NOW) is None
    assert parse_retry_after("   ", NOW) is None
