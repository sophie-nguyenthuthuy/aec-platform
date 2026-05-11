"""Cron-failure watchdog — surfaces fresh `cron_runs` failures to
Slack so ops doesn't have to refresh `/admin/crons` to find out a
cron broke.

Pairs with `services.cron_telemetry` (the writer): the wrapper writes
a row to `cron_runs` on every invocation; this watchdog reads them
back and alerts on fresh failures.

Why not call `send_slack` directly from the cron decorator:
  * The decorator runs in the worker, mid-cron. Adding an outbound
    Slack call there would couple every cron's success path to
    Slack's availability — a Slack outage would slow every cron.
  * Failure-alerting belongs in a separate, slow-cadence loop
    (every 5 min) where the latency budget is generous.

Dedup contract:
  * The watchdog runs every 5 min and looks at failures whose
    `started_at >= NOW() - INTERVAL '5 minutes'`. Consecutive
    invocations look at non-overlapping 5-min windows, so a single
    failure produces a single alert.
  * Race window at the boundary: a cron failing exactly at the tick
    AND the watchdog firing simultaneously could double-alert. The
    rate is low enough we don't engineer around it; if a customer
    notices duplicate alerts during incident retros, add a
    `cron_alerts_sent` table with (cron_name, run_id) UNIQUE.

Why not "consecutive N failures" semantics:
  * v1 alerts on every fresh failure. Simpler. A flaky-once cron
    that recovers on its own retry will produce one alert + one
    "succeeded" row that closes the loop in the dashboard.
  * If alert volume becomes noisy (some cron flakes nightly), bump
    the watchdog window or add the consecutive-N filter — both are
    one-line changes here.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from db.session import AdminSessionFactory

logger = logging.getLogger(__name__)


# Window for "fresh" failures — must match the watchdog cron's tick
# interval exactly, otherwise we either miss failures (window <
# tick) or double-alert (window > tick). The watchdog runs every 5
# min in `workers.queue.WorkerSettings.cron_jobs`; if the cadence
# changes, update both here AND there in the same commit.
_FRESH_FAILURE_WINDOW_MINUTES = 5


# Slack `kind` for `record_delivery_attempt`. Surfaces these in
# `/admin/slack-deliveries` filtered by kind so ops can see "is the
# alerter itself healthy".
_KIND = "cron_failure"


async def check_failing_crons() -> dict[str, Any]:
    """Query `cron_runs` for fresh failures, send one Slack message
    per cron that failed, return a summary.

    Returns:
        {"checked": int, "alerted": int, "skipped": int}
            * checked = number of distinct crons in the failure window
            * alerted = number of Slack messages successfully sent
            * skipped = checked - alerted (Slack not configured, or
              transport failed — the failure-of-the-alerter is
              recorded in slack_deliveries either way)

    Idempotent within a 5-min window: the SQL filter is
    `started_at >= NOW() - INTERVAL '5 minutes'`, which matches the
    watchdog's tick interval. Two watchdog instances running
    concurrently (e.g. during a deploy) might both alert on the same
    failure — that's an acceptable trade vs. the complexity of a
    UNIQUE-on-(cron_name, run_id) dedup table.
    """
    rows = await _fresh_failures()
    summary: dict[str, int] = {"checked": len(rows), "alerted": 0, "skipped": 0}

    if not rows:
        return summary

    # Lazy imports — services/slack* pull httpx + the settings cache.
    # Importing at module-load would couple every cron-telemetry
    # caller to those modules even when no failures are present.
    from services.slack import send_slack
    from services.slack_telemetry import record_delivery_attempt

    for row in rows:
        text_msg = _format_alert(row)
        result = await send_slack(text=text_msg)
        # Record EVERY attempt, even when delivered=False — the
        # `/admin/slack-deliveries` dashboard then shows "watchdog
        # tried but Slack is down" alongside "watchdog succeeded".
        await record_delivery_attempt(
            kind=_KIND,
            text=text_msg,
            result=result,
        )
        if result.get("delivered"):
            summary["alerted"] += 1
        else:
            summary["skipped"] += 1
            logger.warning(
                "cron_alerts: skipped Slack send for %s — %s",
                row["cron_name"],
                result.get("reason"),
            )

    return summary


async def _fresh_failures() -> list[dict[str, Any]]:
    """One row per cron whose LATEST run within the lookback failed.

    Uses DISTINCT ON to collapse multi-failure crons (e.g. a cron that
    runs every minute and has been failing for 4 of the last 5
    minutes) into a single alert per cron — rather than hammering
    Slack with five identical messages.

    Index path: `(cron_name, started_at DESC)` from migration 0042
    makes this an index-only scan, bounded by the registry size
    (~10 crons).
    """
    sql = text(
        f"""
        SELECT DISTINCT ON (cron_name)
            cron_name,
            id,
            started_at,
            finished_at,
            status,
            duration_ms,
            error_message
        FROM cron_runs
        WHERE started_at >= NOW() - INTERVAL '{_FRESH_FAILURE_WINDOW_MINUTES} minutes'
        ORDER BY cron_name, started_at DESC
        """
    )
    async with AdminSessionFactory() as session:
        rows = (await session.execute(sql)).mappings().all()

    # Return only the failures. We could push this into the SQL via
    # `WHERE status = 'failed'` BUT then DISTINCT ON would skip a
    # "failed → succeeded → failed" sequence's interim recovery —
    # we want the last_status, not the last_failure. Filter in Python.
    return [dict(r) for r in rows if r["status"] == "failed"]


def _format_alert(row: dict[str, Any]) -> str:
    """One-line Slack message that fits in mobile notification preview.

    Format: `:rotating_light: cron failed: <name> — <error>` truncated
    so the Slack notification preview shows the cron name and the
    first chunk of the error. Slack's preview cap is ~144 chars on
    mobile.
    """
    error = row.get("error_message") or "(no error message)"
    duration_ms = row.get("duration_ms")
    duration_str = f" ({duration_ms}ms)" if duration_ms is not None else ""
    cron_name = row["cron_name"]
    msg = f":rotating_light: cron failed: `{cron_name}`{duration_str} — {error}"
    # Slack message body cap is 40000 chars; we cap aggressively for
    # readability. The full error sits in `cron_runs` already; the
    # alert is the heads-up.
    if len(msg) > 500:
        return msg[:499] + "…"
    return msg


# ---------- Stuck-cron detection -----------------------------------
#
# A cron stuck in `running` (worker crashed mid-run, deadlocked SQL,
# infinite loop) sits there forever. The status pill on `/admin/crons`
# shows "running" until the next watchdog tick or the next cron
# instance overlaps — neither is a reliable failure signal.
#
# Detection: per-cron rolling p95 of successful-run duration over the
# last 7 days. Any `running` row whose elapsed time exceeds 3 × p95
# is flagged as stuck. Why 3×:
#   * Healthy crons cluster within 2× p95 even on a slow day.
#   * 3× ignores a slow-but-progressing run while still flagging a
#     truly hung one (the typical "10× expected" heuristic catches the
#     same cases but with more lag — a cron whose p95 is 1m would
#     have to run 10m before alerting; 3× = 3m alert, faster MTTR).
# Why p95 not p99: p99 over a 7d window is dominated by the single
# worst run; p95 is the natural "this is what 'normal' looks like"
# cluster, which is what we want to compare against.
#
# Why 7d window: the platform has weekly crons (weekly_report,
# codeguard_quota_reconcile) that fire once. A shorter window
# wouldn't have any samples for those. 7d guarantees ≥1 sample for
# every cadence in `WorkerSettings.cron_jobs`.

# A cron with fewer than this many successful samples in the window
# is treated as "no baseline yet" — the stuck check is skipped
# (returning False from `is_stuck_run`). Two reasons:
#   * p95 over 1 sample is just that sample's value — a cron that
#     genuinely takes a long time first run would falsely flag.
#   * A brand-new cron added in this deploy hasn't had time to
#     accumulate baseline samples — alerting on its very first run
#     is noise.
# 3 samples is the smallest credible "this is repeatable behaviour."
_MIN_SAMPLES_FOR_BASELINE = 3

# How many multiples of the rolling p95 the current run must exceed
# to be flagged stuck. See module docstring for the 3× rationale.
_STUCK_MULTIPLIER = 3.0

# Rolling-baseline window in days. Must be ≥ the longest cron
# interval (weekly_report = 7d) so every registered cron has at
# least one sample.
_BASELINE_WINDOW_DAYS = 7


async def check_stuck_crons() -> dict[str, Any]:
    """Find `running` cron_runs rows that have run longer than
    3× the cron's 7-day p95.

    Returns:
        {"checked": int, "stuck": int, "alerted": int}
            * checked = number of running rows examined
            * stuck = number flagged as stuck (running × elapsed >
              3× p95)
            * alerted = Slack messages successfully sent

    Pairs with `check_failing_crons` — that watchdog covers the
    "ran and failed" case; this one covers the "started and never
    finished" case. Both run in the every-5-minute watchdog cron;
    keeping them in the same module + tick avoids the divergence
    risk of independent schedules.
    """
    rows = await _running_crons_with_baseline()
    summary: dict[str, int] = {"checked": len(rows), "stuck": 0, "alerted": 0}

    if not rows:
        return summary

    from services.slack import send_slack
    from services.slack_telemetry import record_delivery_attempt

    for row in rows:
        if not _is_stuck(row):
            continue
        summary["stuck"] += 1
        text_msg = _format_stuck_alert(row)
        result = await send_slack(text=text_msg)
        await record_delivery_attempt(
            kind="cron_stuck",  # distinct from `cron_failure` so the
            # /admin/slack-deliveries dashboard
            # filter cleanly separates them
            text=text_msg,
            result=result,
        )
        if result.get("delivered"):
            summary["alerted"] += 1
        else:
            logger.warning(
                "cron_alerts: stuck-cron Slack send failed for %s — %s",
                row["cron_name"],
                result.get("reason"),
            )

    return summary


async def _running_crons_with_baseline() -> list[dict[str, Any]]:
    """Pull every currently-running cron_runs row plus the rolling
    p95-duration of its successful runs over the baseline window.

    One query joins:
      * The current `running` rows (small set: ≤ 1 per registered
        cron in steady state).
      * `percentile_cont` over each cron's successful runs in the
        window — PG-native, no Python sort needed.

    Returns rows that already include `baseline_p95_ms` so
    `_is_stuck` is a pure function.
    """
    sql = text(
        f"""
        WITH baseline AS (
            -- One row per cron_name with the rolling p95.
            SELECT
                cron_name,
                COUNT(*) AS sample_count,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                    AS p95_ms
            FROM cron_runs
            WHERE status = 'succeeded'
              AND duration_ms IS NOT NULL
              AND started_at >= NOW()
                  - INTERVAL '{_BASELINE_WINDOW_DAYS} days'
            GROUP BY cron_name
        ),
        running AS (
            -- Currently-executing rows. status='running' AND
            -- finished_at IS NULL — both predicates because a row
            -- could in theory be left in 'running' status by a
            -- crashed wrapper before finished_at gets set; the
            -- explicit NULL check makes that case still surface here.
            SELECT
                id,
                cron_name,
                started_at,
                EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000
                    AS elapsed_ms
            FROM cron_runs
            WHERE status = 'running'
              AND finished_at IS NULL
        )
        SELECT
            r.id,
            r.cron_name,
            r.started_at,
            r.elapsed_ms,
            b.sample_count,
            b.p95_ms
        FROM running r
        LEFT JOIN baseline b ON b.cron_name = r.cron_name
        """
    )
    async with AdminSessionFactory() as session:
        rows = (await session.execute(sql)).mappings().all()
    return [dict(r) for r in rows]


def _is_stuck(row: dict[str, Any]) -> bool:
    """Pure-function decision rule: is this running row stuck?

    Three guards:
      1. Skip if the cron has no baseline yet — first runs aren't
         alertable.
      2. Skip if the baseline has < `_MIN_SAMPLES_FOR_BASELINE` —
         too noisy to alert on.
      3. Otherwise: stuck iff elapsed > multiplier × p95.

    Returning False on insufficient data is the conservative choice —
    a missed alert is recoverable (next watchdog tick has more
    samples), a false alert wakes someone up at 3am for nothing.
    """
    sample_count = row.get("sample_count")
    if sample_count is None or sample_count < _MIN_SAMPLES_FOR_BASELINE:
        return False
    p95_ms = row.get("p95_ms")
    if p95_ms is None or p95_ms <= 0:
        # p95 of 0 (every successful run took 0ms — usually a no-op
        # cron with no real work) → multiplier × 0 = 0 → every run
        # would be flagged. Skip. Operators bored enough to alert
        # on no-op crons can configure something else.
        return False
    elapsed_ms = float(row.get("elapsed_ms") or 0)
    return elapsed_ms > _STUCK_MULTIPLIER * float(p95_ms)


def _format_stuck_alert(row: dict[str, Any]) -> str:
    """Mobile-preview-sized Slack message for a stuck cron."""
    cron_name = row["cron_name"]
    elapsed_ms = int(row.get("elapsed_ms") or 0)
    p95_ms = int(row.get("p95_ms") or 0)
    elapsed_s = elapsed_ms / 1000.0
    multiple = elapsed_ms / p95_ms if p95_ms else 0
    msg = (
        f":hourglass_flowing_sand: cron stuck: `{cron_name}` running "
        f"{elapsed_s:.0f}s (~{multiple:.1f}× p95). Worker may have "
        f"crashed mid-run; check `/admin/crons/{cron_name}` for the "
        f"row id."
    )
    if len(msg) > 500:
        return msg[:499] + "…"
    return msg


__all__ = [
    "check_failing_crons",
    "check_stuck_crons",
]
