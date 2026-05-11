"""Webhook delivery health alert evaluator (cycle W1).

Pure-helper module. Given per-subscription 7-day delivery counts
(delivered, failed, total), decides whether the subscription is
"unhealthy" enough to warrant a Slack alert.

Decision rule:

  * `total < _MIN_VOLUME_FOR_SIGNAL` — too few deliveries for the
    rate to be a reliable signal. Skip (no alert).
    A receiver with 2 deliveries and 1 failure is at 50% rate; a
    receiver with 2,000 deliveries at 50% is a real outage. Don't
    page on the former.
  * `rate >= _UNHEALTHY_RATE_THRESHOLD` — healthy enough; no alert.
  * Otherwise — return an alert payload that the cron pipes into
    `should_emit_alert(kind='webhook_unhealthy', cron_name=str(sub_id))`
    for dedup-aware emission via the R3 ratchet.

Why thresholds as module-level constants:
  * `_MIN_VOLUME_FOR_SIGNAL` = 10 — under this, the rate is too
    noisy to alert on. A subscription pushing 2 deliveries/week is
    fine to fail occasionally; a subscription pushing 500/week
    failing 50% is an outage.
  * `_UNHEALTHY_RATE_THRESHOLD` = 0.8 — matches T1's amber-tone
    threshold on the partner-facing badge. Same number = same
    operator definition of "unhealthy" across UI + Slack.

Why the kind is `webhook_unhealthy` (not `webhook_failure`):
  * `cron_failure` already exists in R3's ALERT_KINDS for cron
    crashes. `webhook_unhealthy` keeps the dedup table's
    (cron_name, kind) PK from accidentally colliding with a
    cron whose name happens to match a UUID.
  * Reads naturally in Slack: "webhook subscription
    abc-123 unhealthy: 67% delivery rate over 7d (320 attempts)."

Pure Python — no DB, no async, no external services. The cron caller
runs the SQL and feeds the results into `evaluate_subscription_health`
per-subscription.
"""

from __future__ import annotations

from dataclasses import dataclass

# Below this attempt count, the rate is too noisy to alert on. A
# subscription pushing <10 deliveries in 7d either: (a) is freshly
# created, (b) belongs to a low-activity tenant. Either way, false
# alerts here are noisy without operational value.
_MIN_VOLUME_FOR_SIGNAL = 10

# Match T1's badge threshold so "amber pill" + "Slack alert" surface
# the same operator definition of unhealthy.
_UNHEALTHY_RATE_THRESHOLD = 0.8


@dataclass(frozen=True)
class HealthEvaluation:
    """Per-subscription evaluation result.

    `should_alert` is the boolean the cron acts on. The other fields
    feed into the Slack message body so the alert reads as
    "subscription <name>: 67% rate over 7d (320 attempts)."
    """

    should_alert: bool
    rate: float | None
    total_terminal: int
    delivered: int
    failed: int
    # Reason code from a closed vocabulary so the cron's logging
    # stays grep-friendly.
    reason: str  # "healthy" | "below_threshold" | "insufficient_volume"


def evaluate_subscription_health(
    *,
    delivered: int,
    failed: int,
) -> HealthEvaluation:
    """Pure decision: should this subscription alert based on its
    7d counters?

    `delivered` + `failed` is the terminal-delivery count. Pending /
    in-flight rows are intentionally excluded from the rate
    denominator (consistent with T1's rate calculation: "what
    eventually went through").

    Returns a `HealthEvaluation` the caller turns into Slack copy
    via `format_alert_message`.
    """
    total = delivered + failed
    if total < _MIN_VOLUME_FOR_SIGNAL:
        return HealthEvaluation(
            should_alert=False,
            rate=None,  # not enough data to compute meaningful rate
            total_terminal=total,
            delivered=delivered,
            failed=failed,
            reason="insufficient_volume",
        )

    rate = delivered / total if total > 0 else 0.0
    if rate >= _UNHEALTHY_RATE_THRESHOLD:
        return HealthEvaluation(
            should_alert=False,
            rate=rate,
            total_terminal=total,
            delivered=delivered,
            failed=failed,
            reason="healthy",
        )

    return HealthEvaluation(
        should_alert=True,
        rate=rate,
        total_terminal=total,
        delivered=delivered,
        failed=failed,
        reason="below_threshold",
    )


def format_alert_message(
    *,
    subscription_id: str,
    subscription_url: str,
    evaluation: HealthEvaluation,
    alert_count: int = 1,
) -> str:
    """Slack message for an unhealthy subscription.

    Format mirrors the cron-failure / cron-stuck message shapes —
    rotating-light icon, backtick-quoted identifier, terse stats,
    optional repeat-counter for re-alerts.

    `alert_count >= 2` (R3's repeat path): appends "(still
    unhealthy, 3×)" so operators see this is an ongoing incident
    rather than a fresh trip.

    Truncated at 500 chars for Slack mobile readability — same cap
    as `_format_alert` in cron_alerts.
    """
    rate_pct = int(round((evaluation.rate or 0.0) * 100))
    repeat_label = ""
    if alert_count >= 2:
        repeat_label = f" (still unhealthy, {alert_count}×)"
    msg = (
        f":rotating_light: webhook unhealthy: `{subscription_id}`"
        f"{repeat_label} — {rate_pct}% delivery rate over 7d "
        f"({evaluation.total_terminal} attempts, {evaluation.failed} failed). "
        f"Receiver: {subscription_url}"
    )
    if len(msg) > 500:
        return msg[:499] + "…"
    return msg
