"""Pin every arq cron's schedule by name.

Why this exists: a typo in `cron(weekly_report_cron, day_of_week=0)`
(arq accepts unknown kwargs silently and the cron then runs at the
default — every minute, or never, depending on the field) would
silently break the schedule for everyone. Customers wouldn't notice
until the weekly digest stops arriving on Mondays. By then we're
days into the failure window.

This test exercises `WorkerSettings.cron_jobs` directly — it doesn't
need a Redis connection, doesn't actually fire any cron, and doesn't
depend on the wall-clock time. It just asserts that the schedule
each cron is registered with matches the documented intent.

If you intentionally change a cron's schedule, update the matching
`expected = …` row here in the same PR. That's the explicit signal
that the change is a behaviour-shift, not a typo.
"""

from __future__ import annotations

from typing import Any

import pytest

from workers.queue import WorkerSettings


def _by_coroutine_name(cron_jobs: list[Any]) -> dict[str, Any]:
    """Index `WorkerSettings.cron_jobs` by underlying coroutine name.

    `arq.cron.CronJob.name` is `"cron:<func.__name__>"` — we strip
    the prefix so each test can assert on a clean function name.
    Returns a dict so a forgotten cron raises KeyError loudly.
    """
    out: dict[str, Any] = {}
    for c in cron_jobs:
        # `c.name` is e.g. "cron:weekly_report_cron"
        bare = c.name.removeprefix("cron:")
        # Two crons sharing a name would silently overwrite — make
        # that an explicit failure rather than a silent dedup.
        assert bare not in out, f"duplicate cron name: {bare}"
        out[bare] = c
    return out


@pytest.fixture(scope="module")
def crons() -> dict[str, Any]:
    return _by_coroutine_name(WorkerSettings.cron_jobs)


# ---------- Per-cron schedule pins ----------


def test_weekly_report_cron_runs_monday_06_utc(crons):
    """Weekly report fires every Monday at 06:00 UTC (~13:00 ICT).

    The Monday-morning timing means the report covers the calendar
    week that JUST ended (Sun→Sat). A typo to `weekday="sun"` would
    shift coverage by a day; a typo dropping `weekday` entirely would
    fire daily and spam every user 7×.
    """
    c = crons["weekly_report_cron"]
    assert c.weekday == "mon"
    assert c.hour == 6
    assert c.minute == 0


def test_price_alerts_cron_runs_nightly_22_utc(crons):
    """Price-alerts evaluation runs once a day at 22:00 UTC
    (~05:00 ICT). The pre-business-hours timing means alerts are
    in inboxes when the team starts — not pinging mid-day."""
    c = crons["price_alerts_evaluate_job"]
    # No `weekday` → fires every day. Pin the absence (None) so a
    # future "let's only run weekdays" change has to flip this test.
    assert c.weekday is None
    assert c.hour == 22
    assert c.minute == 0


def test_scrape_all_prices_runs_2nd_of_month_01_utc(crons):
    """Province price-bulletin scrape: 2nd of each month at 01:00 UTC
    (~08:00 ICT). Most provinces publish the prior month's bulletin
    by the 1st-2nd; running on the 2nd gives the slowest provinces
    one extra day to publish before our scrape misses the cycle.

    A `day=1` typo would scrape too early and miss late-publishing
    provinces; `day=15` would unnecessarily delay the data by 2 weeks.
    """
    c = crons["scrape_all_prices_job"]
    assert c.day == 2
    assert c.hour == 1
    assert c.minute == 0


def test_daily_activity_digest_cron_runs_midnight_utc(crons):
    """Daily activity digest fires at 00:00 UTC (~07:00 ICT) — lands
    in inboxes before the workday in Vietnam. A typo to `hour=12`
    would land at 19:00 ICT (after-hours), defeating the purpose."""
    c = crons["daily_activity_digest_cron"]
    assert c.weekday is None
    assert c.hour == 0
    assert c.minute == 0


def test_rfq_deadlines_cron_runs_daily_01_utc(crons):
    """RFQ slot expiry fires at 01:00 UTC (~08:00 ICT) — one hour
    after the digest so a buyer's morning email reflects already-
    expired slots, not stale ones. The 1-day grace inside the cron
    body means a Sunday evening submission still counts on Monday.
    """
    c = crons["rfq_deadlines_cron"]
    assert c.weekday is None
    assert c.hour == 1
    assert c.minute == 0


def test_webhook_drain_cron_runs_every_minute(crons):
    """Webhook outbox drain fires every minute. The minute-cadence
    is the floor on retry latency for a flaky receiver — going
    coarser (every 5 min) would mean a 4-minute delay on the first
    retry, which customer integrations would notice.

    arq spells "every minute" as `minute={0..59}`. A future "let's
    drain every 5 minutes to save Redis traffic" change has to flip
    this test — that's the explicit cost-vs-latency tradeoff.
    """
    c = crons["webhook_drain_cron"]
    # `minute` is a set of explicit minutes when the cron fires.
    # Full set = every minute of the hour.
    assert c.minute == set(range(60))


def test_retention_prune_cron_runs_daily_03_utc(crons):
    """Retention prune fires at 03:00 UTC (~10:00 ICT). Picked the
    quietest customer-facing window — not midnight (digest), not
    01:00 (RFQ deadlines), not 22:00 (price alerts). The job is
    bounded by `_MAX_PRUNE_ROWS_PER_RUN` so even a backed-up tenant
    can't lock the table for minutes."""
    c = crons["retention_prune_cron"]
    assert c.weekday is None
    assert c.hour == 3
    assert c.minute == 0


def test_codeguard_quota_reconcile_cron_runs_monday_04_utc(crons):
    """CodeGuard quota drift reconciliation: weekly Monday at 04:00 UTC
    (~11:00 ICT). Weekly cadence chosen because drift is attribution
    loss (org-level vs per-user usage), not hot-path correctness —
    waiting up to 7 days for reconciliation is acceptable. A typo
    to daily would 7× the read load on the quota tables."""
    c = crons["codeguard_quota_reconcile_cron"]
    assert c.weekday == "mon"
    assert c.hour == 4
    assert c.minute == 0


def test_cron_failure_watchdog_cron_runs_every_5_minutes(crons):
    """Cron-failure + stuck-cron watchdog. The 5-minute cadence is
    LOAD-BEARING — it MUST equal
    `services.cron_alerts._FRESH_FAILURE_WINDOW_MINUTES` so the
    failure-lookback window tiles cleanly with the cron tick.

    Mismatched values silently drop alerts (cadence > window) or
    double-alert (cadence < window). The cross-pin in
    `tests/test_cron_alerts_watchdog_pin.py::test_watchdog_cron_runs_every_5_minutes`
    asserts the same cadence from the other side; both have to move
    together if the cadence ever changes.

    arq spells "every 5 minutes" as `minute={0, 5, 10, ..., 55}` —
    the full multiples-of-5 set within an hour.
    """
    c = crons["cron_failure_watchdog_cron"]
    assert c.minute == set(range(0, 60, 5)), (
        f"cron_failure_watchdog_cron.minute drifted to {c.minute}; "
        "want set(range(0, 60, 5)). The 5-minute cadence is LOAD-"
        "BEARING — see _FRESH_FAILURE_WINDOW_MINUTES in services.cron_alerts."
    )


# ---------- Coverage / no-orphans ----------


def test_every_registered_cron_has_a_test(crons):
    """Sanity: every cron in `WorkerSettings.cron_jobs` must be
    asserted on by name above. A new cron added without a matching
    schedule pin would mean the next typo on it goes unnoticed.

    Update this set in the same PR that adds a new cron + a
    `test_<name>_runs_…` function above.
    """
    pinned = {
        "weekly_report_cron",
        "price_alerts_evaluate_job",
        "scrape_all_prices_job",
        "daily_activity_digest_cron",
        "rfq_deadlines_cron",
        "webhook_drain_cron",
        "retention_prune_cron",
        "codeguard_quota_reconcile_cron",
        "cron_failure_watchdog_cron",
    }
    actual = set(crons.keys())
    missing = actual - pinned
    extra = pinned - actual
    assert not missing, f"unpinned crons (add a test): {missing}"
    assert not extra, f"pin references a cron that no longer exists: {extra}"
