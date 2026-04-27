"""Smoke tests for the Celery task wiring in `apps/worker/tasks.py`.

What we cover
-------------
* The 3 BIDRADAR tasks — these are the only worker tasks with real glue
  (the others are stubs that just log + return a canned dict).
* The Celery Beat schedule — assert the two cron entries point at the
  task names that actually exist on `app.tasks`. Drift here would make
  the scheduler enqueue a task that doesn't exist, with the worker
  silently logging "received unknown task" and the run never happening.

What we don't cover
-------------------
* Network behaviour of `services.bidradar_jobs` — its scrapers hit
  external sites; covered separately in `apps/api/tests` via per-source
  unit tests.
* The 3 stub tasks (`send_proposal_email`, `process_upload`,
  `backfill_embeddings`) — they're literal log + return statements;
  testing them would just assert the log message.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _import_tasks():
    """Import the worker module fresh per-test.

    Celery registers tasks on the global `app.tasks` registry at import
    time. Importing once at module top would pin a cached module in
    sys.modules and any monkeypatch.setattr the tests do would race
    other tests that import in a different order. Re-importing per-call
    keeps the patches local.
    """
    import importlib

    import tasks as worker_tasks

    return importlib.reload(worker_tasks)


# ---------------------------------------------------------------------
# bidradar_scrape_source
# ---------------------------------------------------------------------


def test_bidradar_scrape_source_calls_service_and_returns_result():
    worker = _import_tasks()

    fake_result = {"scraped": 12, "matched_orgs": 4}
    with patch(
        "services.bidradar_jobs.scrape_and_score_for_all_orgs",
        new=AsyncMock(return_value=fake_result),
    ) as svc:
        # `bind=True` means the task expects `self` as the first arg —
        # `.run(*args, **kwargs)` skips Celery's binding and invokes the
        # underlying function directly. That's what we want for unit
        # testing — no broker, no worker process.
        out = worker.bidradar_scrape_source.run("muasamcong", max_pages=3)

    assert out == fake_result
    svc.assert_awaited_once_with(source="muasamcong", max_pages=3)


def test_bidradar_scrape_source_retries_on_service_error():
    worker = _import_tasks()

    with patch(
        "services.bidradar_jobs.scrape_and_score_for_all_orgs",
        new=AsyncMock(side_effect=RuntimeError("network down")),
    ):
        # The bound task calls `self.retry(exc=exc)` on failure. Celery
        # raises a `Retry` exception when retries remain, or re-raises
        # the original on max-out. Either way, the call should not
        # return a value.
        try:
            worker.bidradar_scrape_source.apply(args=("muasamcong",), throw=True)
        except Exception as exc:
            # Either `celery.exceptions.Retry` (retries left) or the
            # original `RuntimeError` (retries exhausted in eager mode).
            # Both confirm the task didn't swallow the failure.
            assert exc is not None
        else:
            raise AssertionError("expected the task to raise on service error")


# ---------------------------------------------------------------------
# bidradar_scrape_all (fan-out)
# ---------------------------------------------------------------------


def test_bidradar_scrape_all_enqueues_one_per_source():
    worker = _import_tasks()

    delays: list[tuple] = []

    def _capture_delay(*args, **kwargs):
        delays.append((args, kwargs))
        # Celery's .delay() returns an AsyncResult; tests don't read it.
        return MagicMock(id="fake-job-id")

    with patch.object(worker.bidradar_scrape_source, "delay", side_effect=_capture_delay):
        out = worker.bidradar_scrape_all(max_pages=7)

    # One enqueue per supported source, all with the requested max_pages.
    assert len(delays) == len(worker._BIDRADAR_SOURCES)
    enqueued_sources = [args[0] for args, _ in delays]
    assert sorted(enqueued_sources) == sorted(worker._BIDRADAR_SOURCES)
    for args, _ in delays:
        assert args[1] == 7

    assert out == {"enqueued": worker._BIDRADAR_SOURCES, "max_pages": 7}


# ---------------------------------------------------------------------
# bidradar_weekly_digest
# ---------------------------------------------------------------------


def test_bidradar_weekly_digest_calls_service():
    worker = _import_tasks()

    fake_result = {"orgs_emailed": 3}
    with patch(
        "services.bidradar_jobs.send_weekly_digest_to_all_orgs",
        new=AsyncMock(return_value=fake_result),
    ) as svc:
        out = worker.bidradar_weekly_digest(top_n=10)

    assert out == fake_result
    svc.assert_awaited_once_with(top_n=10)


# ---------------------------------------------------------------------
# Beat schedule wiring
# ---------------------------------------------------------------------


def test_beat_schedule_points_at_registered_task_names():
    """The Beat scheduler enqueues by task NAME (string lookup against
    `app.tasks`). If a task name in `beat_schedule` doesn't exist on the
    registry — typo, rename, file split — the scheduler logs "received
    unknown task" once a tick and the cron silently never runs. Cheap
    drift detector.
    """
    worker = _import_tasks()

    schedule = worker.app.conf.beat_schedule
    registered = set(worker.app.tasks.keys())

    expected_keys = {
        "bidradar-scrape-daily-0430-ict",
        "bidradar-weekly-digest-monday-0700-ict",
    }
    assert expected_keys.issubset(schedule.keys()), (
        f"missing beat entries: {expected_keys - schedule.keys()}"
    )

    for entry_key, entry in schedule.items():
        task_name = entry["task"]
        assert task_name in registered, (
            f"beat entry {entry_key!r} points at unknown task {task_name!r}; "
            f"registered: {sorted(t for t in registered if not t.startswith('celery.'))}"
        )
