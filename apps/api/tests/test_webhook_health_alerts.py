"""Webhook delivery health alert evaluator (cycle W1).

Pinned seams:
  1. `evaluate_subscription_health` returns `should_alert=False` when
     volume is below the noise threshold (operationally: don't page
     on a subscription with 2 deliveries/week).
  2. Returns `should_alert=True` only when rate < 0.8 AND volume ≥ 10.
  3. Threshold constants match T1's 80% UI badge so the operator
     definition of "unhealthy" is uniform.
  4. `format_alert_message` includes the "still unhealthy, N×"
     repeat label when alert_count >= 2 — same shape as the cron
     failure / stuck alert messages.
"""

from __future__ import annotations

from services.webhook_health_alerts import (
    HealthEvaluation,
    evaluate_subscription_health,
    format_alert_message,
)


# ---------- Threshold constants ----------


def test_thresholds_match_ui_badge():
    """The 80% badge tone in T1's frontend MUST match this 80%
    alert threshold so a partner who sees a green pill in the UI
    isn't simultaneously paging ops."""
    from services.webhook_health_alerts import (
        _MIN_VOLUME_FOR_SIGNAL,
        _UNHEALTHY_RATE_THRESHOLD,
    )

    assert _UNHEALTHY_RATE_THRESHOLD == 0.8
    # 10 deliveries is the smallest credible "real activity" window
    # for the 7d cadence — below this, rate is too noisy.
    assert _MIN_VOLUME_FOR_SIGNAL == 10


# ---------- evaluate_subscription_health ----------


def test_below_volume_threshold_does_not_alert():
    """3 delivered + 2 failed = 5 terminal < 10. Don't page."""
    out = evaluate_subscription_health(delivered=3, failed=2)
    assert out.should_alert is False
    assert out.reason == "insufficient_volume"
    # Rate is intentionally None (not 0.0) — there's no meaningful
    # rate to report below the threshold.
    assert out.rate is None


def test_zero_deliveries_does_not_alert():
    """A brand-new subscription with 0 attempts is healthy by
    default — no alert. Pin the boundary."""
    out = evaluate_subscription_health(delivered=0, failed=0)
    assert out.should_alert is False
    assert out.reason == "insufficient_volume"


def test_healthy_above_threshold_does_not_alert():
    """100 delivered + 5 failed = 95.2% rate over 105 attempts.
    Healthy, no alert."""
    out = evaluate_subscription_health(delivered=100, failed=5)
    assert out.should_alert is False
    assert out.reason == "healthy"
    assert abs(out.rate - 100 / 105) < 0.0001


def test_at_exact_threshold_does_not_alert():
    """Rate == 0.8 → still healthy (>=). Pin the boundary."""
    # 80 delivered + 20 failed = 80% rate, 100 attempts.
    out = evaluate_subscription_health(delivered=80, failed=20)
    assert out.should_alert is False
    assert out.reason == "healthy"
    assert out.rate == 0.8


def test_below_threshold_with_volume_alerts():
    """40 delivered + 60 failed = 40% rate over 100 attempts.
    Volume threshold hit AND rate below — the page-worthy case."""
    out = evaluate_subscription_health(delivered=40, failed=60)
    assert out.should_alert is True
    assert out.reason == "below_threshold"
    assert out.rate == 0.4
    assert out.total_terminal == 100
    assert out.delivered == 40
    assert out.failed == 60


def test_just_below_threshold_alerts():
    """79 delivered + 21 failed = 79% rate. Just below 80%, alerts."""
    out = evaluate_subscription_health(delivered=79, failed=21)
    assert out.should_alert is True


def test_volume_threshold_with_failure():
    """At the volume threshold (10) with failures bringing the rate
    below 80% — must alert. Pin the boundary."""
    # 7 delivered + 3 failed = 70% rate, 10 attempts.
    out = evaluate_subscription_health(delivered=7, failed=3)
    assert out.should_alert is True
    assert out.total_terminal == 10
    assert out.rate == 0.7


# ---------- format_alert_message ----------


def test_message_includes_subscription_id_and_url():
    """The Slack body must surface the subscription id (for cross-
    referencing in /admin/webhook-deliveries) AND the receiver URL
    (for "is the customer's domain still up?")."""
    e = HealthEvaluation(
        should_alert=True,
        rate=0.67,
        total_terminal=200,
        delivered=134,
        failed=66,
        reason="below_threshold",
    )
    msg = format_alert_message(
        subscription_id="abc-123",
        subscription_url="https://customer.example.com/hook",
        evaluation=e,
    )
    assert "abc-123" in msg
    assert "customer.example.com" in msg
    assert "67%" in msg
    assert "200 attempts" in msg
    assert "66 failed" in msg


def test_message_includes_repeat_label_for_re_alerts():
    """alert_count >= 2 → "still unhealthy, N×" appended. Mirrors
    the cron failure / stuck alert framing so operators see the
    incident is ongoing."""
    e = HealthEvaluation(
        should_alert=True,
        rate=0.5,
        total_terminal=100,
        delivered=50,
        failed=50,
        reason="below_threshold",
    )
    msg_first = format_alert_message(
        subscription_id="abc-123",
        subscription_url="https://x.io/h",
        evaluation=e,
        alert_count=1,
    )
    msg_third = format_alert_message(
        subscription_id="abc-123",
        subscription_url="https://x.io/h",
        evaluation=e,
        alert_count=3,
    )
    assert "still unhealthy" not in msg_first
    assert "still unhealthy, 3×" in msg_third


def test_message_caps_at_500_chars():
    """Slack body cap is 40000 but mobile preview ~144. We cap at
    500 for readability — same idiom as cron alert messages."""
    e = HealthEvaluation(
        should_alert=True,
        rate=0.1,
        total_terminal=1000,
        delivered=100,
        failed=900,
        reason="below_threshold",
    )
    # Long URL (~600 chars) → message would exceed 500 without cap.
    long_url = "https://customer.example.com/" + "a" * 600
    msg = format_alert_message(
        subscription_id="abc-123",
        subscription_url=long_url,
        evaluation=e,
    )
    assert len(msg) <= 500
    assert msg.endswith("…")
