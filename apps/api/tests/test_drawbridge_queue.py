"""Smoke tests for the Drawbridge arq job wiring.

Covers:
  * `enqueue_drawbridge_ingest` pushes the right job name + serialised args.
  * `drawbridge_ingest_job` forwards to `_ingest_document` with typed UUIDs.
  * `enqueue_ingest_document` (called from the router) falls back to an
    inline task when the arq pool is unreachable, so local dev / tests
    don't need Redis.
  * `WorkerSettings.functions` registers the new handler.

Redis and the ML pipeline are mocked — no external services required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
DOC_ID = UUID("44444444-4444-4444-4444-444444444444")

asyncio_test = pytest.mark.asyncio


@pytest.fixture
def fake_pool():
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    pool.enqueue_job.return_value = MagicMock(job_id="job-xyz")
    return pool


@pytest.fixture(autouse=True)
def reset_redis_singleton():
    from workers import queue

    queue._REDIS = None
    yield
    queue._REDIS = None


# ---------- Enqueue helper ----------


@asyncio_test
async def test_enqueue_drawbridge_ingest_pushes_serialised_args(fake_pool):
    from workers import queue

    with patch.object(queue, "get_pool", AsyncMock(return_value=fake_pool)):
        job_id = await queue.enqueue_drawbridge_ingest(
            organization_id=ORG_ID,
            document_id=DOC_ID,
            storage_key="drawbridge/org/22222.../doc.pdf",
            mime_type="application/pdf",
        )

    assert job_id == "job-xyz"
    fake_pool.enqueue_job.assert_awaited_once()
    name, *args = fake_pool.enqueue_job.await_args.args
    assert name == "drawbridge_ingest_job"
    assert args == [
        str(ORG_ID),
        str(DOC_ID),
        "drawbridge/org/22222.../doc.pdf",
        "application/pdf",
    ]


# ---------- Job handler ----------


@asyncio_test
async def test_drawbridge_ingest_job_forwards_to_pipeline(monkeypatch):
    from workers import queue

    ingest = AsyncMock(return_value=None)

    # Stub the ml pipeline module BEFORE the handler imports from it.
    import sys
    import types

    fake_mod = types.ModuleType("apps.ml.pipelines.drawbridge")
    fake_mod._ingest_document = ingest
    # Install under BOTH module names. `workers/queue.py` does
    # `from ml.pipelines.drawbridge import _ingest_document` (bare-package);
    # other call sites use `apps.ml.pipelines.drawbridge`. conftest puts
    # both apps/api/ and the repo root on sys.path, so the two paths land
    # as separate sys.modules entries — stubbing only one leaves the real
    # module in effect on the other.
    monkeypatch.setitem(sys.modules, "apps.ml.pipelines.drawbridge", fake_mod)
    monkeypatch.setitem(sys.modules, "ml.pipelines.drawbridge", fake_mod)

    result = await queue.drawbridge_ingest_job(
        ctx={},
        organization_id=str(ORG_ID),
        document_id=str(DOC_ID),
        storage_key="k",
        mime_type="application/pdf",
    )

    assert result == {"document_id": str(DOC_ID), "status": "ingested"}
    ingest.assert_awaited_once_with(
        organization_id=ORG_ID,
        document_id=DOC_ID,
        storage_key="k",
        mime_type="application/pdf",
    )


# ---------- Router-side fallback ----------


@asyncio_test
async def test_enqueue_ingest_document_falls_back_when_pool_unavailable(monkeypatch):
    """If Redis is down the API must not 500 — drop to inline asyncio task."""
    # The SUT does `from workers.queue import get_pool` (bare-package). Patch
    # *that* module — patching `apps.api.workers.queue` instead silently
    # misses, because conftest's dual sys.path entries make those two
    # different module objects. Pre-this-fix the test passed by accident
    # (real Redis was unreachable, so the un-patched get_pool raised
    # anyway); under CI's running Redis it would no-op into the wrong path.
    from apps.ml.pipelines import drawbridge as pipeline

    from workers import queue

    monkeypatch.setattr(queue, "get_pool", AsyncMock(side_effect=RuntimeError("redis down")))

    # Swap out the real _ingest_document so we don't actually touch DB/LLMs.
    inline = AsyncMock(return_value=None)
    monkeypatch.setattr(pipeline, "_ingest_document", inline)

    # asyncio.create_task wraps a coroutine; capture it to ensure it was scheduled.
    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        # Close the coroutine so pytest doesn't complain about it never being awaited.
        coro.close()

        class _Task:
            def done(self):
                return True

            # The pipeline registers a `discard` callback to keep background
            # tasks from being garbage-collected mid-flight; the stub has
            # to accept it (a no-op is fine — we already closed the coro).
            def add_done_callback(self, _cb):
                return None

        return _Task()

    monkeypatch.setattr(pipeline.asyncio, "create_task", fake_create_task)

    job_id = await pipeline.enqueue_ingest_document(
        organization_id=ORG_ID,
        document_id=DOC_ID,
        storage_key="k",
        mime_type="application/pdf",
    )

    assert job_id is None
    assert len(scheduled) == 1


@asyncio_test
async def test_enqueue_ingest_document_uses_arq_when_available(fake_pool, monkeypatch):
    # Patch the bare-package module — see the falls-back test for why.
    from apps.ml.pipelines import drawbridge as pipeline

    from workers import queue

    monkeypatch.setattr(queue, "get_pool", AsyncMock(return_value=fake_pool))

    # If we accidentally fall through to inline, fail loudly.
    def boom(*_a, **_k):
        raise AssertionError("inline fallback should not run when pool is up")

    monkeypatch.setattr(pipeline.asyncio, "create_task", boom)

    job_id = await pipeline.enqueue_ingest_document(
        organization_id=ORG_ID,
        document_id=DOC_ID,
        storage_key="k",
        mime_type="application/pdf",
    )

    assert job_id == "job-xyz"
    fake_pool.enqueue_job.assert_awaited_once()
    name, *args = fake_pool.enqueue_job.await_args.args
    assert name == "drawbridge_ingest_job"
    assert args[0] == str(ORG_ID)
    assert args[1] == str(DOC_ID)


# ---------- Worker registration ----------


def test_worker_settings_registers_drawbridge_ingest():
    from workers.queue import WorkerSettings, drawbridge_ingest_job

    assert drawbridge_ingest_job in WorkerSettings.functions
