"""TZ-aware ISO-8601 datetime serializer (cycle YY2).

Pinned seams:
  1. tz-aware preserved (offset preserved).
  2. Naive → UTC (+00:00).
  3. `Z` accepted on parse, `+00:00` emitted on output.
  4. Microseconds preserved.
  5. Round-trip stable.
  6. None / empty → None / "".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from services.tz_iso import parse_iso, to_iso

# ---------- to_iso ----------


def test_to_iso_utc_explicit():
    dt = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    assert to_iso(dt) == "2026-05-10T12:00:00+00:00"


def test_to_iso_naive_assumed_utc():
    dt = datetime(2026, 5, 10, 12, 0, 0)
    assert to_iso(dt) == "2026-05-10T12:00:00+00:00"


def test_to_iso_preserves_offset():
    """Cardinal pin: tz-aware datetimes preserve their offset.
    Distinct from AA2 which forces UTC."""
    plus_seven = timezone(timedelta(hours=7))
    dt = datetime(2026, 5, 10, 19, 0, 0, tzinfo=plus_seven)
    assert to_iso(dt) == "2026-05-10T19:00:00+07:00"


def test_to_iso_preserves_microseconds():
    """Cardinal pin: microseconds preserved (distinct from AA2
    which drops them for CSV operational form)."""
    dt = datetime(2026, 5, 10, 12, 0, 0, 123456, tzinfo=UTC)
    assert to_iso(dt) == "2026-05-10T12:00:00.123456+00:00"


def test_to_iso_negative_offset():
    """Negative offsets (Americas) preserved."""
    minus_five = timezone(timedelta(hours=-5))
    dt = datetime(2026, 5, 10, 7, 0, 0, tzinfo=minus_five)
    assert to_iso(dt) == "2026-05-10T07:00:00-05:00"


def test_to_iso_none():
    assert to_iso(None) == ""


# ---------- parse_iso ----------


def test_parse_iso_with_offset():
    dt = parse_iso("2026-05-10T12:00:00+00:00")
    assert dt is not None
    assert dt.year == 2026
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(0)


def test_parse_iso_with_z_suffix():
    """Cardinal pin: Z accepted on parse."""
    dt = parse_iso("2026-05-10T12:00:00Z")
    assert dt is not None
    assert dt.utcoffset() == timedelta(0)


def test_parse_iso_with_positive_offset():
    dt = parse_iso("2026-05-10T19:00:00+07:00")
    assert dt is not None
    assert dt.utcoffset() == timedelta(hours=7)


def test_parse_iso_with_negative_offset():
    dt = parse_iso("2026-05-10T07:00:00-05:00")
    assert dt is not None
    assert dt.utcoffset() == timedelta(hours=-5)


def test_parse_iso_with_microseconds():
    dt = parse_iso("2026-05-10T12:00:00.123456+00:00")
    assert dt is not None
    assert dt.microsecond == 123456


def test_parse_iso_naive_assumed_utc():
    """Naive input (no offset) → UTC."""
    dt = parse_iso("2026-05-10T12:00:00")
    assert dt is not None
    assert dt.utcoffset() == timedelta(0)


def test_parse_iso_strips_whitespace():
    dt = parse_iso("  2026-05-10T12:00:00Z  ")
    assert dt is not None


def test_parse_iso_none():
    assert parse_iso(None) is None


def test_parse_iso_empty():
    assert parse_iso("") is None
    assert parse_iso("   ") is None


def test_parse_iso_malformed():
    assert parse_iso("not-a-date") is None
    assert parse_iso("2026-13-01") is None  # invalid month
    assert parse_iso("2026-02-31") is None  # invalid day


# ---------- Round-trip ----------


def test_round_trip_utc():
    original = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    assert parse_iso(to_iso(original)) == original


def test_round_trip_with_offset():
    plus_seven = timezone(timedelta(hours=7))
    original = datetime(2026, 5, 10, 19, 0, 0, tzinfo=plus_seven)
    rt = parse_iso(to_iso(original))
    # Equality compares the same instant (after offset applied).
    assert rt == original


def test_round_trip_with_microseconds():
    original = datetime(2026, 5, 10, 12, 0, 0, 123456, tzinfo=UTC)
    assert parse_iso(to_iso(original)) == original


def test_round_trip_negative_offset():
    minus_five = timezone(timedelta(hours=-5))
    original = datetime(2026, 5, 10, 7, 0, 0, tzinfo=minus_five)
    rt = parse_iso(to_iso(original))
    assert rt == original


def test_z_normalized_to_offset_on_round_trip():
    """`Z` parsed → emitted as `+00:00` (canonical Python form).
    Pin so a refactor that swaps to `Z` suffix output surfaces."""
    parsed = parse_iso("2026-05-10T12:00:00Z")
    emitted = to_iso(parsed)
    assert emitted.endswith("+00:00")
    assert "Z" not in emitted


# ---------- Distinct from AA2 ----------


def test_preserves_microseconds_unlike_aa2():
    """Cardinal pin: YY2 preserves microseconds; AA2's CSV
    formatter drops them. Verify the distinction."""
    from services.csv_export import format_iso_for_csv

    dt = datetime(2026, 5, 10, 12, 0, 0, 123456, tzinfo=UTC)

    # AA2 drops microseconds.
    csv_form = format_iso_for_csv(dt)
    assert ".123456" not in csv_form

    # YY2 preserves them.
    api_form = to_iso(dt)
    assert ".123456" in api_form


def test_preserves_offset_unlike_aa2():
    """AA2 forces UTC; YY2 preserves offset."""
    from services.csv_export import format_iso_for_csv

    plus_seven = timezone(timedelta(hours=7))
    dt = datetime(2026, 5, 10, 19, 0, 0, tzinfo=plus_seven)

    # AA2 converts to UTC (so 19:00 +07:00 → 12:00 UTC).
    csv_form = format_iso_for_csv(dt)
    assert "12:00:00Z" in csv_form

    # YY2 preserves offset.
    api_form = to_iso(dt)
    assert "+07:00" in api_form
    assert "19:00:00" in api_form
