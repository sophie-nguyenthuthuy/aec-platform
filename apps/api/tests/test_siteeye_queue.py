"""Smoke tests for the SiteEye worker queue.

Covers the upload → enqueue → analyze → report chain:
  * `enqueue_photo_analysis` / `enqueue_weekly_report` push the right payloads
    into an arq redis pool.
  * `photo_analysis_job` fans out to `run_photo_analysis` + `_aggregate_progress`.
  * `weekly_report_job` delegates to `generate_weekly_report`.
  * `weekly_report_cron` discovers active projects and enqueues one report per.

Redis and the ML pipelines are mocked so this suite runs without Redis,
Postgres, or any model weights.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")

asyncio_test = pytest.mark.asyncio


@pytest.fixture
def fake_pool():
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    pool.enqueue_job.return_value = MagicMock(job_id="job-abc")
    return pool


@pytest.fixture(autouse=True)
def reset_redis_singleton():
    """Ensure `_REDIS` is re-fetched per test so `get_pool` picks up our patch."""
    from workers import queue

    queue._REDIS = None
    yield
    queue._REDIS = None


# ---------- Enqueue helpers ----------

@asyncio_test
async def test_enqueue_photo_analysis_pushes_serialized_ids(fake_pool):
    from workers import queue

    photo_ids = [uuid4(), uuid4(), uuid4()]

    with patch.object(queue, "get_pool", AsyncMock(return_value=fake_pool)):
        job_id = await queue.enqueue_photo_analysis(
            organization_id=ORG_ID,
            project_id=PROJECT_ID,
            photo_ids=photo_ids,
        )

    assert job_id == "job-abc"
    fake_pool.enqueue_job.assert_awaited_once()
    name, *args = fake_pool.enqueue_job.await_args.args
    assert name == "photo_analysis_job"
    assert args == [str(ORG_ID), str(PROJECT_ID), [str(p) for p in photo_ids]]


@asyncio_test
async def test_enqueue_weekly_report_serializes_dates(fake_pool):
    from workers import queue

    with patch.object(queue, "get_pool", AsyncMock(return_value=fake_pool)):
        job_id = await queue.enqueue_weekly_report(
            organization_id=ORG_ID,
            project_id=PROJECT_ID,
            week_start=date(2026, 4, 13),
            week_end=date(2026, 4, 19),
        )

    assert job_id == "job-abc"
    name, *args = fake_pool.enqueue_job.await_args.args
    assert name == "weekly_report_job"
    assert args == [str(ORG_ID), str(PROJECT_ID), "2026-04-13", "2026-04-19"]


# ---------- Job handlers ----------

@asyncio_test
async def test_photo_analysis_job_fans_out_and_aggregates(monkeypatch):
    from workers import queue

    run_photo = AsyncMock(return_value=None)
    aggregate = AsyncMock(return_value=None)

    # Stub the ml pipeline module BEFORE the handler imports from it.
    import sys
    import types

    fake_mod = types.ModuleType("apps.ml.pipelines.siteeye")
    fake_mod.run_photo_analysis = run_photo
    fake_mod._aggregate_progress = aggregate
    monkeypatch.setitem(sys.modules, "apps.ml.pipelines.siteeye", fake_mod)

    photo_ids = [uuid4(), uuid4()]
    result = await queue.photo_analysis_job(
        ctx={},
        organization_id=str(ORG_ID),
        project_id=str(PROJECT_ID),
        photo_ids=[str(p) for p in photo_ids],
    )

    assert result == {"analyzed": 2}
    assert run_photo.await_count == 2
    for call, pid in zip(run_photo.await_args_list, photo_ids):
        assert call.kwargs == {
            "organization_id": ORG_ID,
            "project_id": PROJECT_ID,
            "photo_id": pid,
        }
    aggregate.assert_awaited_once_with(organization_id=ORG_ID, project_id=PROJECT_ID)


@asyncio_test
async def test_photo_analysis_job_swallows_per_photo_errors(monkeypatch):
    """One bad photo shouldn't take down the whole batch."""
    from workers import queue

    calls = []

    async def _run(*, organization_id, project_id, photo_id):
        calls.append(photo_id)
        if len(calls) == 1:
            raise RuntimeError("model timeout")

    import sys
    import types

    fake_mod = types.ModuleType("apps.ml.pipelines.siteeye")
    fake_mod.run_photo_analysis = _run
    fake_mod._aggregate_progress = AsyncMock(return_value=None)
    monkeypatch.setitem(sys.modules, "apps.ml.pipelines.siteeye", fake_mod)

    photo_ids = [uuid4(), uuid4()]
    result = await queue.photo_analysis_job(
        ctx={},
        organization_id=str(ORG_ID),
        project_id=str(PROJECT_ID),
        photo_ids=[str(p) for p in photo_ids],
    )

    assert result == {"analyzed": 2}
    assert len(calls) == 2
    fake_mod._aggregate_progress.assert_awaited_once()


@asyncio_test
async def test_weekly_report_job_delegates_to_pipeline(monkeypatch):
    from workers import queue

    report = MagicMock(id=uuid4())
    generate = AsyncMock(return_value=report)

    import sys
    import types

    fake_mod = types.ModuleType("apps.ml.pipelines.siteeye")
    fake_mod.generate_weekly_report = generate
    monkeypatch.setitem(sys.modules, "apps.ml.pipelines.siteeye", fake_mod)

    result = await queue.weekly_report_job(
        ctx={},
        organization_id=str(ORG_ID),
        project_id=str(PROJECT_ID),
        week_start="2026-04-13",
        week_end="2026-04-19",
    )

    assert result == {"report_id": str(report.id)}
    generate.assert_awaited_once_with(
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        week_start=date(2026, 4, 13),
        week_end=date(2026, 4, 19),
    )


# ---------- Cron ----------

@asyncio_test
async def test_weekly_report_cron_enqueues_one_job_per_active_project(
    fake_pool, monkeypatch
):
    from workers import queue

    active_projects = [
        (uuid4(), uuid4()),
        (uuid4(), uuid4()),
        (uuid4(), uuid4()),
    ]

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def execute(self, *_args, **_kwargs):
            result = MagicMock()
            result.all = MagicMock(return_value=active_projects)
            return result

    monkeypatch.setattr(queue, "get_pool", AsyncMock(return_value=fake_pool))
    # The cron uses AdminSessionFactory (BYPASSRLS) for its cross-tenant
    # discovery read — see workers/queue.py. Patch on the source module
    # because the import happens inside the cron body.
    from db import session as db_session

    monkeypatch.setattr(db_session, "AdminSessionFactory", lambda: _FakeSession())

    result = await queue.weekly_report_cron(ctx={})

    assert result["projects_queued"] == 3
    assert fake_pool.enqueue_job.await_count == 3
    for call, (org_id, project_id) in zip(
        fake_pool.enqueue_job.await_args_list, active_projects
    ):
        name, org_arg, project_arg, *_dates = call.args
        assert name == "weekly_report_job"
        assert org_arg == str(org_id)
        assert project_arg == str(project_id)


@asyncio_test
async def test_weekly_report_cron_no_activity_enqueues_nothing(
    fake_pool, monkeypatch
):
    from workers import queue

    class _EmptySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def execute(self, *_args, **_kwargs):
            result = MagicMock()
            result.all = MagicMock(return_value=[])
            return result

    monkeypatch.setattr(queue, "get_pool", AsyncMock(return_value=fake_pool))
    from db import session as db_session

    monkeypatch.setattr(db_session, "AdminSessionFactory", lambda: _EmptySession())

    result = await queue.weekly_report_cron(ctx={})

    assert result["projects_queued"] == 0
    fake_pool.enqueue_job.assert_not_called()


# ---------- Worker registration ----------

def test_worker_settings_registers_all_job_handlers():
    from workers.queue import (
        WorkerSettings,
        photo_analysis_job,
        weekly_report_job,
    )

    assert photo_analysis_job in WorkerSettings.functions
    assert weekly_report_job in WorkerSettings.functions


def test_worker_settings_registers_weekly_cron():
    from workers.queue import WorkerSettings

    assert len(WorkerSettings.cron_jobs) >= 1
    weekly = WorkerSettings.cron_jobs[0]
    # arq's CronJob stores the bound coroutine under `coroutine`.
    assert getattr(weekly, "coroutine", None).__name__ == "weekly_report_cron"
