"""HTTP If-Modified-Since parser (cycle AAA2).

Pinned seams:
  1. HTTP-date format parsed.
  2. Naive HTTP-date → UTC.
  3. Missing / malformed → None.
  4. should_return_304: last_modified <= if_modified_since → True.
  5. Second-precision comparison.
  6. Either side None → False.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.if_modified_since import (
    parse_if_modified_since,
    should_return_304_for_modified,
)

# ---------- parse_if_modified_since ----------


def test_parse_canonical_http_date():
    dt = parse_if_modified_since("Sun, 10 May 2026 12:00:00 GMT")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 10
    assert dt.hour == 12


def test_parse_naive_assumed_utc():
    """HTTP-date with no offset → UTC."""
    dt = parse_if_modified_since("Sun, 10 May 2026 12:00:00 -0000")
    assert dt is not None
    assert dt.utcoffset() == timedelta(0)


def test_parse_strips_whitespace():
    dt = parse_if_modified_since("  Sun, 10 May 2026 12:00:00 GMT  ")
    assert dt is not None


def test_parse_none_returns_none():
    assert parse_if_modified_since(None) is None


def test_parse_empty_returns_none():
    assert parse_if_modified_since("") is None
    assert parse_if_modified_since("   ") is None


def test_parse_garbage_returns_none():
    assert parse_if_modified_since("not-a-date") is None


def test_parse_iso_format_returns_none():
    """Pin: HTTP-date format ONLY. ISO-8601 not accepted."""
    # parsedate_to_datetime might accept ISO-like strings in some
    # versions — pin behaviour either way. ISO 8601 lacks the day
    # name, so should fail.
    result = parse_if_modified_since("2026-05-10T12:00:00")
    assert result is None


# ---------- should_return_304_for_modified ----------


def test_unchanged_returns_304():
    """Cardinal pin: resource last_modified <= client's
    if_modified_since → 304."""
    if_mod = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    last_mod = datetime(2026, 5, 10, 11, 0, 0, tzinfo=UTC)
    assert should_return_304_for_modified(if_mod, last_mod) is True


def test_unchanged_at_exact_time_returns_304():
    """Boundary: equal times → 304."""
    same = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    assert should_return_304_for_modified(same, same) is True


def test_modified_returns_no_304():
    """Resource newer than client's cached version → 200."""
    if_mod = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    last_mod = datetime(2026, 5, 10, 13, 0, 0, tzinfo=UTC)
    assert should_return_304_for_modified(if_mod, last_mod) is False


def test_subsecond_difference_treated_as_unchanged():
    """Cardinal pin: second-precision comparison. Microsecond-
    newer resource isn't a meaningful modification."""
    if_mod = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    last_mod = datetime(
        2026,
        5,
        10,
        12,
        0,
        0,
        999999,
        tzinfo=UTC,
    )
    assert should_return_304_for_modified(if_mod, last_mod) is True


def test_one_second_newer_is_modified():
    """1 second newer → modified."""
    if_mod = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    last_mod = datetime(2026, 5, 10, 12, 0, 1, tzinfo=UTC)
    assert should_return_304_for_modified(if_mod, last_mod) is False


def test_no_if_modified_since_returns_no_304():
    """Cardinal pin: no precondition → no 304 condition."""
    assert (
        should_return_304_for_modified(
            None,
            datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC),
        )
        is False
    )


def test_no_last_modified_returns_no_304():
    """Unknown last_modified → can't determine → serve body."""
    assert (
        should_return_304_for_modified(
            datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC),
            None,
        )
        is False
    )


def test_both_none_returns_no_304():
    assert should_return_304_for_modified(None, None) is False


# ---------- Realistic GET caching ----------


def test_realistic_unchanged_audit_list():
    """Realistic: client cached audit list 1 hour ago; server's
    most recent audit row is older → 304."""
    one_hour_ago = datetime(
        2026,
        5,
        10,
        11,
        0,
        0,
        tzinfo=UTC,
    )
    last_event = datetime(
        2026,
        5,
        10,
        10,
        30,
        0,
        tzinfo=UTC,
    )
    assert should_return_304_for_modified(one_hour_ago, last_event) is True


def test_realistic_changed_audit_list():
    """Client cached an hour ago; server has new event since."""
    one_hour_ago = datetime(
        2026,
        5,
        10,
        11,
        0,
        0,
        tzinfo=UTC,
    )
    new_event = datetime(2026, 5, 10, 11, 30, 0, tzinfo=UTC)
    assert should_return_304_for_modified(one_hour_ago, new_event) is False


# ---------- Round-trip ----------


def test_round_trip_via_http_date():
    """HTTP-date → parse → datetime, all preserves second precision."""
    parsed = parse_if_modified_since("Sun, 10 May 2026 12:00:00 GMT")
    assert parsed is not None
    assert parsed == datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
