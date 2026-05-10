"""Time-window helpers (cycle Z3, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/time-window.test.ts`):
  1. TIME_WINDOW_OPTIONS chip set + order matches the TS half exactly.
  2. parse_since_days accepts [1, 365], rejects out-of-range and
     non-numeric input with a graceful None fallback (no raise).
  3. format_relative_age_vn thresholds: <60s vừa xong, <60m phút,
     <24h giờ, <30d ngày, <12mo tháng, else năm.
  4. Future-dated → "trong tương lai" (clock skew defense).
  5. None → "" (no-op for chained renderers — calling code can do
     `format_relative_age_vn(row.last_used_at, now)` without a
     None check).
  6. MAX_SINCE_DAYS = 365 — pin against the API's Query(le=365)
     bound on the audit / dead-letter / deliveries endpoints.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.time_window import (
    DEFAULT_SINCE_DAYS,
    MAX_SINCE_DAYS,
    TIME_WINDOW_OPTIONS,
    TimeWindowOption,
    format_relative_age_vn,
    parse_since_days,
)


# ---------- Constants ----------


def test_time_window_options_canonical_order():
    """Order matters — chips render left-to-right in this exact
    sequence so a user moving between pages sees the same layout.
    A refactor that swaps "24h" and "7d" would silently shift the
    chip layout across every page."""
    assert TIME_WINDOW_OPTIONS == (
        TimeWindowOption(value=1, label="24h"),
        TimeWindowOption(value=7, label="7d"),
        TimeWindowOption(value=30, label="30d"),
        TimeWindowOption(value=None, label="Tất cả"),
    )


def test_time_window_options_includes_null_sentinel():
    """The None entry is the wire-level "no filter" sentinel —
    pin so a refactor that removes it forces every page to
    special-case the unfiltered render."""
    all_time = [o for o in TIME_WINDOW_OPTIONS if o.value is None]
    assert len(all_time) == 1
    assert all_time[0].label == "Tất cả"


def test_time_window_option_is_frozen():
    """frozen=True so a refactor can't mutate a chip in place
    and silently shift the layout."""
    opt = TIME_WINDOW_OPTIONS[0]
    try:
        opt.label = "1d"  # type: ignore[misc]
    except Exception:  # FrozenInstanceError
        return
    raise AssertionError("TimeWindowOption should be frozen")


def test_max_since_days_pin():
    """Pin to 365 — matches the API's `Query(le=365)` bound on the
    audit / dead-letter / deliveries endpoints. A divergence would
    let the frontend send a value the API rejects."""
    assert MAX_SINCE_DAYS == 365


def test_default_since_days_pin():
    """7 — the converged 'last week' default across pages. A
    refactor that drops to None would silently shift to 'all time'
    and hammer the audit query."""
    assert DEFAULT_SINCE_DAYS == 7


# ---------- parse_since_days ----------


def test_parse_since_days_none_and_empty_returns_none():
    """None / "" → None (the all-time sentinel). Mirrors the TS
    parser's null/undefined/"" handling."""
    assert parse_since_days(None) is None
    assert parse_since_days("") is None


def test_parse_since_days_accepts_int_in_range():
    """Numeric input within [1, MAX_SINCE_DAYS] passes through."""
    assert parse_since_days(1) == 1
    assert parse_since_days(7) == 7
    assert parse_since_days(30) == 30
    assert parse_since_days(365) == 365


def test_parse_since_days_accepts_numeric_strings():
    """URL query strings arrive as strings — pin coercion."""
    assert parse_since_days("1") == 1
    assert parse_since_days("7") == 7
    assert parse_since_days("365") == 365


def test_parse_since_days_rejects_below_floor():
    """Below 1 → None. Zero / negative are invalid windows."""
    assert parse_since_days(0) is None
    assert parse_since_days(-1) is None
    assert parse_since_days("0") is None
    assert parse_since_days("-5") is None


def test_parse_since_days_rejects_above_ceiling():
    """Above MAX_SINCE_DAYS → None. A hand-edited URL with
    `since_days=10000` clamps to None rather than DOS-ing the
    audit query."""
    assert parse_since_days(366) is None
    assert parse_since_days(10_000) is None
    assert parse_since_days("10000") is None


def test_parse_since_days_rejects_non_numeric_strings():
    """Stale URLs with `since_days=abc` shouldn't crash —
    graceful fallback to None ("all time"). Same posture as
    the TS parser."""
    assert parse_since_days("abc") is None
    assert parse_since_days("7d") is None
    assert parse_since_days("seven") is None


def test_parse_since_days_truncates_floats():
    """The API expects integer days; floats from a hand-edited
    URL get floored rather than rejected. Python `int(7.9)`
    truncates toward zero, matching JS Math.trunc."""
    assert parse_since_days(7.9) == 7
    assert parse_since_days(7.1) == 7


def test_parse_since_days_rejects_unhashable_or_weird():
    """Defensive: a dict / list shouldn't crash the parser —
    graceful None. Caller can pass any URL-decoded value."""
    assert parse_since_days([7]) is None
    assert parse_since_days({"days": 7}) is None
    assert parse_since_days(object()) is None


# ---------- format_relative_age_vn ----------


# Pin a deterministic "now" so the threshold tests aren't flaky.
NOW = datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc)


def test_format_relative_age_vua_xong_under_60s():
    """< 60s → "vừa xong" (just now)."""
    then = NOW - timedelta(seconds=30)
    assert format_relative_age_vn(then, NOW) == "vừa xong"


def test_format_relative_age_vua_xong_at_zero():
    """Exact same instant → "vừa xong" (boundary defense)."""
    assert format_relative_age_vn(NOW, NOW) == "vừa xong"


def test_format_relative_age_phut_under_60m():
    """< 60m → "<N> phút trước"."""
    then = NOW - timedelta(minutes=23)
    assert format_relative_age_vn(then, NOW) == "23 phút trước"


def test_format_relative_age_phut_at_one_minute():
    """Boundary: exactly 60s → "1 phút trước" (not "vừa xong")."""
    then = NOW - timedelta(seconds=60)
    assert format_relative_age_vn(then, NOW) == "1 phút trước"


def test_format_relative_age_gio_under_24h():
    """< 24h → "<N> giờ trước"."""
    then = NOW - timedelta(hours=3)
    assert format_relative_age_vn(then, NOW) == "3 giờ trước"


def test_format_relative_age_ngay_under_30d():
    """< 30d → "<N> ngày trước"."""
    then = NOW - timedelta(days=5)
    assert format_relative_age_vn(then, NOW) == "5 ngày trước"


def test_format_relative_age_thang_under_12mo():
    """< 12mo → "<N> tháng trước". Pin the 30-day-month rounding
    used by both halves (calendar months are not used — the JS
    half doesn't have access to a calendar lib that's worth
    pulling in for this)."""
    # 90 days ≈ 3 months at 30-day rounding.
    then = NOW - timedelta(days=90)
    assert format_relative_age_vn(then, NOW) == "3 tháng trước"


def test_format_relative_age_nam_at_year():
    """>= 1 year → "<N> năm trước". 365-day rounding."""
    then = NOW - timedelta(days=730)  # ~2 years
    assert format_relative_age_vn(then, NOW) == "2 năm trước"


def test_format_relative_age_future_returns_clock_skew_label():
    """Defensive: a row with a clock-skewed future timestamp
    shouldn't render "X giờ trước" with a negative N. Slack
    digests and the audit page both rely on this — without it
    a misconfigured server clock would render nonsense."""
    then = NOW + timedelta(hours=1)
    assert format_relative_age_vn(then, NOW) == "trong tương lai"


def test_format_relative_age_none_returns_empty_string():
    """None → "". Calling code can do
    `format_relative_age_vn(row.last_used_at, now)` without a
    None check — the empty string slots into the templated
    plaintext / Slack message without crashing."""
    assert format_relative_age_vn(None, NOW) == ""


def test_format_relative_age_deterministic_with_supplied_now():
    """Two calls with the same `now` MUST return the same string
    — pin so a refactor that introduces side-effects (datetime.now())
    breaks here. The Slack alert digest builds with a frozen `now`
    so all messages in a batch agree on the relative ages."""
    then = NOW - timedelta(hours=3)
    a = format_relative_age_vn(then, NOW)
    b = format_relative_age_vn(then, NOW)
    assert a == b


def test_format_relative_age_naive_and_aware_consistent():
    """Both halves of a delta must use the same tz-awareness or
    Python raises TypeError. Pin that the formatter is consistent
    when given two naive datetimes (the audit row export path
    uses tz-naive UTC datetimes)."""
    naive_now = datetime(2026, 5, 9, 12, 0, 0)
    naive_then = naive_now - timedelta(minutes=5)
    assert format_relative_age_vn(naive_then, naive_now) == "5 phút trước"


# ---------- Cross-language consistency ----------


def test_chip_count_matches_ts_half():
    """The TS half pins exactly 4 chips. A divergence (e.g.
    adding a "90d" chip in one language but not the other) would
    make the picker render different chips on different pages."""
    assert len(TIME_WINDOW_OPTIONS) == 4


def test_chip_values_match_ts_half():
    """Pin the value set itself — `[1, 7, 30, None]`."""
    values = [opt.value for opt in TIME_WINDOW_OPTIONS]
    assert values == [1, 7, 30, None]


def test_chip_labels_match_ts_half():
    """Pin the label set itself — TS labels are vi-VN, must match
    the Python labels exactly. A translator who edits one but not
    the other would surface here."""
    labels = [opt.label for opt in TIME_WINDOW_OPTIONS]
    assert labels == ["24h", "7d", "30d", "Tất cả"]
