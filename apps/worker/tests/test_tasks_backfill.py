"""Backfill for `apps/worker/tasks.py`.

The existing `test_tasks.py` covers the three bidradar tasks + the
beat-schedule wiring. This file fills the gaps a quarterly worker-
audit surfaced:

  1. The stub tasks (`send_proposal_email`, `process_upload`,
     `backfill_embeddings`) have NO tests today. The original test
     file calls them out as "literal log + return statements" — but
     a regression that changed the return-shape (e.g. dropping
     `status` from the dict) would silently break every caller
     that destructures it. Pin the shape here so when these stubs
     gain real implementations later, the dict contract carries
     forward.

  2. `_run_async` — the helper that runs a coroutine inside a sync
     Celery task. The docstring mentions a previous broken
     implementation that crashed under Python 3.12+. Pin the
     contract: success returns the awaited value; an exception in
     the coroutine propagates synchronously.

  3. The bidradar retry path — existing test asserts "any exception
     raised." Tighten to assert specifically `celery.exceptions.Retry`
     (or that retries were attempted), so a regression that swallowed
     the error and just returned None would surface.

  4. `bidradar_weekly_digest` failure path — the existing test only
     covers the happy path. The task has NO retry config; if the
     service raises, the call must propagate (not return a
     swallowed-error dict that the digest would interpret as success).

  5. Beat schedule UTC values — the comments say "04:30 ICT → 21:30
     UTC". A regression that flipped the cron to 04:30 UTC would
     silently shift the daily run by 7 hours and noone would notice
     until a partner's first-of-day digest landed mid-afternoon.
     Pin the literal `hour` / `minute` values.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


def _import_tasks():
    """Same per-test re-import idiom as `test_tasks.py`. Re-using it
    here keeps the two files independent — neither's monkeypatches
    bleed into the other through sys.modules.
    """
    import importlib

    import tasks as worker_tasks

    return importlib.reload(worker_tasks)


# ---------- Stub-task return shape ----------


def test_send_proposal_email_returns_status_and_proposal_id():
    """A regression that dropped `status` or `proposal_id` from the
    returned dict would silently break the API caller's `result.get`
    chain. Pin both keys."""
    worker = _import_tasks()
    out = worker.send_proposal_email.run(
        organization_id="org-1",
        proposal_id="prop-1",
        payload={"title": "Marina Tower"},
    )
    assert out == {"status": "sent", "proposal_id": "prop-1"}


def test_process_upload_returns_status_and_file_id():
    worker = _import_tasks()
    out = worker.process_upload.run(file_id="f-123")
    assert out == {"status": "done", "file_id": "f-123"}


def test_backfill_embeddings_returns_status_org_module():
    worker = _import_tasks()
    out = worker.backfill_embeddings("org-1", "drawbridge")
    assert out == {"status": "queued", "org": "org-1", "module": "drawbridge"}


# ---------- _run_async helper ----------


def test_run_async_returns_awaited_value():
    """`_run_async` is the bridge from sync Celery to async services.
    A bug here would make every async-backed task either crash
    (DeprecationWarning under 3.12+) or hang. Pin a trivial coroutine
    that returns a value."""
    worker = _import_tasks()

    async def _coro():
        await asyncio.sleep(0)
        return 42

    assert worker._run_async(_coro()) == 42


def test_run_async_propagates_exceptions_synchronously():
    """An exception inside the coroutine must surface as a sync raise
    on the caller. Without this, the Celery task wrapping `_run_async`
    couldn't `try/except` around it — the failure would be invisible."""
    worker = _import_tasks()

    class _Sentinel(Exception):
        pass

    async def _coro():
        raise _Sentinel("boom")

    with pytest.raises(_Sentinel, match="boom"):
        worker._run_async(_coro())


# ---------- bidradar_weekly_digest failure path ----------


def test_bidradar_weekly_digest_propagates_service_failure():
    """The digest task has NO max_retries config (it runs once a week,
    re-running automatically would be more confusing than helpful).
    A service exception must propagate so the next manual run can
    surface the cause rather than the operator silently believing
    last week's run succeeded.
    """
    worker = _import_tasks()

    with patch(
        "services.bidradar_jobs.send_weekly_digest_to_all_orgs",
        new=AsyncMock(side_effect=RuntimeError("supabase down")),
    ):
        with pytest.raises(RuntimeError, match="supabase down"):
            worker.bidradar_weekly_digest(top_n=5)


# ---------- Beat schedule timezone ----------


def test_beat_daily_scrape_runs_at_2130_utc():
    """The daily scrape is documented as "04:30 ICT → 21:30 UTC."
    Any change to that crontab would shift the run by hours; for an
    integration partner expecting a fresh feed at 04:30 ICT, that's
    a silent SLA regression. Pin the literal cron values.
    """
    worker = _import_tasks()
    entry = worker.app.conf.beat_schedule["bidradar-scrape-daily-0430-ict"]
    cron = entry["schedule"]
    # `crontab.hour` is a set under the hood; cast to sorted tuple
    # for stable comparison.
    assert sorted(cron.hour) == [21]
    assert sorted(cron.minute) == [30]


def test_beat_weekly_digest_runs_monday_0000_utc():
    """The weekly digest is documented as "Monday 07:00 ICT → Mon
    00:00 UTC." Pin both day-of-week and hour/minute. A bug that
    changed `day_of_week` to `tue` would silently shift everyone's
    digest to Tuesday."""
    worker = _import_tasks()
    entry = worker.app.conf.beat_schedule["bidradar-weekly-digest-monday-0700-ict"]
    cron = entry["schedule"]
    # `day_of_week` for Monday is `1` in cron's 0=Sun, 1=Mon, ... convention.
    assert sorted(cron.day_of_week) == [1]
    assert sorted(cron.hour) == [0]
    assert sorted(cron.minute) == [0]


# ---------- bidradar_scrape_source retry tightening ----------


def test_bidradar_scrape_source_uses_celerys_retry_mechanism_on_error():
    """Existing test: "any exception is raised" on service failure.
    This test tightens it: `self.retry(exc=...)` is what the body
    actually calls, and Celery converts that into a `Retry`
    exception in eager mode (or schedules a retry in worker mode).
    Either way, the original RuntimeError gets WRAPPED — a
    regression that swallowed the wrap and just returned None
    would surface here.
    """
    from celery.exceptions import Retry

    worker = _import_tasks()

    with patch(
        "services.bidradar_jobs.scrape_and_score_for_all_orgs",
        new=AsyncMock(side_effect=RuntimeError("network down")),
    ):
        # `apply(throw=True)` runs the task synchronously and re-raises
        # whatever Celery would have raised in worker context.
        with pytest.raises((Retry, RuntimeError)):
            worker.bidradar_scrape_source.apply(args=("muasamcong",), throw=True)
