"""End-to-end smoke test: arq enqueue → Redis → live worker → Postgres.

This test is the integration counterpart to the mock-heavy unit tests in
`test_scraper_queue.py` / `test_siteeye_queue.py`. Instead of patching
`get_pool` and verifying the enqueue call, we:

  1. Seed one price alert + one matching material_prices row
     (via AdminSessionFactory, because those tables live cross-tenant).
  2. Enqueue `price_alerts_evaluate_job` through a real Redis pool.
  3. Spin up a real `arq.worker.Worker(..., burst=True)` that drains
     the queue and exits.
  4. Read the seeded alert back and assert its `last_price_vnd` was set
     (first-observation baseline path — no email, no threshold math).
  5. Tear down the seed data.

The job we exercise is deliberately the NOBYPASSRLS-flavoured batch job
that was silently broken before migration 0010_app_role + the
AdminSessionFactory refactor landed. Running it through the real worker
proves the whole loop — enqueue, Redis, worker process, admin factory,
Postgres DML, RLS posture — is stitched together correctly.

Skipped unless all four env vars are set:

    REDIS_URL="redis://localhost:6381/15"  # isolated DB to avoid collision
    COSTPULSE_RLS_APP_URL="postgresql+asyncpg://aec_app:aec_app@localhost:55432/aec"
    COSTPULSE_RLS_ADMIN_URL="postgresql+asyncpg://aec:aec@localhost:55432/aec"
    DATABASE_URL=<same as COSTPULSE_RLS_APP_URL>
    DATABASE_URL_ADMIN=<same as COSTPULSE_RLS_ADMIN_URL>
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_REDIS_URL = os.environ.get("REDIS_URL")
_ADMIN_URL = os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("COSTPULSE_RLS_ADMIN_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        not (_REDIS_URL and _ADMIN_URL),
        reason=(
            "E2E smoke test requires REDIS_URL + DATABASE_URL_ADMIN "
            "(or COSTPULSE_RLS_ADMIN_URL). See test module docstring."
        ),
    ),
]


@pytest.fixture
async def seed():
    """Seed org + user + price alert + material_prices row; yield ids; clean up."""
    assert _ADMIN_URL is not None
    admin_engine = create_async_engine(_ADMIN_URL, future=True)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    org_id = uuid4()
    user_id = uuid4()
    alert_id = uuid4()
    material_price_id = uuid4()
    material_code = f"E2E_ARQ_{uuid4().hex[:8].upper()}"

    async with admin_factory() as s:
        await s.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'E2E arq', :slug)"),
            {"id": str(org_id), "slug": f"e2e-arq-{org_id}"},
        )
        await s.execute(
            text("INSERT INTO users (id, email) VALUES (:id, :email)"),
            {"id": str(user_id), "email": f"e2e-arq-{user_id}@test.local"},
        )
        # Alert with NO baseline — first-observation path: no email, just
        # stamp `last_price_vnd` on the first evaluator pass.
        await s.execute(
            text(
                "INSERT INTO price_alerts "
                "(id, organization_id, user_id, material_code, threshold_pct) "
                "VALUES (:id, :org, :uid, :code, 5)"
            ),
            {
                "id": str(alert_id),
                "org": str(org_id),
                "uid": str(user_id),
                "code": material_code,
            },
        )
        # Matching price — `evaluate_price_alerts` joins via a LATERAL on
        # material_code + effective_date DESC. One row is enough.
        await s.execute(
            text(
                "INSERT INTO material_prices "
                "(id, material_code, name, unit, price_vnd, source, effective_date) "
                "VALUES (:id, :code, 'E2E Concrete', 'm3', 2100000, 'government', '2026-04-01')"
            ),
            {"id": str(material_price_id), "code": material_code},
        )
        await s.commit()

    yield {
        "alert_id": alert_id,
        "material_code": material_code,
        "org_id": org_id,
        "user_id": user_id,
    }

    async with admin_factory() as s:
        await s.execute(text("DELETE FROM price_alerts WHERE id = :id"), {"id": str(alert_id)})
        await s.execute(
            text("DELETE FROM material_prices WHERE material_code = :code"),
            {"code": material_code},
        )
        await s.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)})
        await s.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_id)})
        await s.commit()
    await admin_engine.dispose()


async def test_price_alert_evaluator_runs_end_to_end_through_real_worker(seed):
    """Enqueue → real arq worker → DB side effects → verify.

    The evaluator job must:
      * Be pickable from Redis by `WorkerSettings.functions`.
      * Run under `AdminSessionFactory` (BYPASSRLS) so it can see the
        cross-tenant alert we seeded.
      * Persist the baseline back to Postgres.
    """
    # Import after the env fixture has asserted — these modules read
    # REDIS_URL + DATABASE_URL_ADMIN at import time via Settings.
    from arq.connections import RedisSettings, create_pool
    from arq.worker import Worker
    from sqlalchemy import text as sql_text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from workers.queue import price_alerts_evaluate_job

    redis_settings = RedisSettings.from_dsn(_REDIS_URL)

    pool = await create_pool(redis_settings)
    try:
        job = await pool.enqueue_job("price_alerts_evaluate_job")
        assert job is not None, "enqueue_job returned None — is the queue paused?"

        # `burst=True` drains the queue and returns. `handle_signals=False`
        # is important inside pytest — arq's signal handlers otherwise try
        # to install SIGTERM/SIGINT handlers on the running event loop and
        # clobber pytest-asyncio's own bookkeeping.
        worker = Worker(
            functions=[price_alerts_evaluate_job],
            redis_settings=redis_settings,
            burst=True,
            handle_signals=False,
            max_jobs=1,
            poll_delay=0.1,
        )
        # Guard against the worker hanging: bounded wait, loud on timeout.
        await asyncio.wait_for(worker.async_run(), timeout=20.0)
        await worker.close()

        # The worker wrote the result back to Redis. Grab it — proves the
        # job actually ran (not just that the worker started + exited).
        info = await job.result_info()
        assert info is not None, "job never produced a result — did it run?"
        assert info.success, f"job failed: {info}"
        summary = info.result
        assert summary["evaluated"] == 1
        assert summary["skipped_no_baseline"] == 1
        assert summary["triggered"] == 0
    finally:
        # arq 5.0.1+ prefers aclose(); fall through if we're on an older
        # pinned version so this test stays cross-compatible.
        closer = getattr(pool, "aclose", None) or pool.close
        await closer()

    # Now verify the DB side effect: the baseline we asked for got stamped.
    # Use a fresh admin engine — the worker's own engine is closed.
    admin_engine = create_async_engine(_ADMIN_URL, future=True)
    try:
        async_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        async with async_factory() as s:
            row = (
                await s.execute(
                    sql_text("SELECT last_price_vnd FROM price_alerts WHERE id = :id"),
                    {"id": str(seed["alert_id"])},
                )
            ).first()
            assert row is not None, "seeded alert vanished"
            assert row[0] is not None, "baseline was NOT stamped — evaluator didn't touch this row"
            assert Decimal(row[0]) == Decimal(2100000), f"unexpected baseline: {row[0]} (expected 2100000)"
    finally:
        await admin_engine.dispose()
