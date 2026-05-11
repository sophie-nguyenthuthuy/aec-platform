"""Unit tests for the manual cron run-now path (cycle O2).

Three seams pinned here:

  * **Validation.** Unknown cron names 404 from the router BEFORE
    enqueue — a typo doesn't burn an arq retry budget on a doomed
    job. The lookup is `cron_name` against
    `WorkerSettings.cron_jobs[i].name`.

  * **Worker-side dispatch.** `run_cron_by_name_job` finds the entry
    by name and awaits its already-`_telemetry`-wrapped coroutine.
    Threading through the wrapper means every manual run writes a
    `cron_runs` row in the same shape as a scheduled tick.

  * **Function registration.** `run_cron_by_name_job` MUST be in
    `WorkerSettings.functions` — otherwise `pool.enqueue_job(...)`
    fails worker-side at lookup. Pin via the live registry.

The router test mounts the cron_admin router with a stubbed pool +
audit; we don't drive a real arq + Postgres here. Coverage for the
arq integration is the worker's own test suite (out of scope).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
USER_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


def _admin_ctx() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="ops@example.com",
    )


# ---------- WorkerSettings.functions registration ------------------


def test_run_cron_by_name_job_is_registered_in_worker_functions():
    """`run_cron_by_name_job` must be in `WorkerSettings.functions`.
    Without that, the router enqueues by name but the worker
    can't dispatch — every manual run silently fails worker-side
    with `JobExecutionFailed: function not found`."""
    from workers.queue import WorkerSettings, run_cron_by_name_job

    assert run_cron_by_name_job in WorkerSettings.functions, (
        "run_cron_by_name_job is not in WorkerSettings.functions. Re-apply: append it to the `functions = [...]` list."
    )


# ---------- run_cron_by_name_job (worker-side) ---------------------


async def test_run_cron_by_name_job_raises_on_unknown_name():
    """Unknown cron name → ValueError, NOT a silent no-op. arq's
    JobResult log carries the diagnostic so an operator who
    enqueued by typo sees it in the worker logs."""
    from workers.queue import run_cron_by_name_job

    with pytest.raises(ValueError, match="unknown cron_name"):
        await run_cron_by_name_job({}, "cron:does_not_exist")


async def test_run_cron_by_name_job_invokes_registered_coroutine(monkeypatch):
    """Happy path: the job finds the cron entry by name and awaits
    its coroutine. We monkey-patch `WorkerSettings.cron_jobs` to a
    sentinel entry so the test doesn't actually run real cron
    side-effects (DB writes etc).
    """
    from workers import queue as qmod

    # Build a stand-in cron entry. arq's CronJob has `.name` and
    # `.coroutine`; the helper only reads those two attributes.
    invoked: list[dict] = []

    async def fake_cron(ctx: dict) -> dict:
        invoked.append(ctx)
        return {"ok": True}

    fake_entry = MagicMock()
    fake_entry.name = "cron:fake_for_test"
    fake_entry.coroutine = fake_cron

    monkeypatch.setattr(qmod.WorkerSettings, "cron_jobs", [fake_entry])
    out = await qmod.run_cron_by_name_job({"sentinel": 1}, "cron:fake_for_test")

    assert invoked == [{"sentinel": 1}], "ctx must thread through unchanged"
    assert out == {"ok": True}


# ---------- Router-level POST /admin/crons/{cron_name}/run --------


def _build_app() -> FastAPI:
    """Mount the cron_admin router with auth stubbed.

    `require_role("admin")` is a factory that returns a fresh closure
    on every call — overriding by that key would shadow only one
    instance. Override the underlying `require_auth` instead, which
    every `require_role(...)` chains through; the role check then
    runs against the test's AuthContext (role='admin') and passes.
    """
    from middleware.auth import require_auth
    from routers import cron_admin

    app = FastAPI()
    app.include_router(cron_admin.router)
    auth = _admin_ctx()
    app.dependency_overrides[require_auth] = lambda: auth
    return app


async def test_run_now_returns_202_and_job_id(monkeypatch):
    """Happy path: POST against a real registered cron name returns
    202 with a job_id + status='enqueued'. The pool's enqueue_job
    is replaced with a stub returning a known job_id."""
    from workers import queue as qmod

    fake_entry = MagicMock()
    fake_entry.name = "cron:fake_for_router_test"
    fake_entry.coroutine = AsyncMock(return_value={})
    monkeypatch.setattr(qmod.WorkerSettings, "cron_jobs", [fake_entry])

    fake_job = MagicMock()
    fake_job.job_id = "arq-job-12345"

    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(return_value=fake_job)
    monkeypatch.setattr(qmod, "get_pool", AsyncMock(return_value=fake_pool))

    # Audit stub — record() reads from a real session normally. We
    # patch the AdminSessionFactory to a no-op async context manager
    # + audit_record to a no-op so the test stays pure.
    from services import audit as audit_mod

    async def _noop_audit(*_a: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(audit_mod, "record", _noop_audit)

    # AdminSessionFactory needs to be a callable returning an async
    # context manager. A simple class with __aenter__/__aexit__
    # avoids reaching into db.session internals.
    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

    from db import session as db_session_mod

    monkeypatch.setattr(db_session_mod, "AdminSessionFactory", lambda: _FakeSession())

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/admin/crons/cron:fake_for_router_test/run")

    assert res.status_code == 202, res.text
    body = res.json()["data"]
    assert body == {
        "cron_name": "cron:fake_for_router_test",
        "job_id": "arq-job-12345",
        "status": "enqueued",
    }
    # The enqueue_job call MUST receive the cron_name as the bound
    # arg — pin so a refactor that swaps the order doesn't silently
    # enqueue with the wrong name.
    assert fake_pool.enqueue_job.call_args.args == (
        "run_cron_by_name_job",
        "cron:fake_for_router_test",
    )


async def test_run_now_404s_on_unknown_cron(monkeypatch):
    """Unknown cron name 404s at the router BEFORE enqueue — the
    pool's enqueue_job is never called. Without this guard a typo
    silently queues a doomed job."""
    from workers import queue as qmod

    monkeypatch.setattr(qmod.WorkerSettings, "cron_jobs", [])  # empty registry
    enqueue_stub = AsyncMock()
    fake_pool = MagicMock()
    fake_pool.enqueue_job = enqueue_stub
    monkeypatch.setattr(qmod, "get_pool", AsyncMock(return_value=fake_pool))

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/admin/crons/cron:does_not_exist/run")

    assert res.status_code == 404, res.text
    enqueue_stub.assert_not_awaited()
