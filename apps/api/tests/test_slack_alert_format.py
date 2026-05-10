"""Slack alert message formatter (cycle Y1).

Pinned seams:
  1. Single-alert format: icon + subject_label + backtick subject
     + " — " separator + detail.
  2. alert_count == 1 → no repeat label.
  3. alert_count >= 2 → " (still <state>, N×)" appended right after
     the backtick subject (before the " — ").
  4. 500-char cap with "…" suffix on truncation; the "…" fits inside
     the cap (never produces a 501-char body).
  5. Each per-kind wrapper produces the same shape as the
     previously-duplicated formatter functions in cron_alerts.py
     and webhook_health_alerts.py.
"""

from __future__ import annotations

from services.slack_alert_format import (
    ICON_FAILURE,
    ICON_HEALTH,
    ICON_STUCK,
    MAX_BODY_CHARS,
    AlertSpec,
    format_alert,
    format_cron_failure,
    format_cron_stuck,
    format_webhook_unhealthy,
)

# ---------- Constants ----------


def test_max_body_chars_pinned():
    """500 matches the legacy formatters' caps. A bump would let
    Slack messages span multi-card mobile previews — pin so the
    change requires a deliberate review."""
    assert MAX_BODY_CHARS == 500


def test_icons_pinned():
    """Pin the emoji slugs. An accessibility refactor (e.g. swap
    rotating_light for warning) should be a deliberate one-line
    change, not a hidden drift across three modules."""
    assert ICON_FAILURE == ":rotating_light:"
    assert ICON_STUCK == ":hourglass_flowing_sand:"
    # Webhook health intentionally re-uses the same alarm icon as
    # cron failure — same operator urgency.
    assert ICON_HEALTH == ":rotating_light:"


# ---------- format_alert (core) ----------


def test_format_alert_no_repeat_for_first_alert():
    """alert_count=1 → no repeat label. The "still failing" framing
    only makes sense once we've alerted at least once before."""
    out = format_alert(
        AlertSpec(
            icon=":rotating_light:",
            subject_label="cron failed",
            subject="cron:test",
            detail="RuntimeError: db down",
            repeat_state="failing",
            alert_count=1,
        )
    )
    assert out == ":rotating_light: cron failed: `cron:test` — RuntimeError: db down"


def test_format_alert_appends_repeat_label_for_re_alert():
    """alert_count=3 → "(still failing, 3×)" between the subject
    and the detail. Pin the position so a refactor that puts it
    at the end of the line breaks the regex-based parsers some
    operators write for Slack thread digests."""
    out = format_alert(
        AlertSpec(
            icon=":rotating_light:",
            subject_label="cron failed",
            subject="cron:test",
            detail="RuntimeError: db down",
            repeat_state="failing",
            alert_count=3,
        )
    )
    assert out == ":rotating_light: cron failed: `cron:test` (still failing, 3×) — RuntimeError: db down"


def test_format_alert_repeat_threshold_at_two():
    """alert_count >= 2 triggers the repeat label; alert_count = 2
    is the boundary. Pin so a "let's wait until 3 to call it
    repeating" refactor doesn't silently shift the threshold."""
    out_one = format_alert(
        AlertSpec(
            icon=":x:",
            subject_label="x",
            subject="y",
            detail="z",
            repeat_state="happening",
            alert_count=1,
        )
    )
    out_two = format_alert(
        AlertSpec(
            icon=":x:",
            subject_label="x",
            subject="y",
            detail="z",
            repeat_state="happening",
            alert_count=2,
        )
    )
    assert "still happening" not in out_one
    assert "still happening, 2×" in out_two


def test_format_alert_caps_at_max_body_chars():
    """A long detail message → cap at MAX_BODY_CHARS with "…" on
    the truncated tail. The "…" must fit inside the cap (never
    produce MAX_BODY_CHARS + 1)."""
    spec = AlertSpec(
        icon=":x:",
        subject_label="x",
        subject="y",
        detail="A" * 600,  # detail alone exceeds the cap
        repeat_state="happening",
        alert_count=1,
    )
    out = format_alert(spec)
    assert len(out) == MAX_BODY_CHARS
    assert out.endswith("…")


def test_format_alert_below_cap_is_unchanged():
    """A short message under the cap is returned verbatim — no
    sneaky reformatting / trimming."""
    spec = AlertSpec(
        icon=":x:",
        subject_label="ok",
        subject="z",
        detail="brief",
        repeat_state="x",
        alert_count=1,
    )
    out = format_alert(spec)
    assert out == ":x: ok: `z` — brief"


def test_format_alert_subject_quoted_with_backticks():
    """Subjects MUST be backtick-quoted so Slack renders them in
    monospace. Operators copy/paste subjects (cron names, UUIDs)
    into shell — the monospace surface preserves whitespace and
    visually distinguishes from prose."""
    out = format_alert(
        AlertSpec(
            icon=":x:",
            subject_label="x",
            subject="cron:weekly_report",
            detail="d",
            repeat_state="x",
            alert_count=1,
        )
    )
    # Backticks present, surrounding the subject only.
    assert "`cron:weekly_report`" in out
    assert "``" not in out  # no double-tick


# ---------- Per-kind wrappers ----------


def test_format_cron_failure_includes_duration_when_present():
    out = format_cron_failure(
        cron_name="cron:weekly_report",
        error_message="RuntimeError: db down",
        duration_ms=1234,
    )
    assert ":rotating_light:" in out
    assert "cron failed" in out
    assert "`cron:weekly_report`" in out
    assert "(1234ms)" in out
    assert "RuntimeError: db down" in out


def test_format_cron_failure_omits_duration_when_none():
    """A failure that crashed before timing started has duration=None.
    Pin that the helper doesn't render "(Noms)" or similar."""
    out = format_cron_failure(
        cron_name="cron:test",
        error_message="boom",
        duration_ms=None,
    )
    assert "ms" not in out
    assert "boom" in out


def test_format_cron_failure_falls_back_for_empty_error():
    """A failed cron with no captured exception message gets a
    placeholder — operators see the cron name + "(no error
    message)" rather than a blank message body."""
    out = format_cron_failure(
        cron_name="cron:test",
        error_message="",
    )
    assert "(no error message)" in out


def test_format_cron_stuck_includes_elapsed_and_multiple():
    """Stuck-cron alert format: "running 142s (~3.2× p95)..."."""
    out = format_cron_stuck(
        cron_name="cron:weekly_report",
        elapsed_ms=142_000,
        p95_ms=44_000,
    )
    assert ":hourglass_flowing_sand:" in out
    assert "cron stuck" in out
    assert "running 142s" in out
    assert "3.2×" in out
    # Drilldown link surfaces so the operator can navigate from
    # Slack to the runs history.
    assert "/admin/crons/cron:weekly_report" in out


def test_format_cron_stuck_handles_zero_p95():
    """If p95=0 (degenerate / no baseline) the multiple is 0×.
    The dispatcher's _is_stuck rule already filters this case
    out, but defensive against direct calls to the formatter."""
    out = format_cron_stuck(
        cron_name="cron:test",
        elapsed_ms=10_000,
        p95_ms=0,
    )
    assert "0.0×" in out  # falls through cleanly without ZeroDivisionError


def test_format_webhook_unhealthy_includes_rate_and_url():
    """W1 wrapper. Pin the partner-facing copy: percentage, attempt
    count, failure count, receiver URL — same shape as the
    existing webhook_health_alerts formatter."""
    out = format_webhook_unhealthy(
        subscription_id="abc-123",
        subscription_url="https://customer.example.com/hook",
        rate=0.67,
        total_attempts=200,
        failed_count=66,
    )
    assert "abc-123" in out
    assert "67%" in out
    assert "200 attempts" in out
    assert "66 failed" in out
    assert "customer.example.com" in out


def test_format_webhook_unhealthy_repeat_label():
    """alert_count=4 → "still unhealthy, 4×" appended to the
    backtick subject."""
    out = format_webhook_unhealthy(
        subscription_id="abc-123",
        subscription_url="https://x/y",
        rate=0.5,
        total_attempts=100,
        failed_count=50,
        alert_count=4,
    )
    assert "still unhealthy, 4×" in out


def test_per_kind_wrappers_obey_500_char_cap():
    """A pathologically-long subscription URL must still produce a
    capped message. Pin so the cap applies uniformly across all
    wrappers, not just the core helper."""
    out = format_webhook_unhealthy(
        subscription_id="x",
        subscription_url="https://" + "a" * 600,
        rate=0.5,
        total_attempts=100,
        failed_count=50,
    )
    assert len(out) <= MAX_BODY_CHARS
