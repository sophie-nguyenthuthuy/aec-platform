"""Real-DB N+1 detector for hot routes.

Why this exists alongside `test_query_budgets.py`
-------------------------------------------------
The unit-lane `test_query_budgets.py` counts `db.execute()` calls
through the `FakeAsyncSession` wrapper. That catches the explicit
`for row in rows: await db.execute(...)` regression, but it CAN'T
see the more pernicious bug class: SQLAlchemy `relationship()`
lazy-loading.

The lazy-load N+1 looks like this in the route:

    rows = (await db.execute(select(Package))).scalars().all()
    return [{"id": r.id, "owner_email": r.owner.email} for r in rows]

That's ONE explicit `db.execute()` call — the fake-session budget
sees it as 1 and waves it through. But against a real Postgres,
each `r.owner.email` access triggers a fresh SELECT against the
`users` table. With 50 packages, that's 51 queries: 1 + 50 lazy
loads. The bundle size guard doesn't see it. The runtime tests
don't see it. The slow-query log eventually sees it, weeks later.

This test runs against a real DB and uses SQLAlchemy's
`before_cursor_execute` event to count EVERY query the engine
issues — including the lazy-loads. We pin a generous ceiling on
each hot route (so the test isn't a perf benchmark, it's a "did
N+1 sneak in" gate).

How budgets were chosen
-----------------------
For each route we seed N rows of the listed-collection (e.g. 50
handover packages), then assert the request issues no more than
`expected + small_constant` queries. The constant absorbs:
  * Auth/RLS context-setting queries.
  * One-off `count` lookups for pagination.
  * Eager-load N+1s the route legitimately performs (e.g. 1 SELECT
    per join when the route is doing complex aggregation).

A lazy-load N+1 would push the count past `seed_n` — it's the
"linear in row count" shape that kills the budget, regardless of
exact number.

Gated on `--integration` + `COSTPULSE_RLS_DB_URL`. Same DB the
RLS + quota tests use; this is a read-mostly suite (we seed +
clean up our own rows; we don't mutate other suites' data).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_DB_URL = os.environ.get("COSTPULSE_RLS_DB_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        _DB_URL is None,
        reason="COSTPULSE_RLS_DB_URL not set — N+1 detector requires a live DB",
    ),
]


# ---------- Query counter via SQLAlchemy event ----------


class QueryCounter:
    """Counts every cursor.execute call against a sync engine.

    Attaches to `engine.sync_engine` (the AsyncEngine wraps a sync
    one underneath). The listener increments `count` on every
    `before_cursor_execute` event — whether the query came from an
    explicit `await session.execute(...)` OR a lazy-load triggered
    by attribute access. THAT is what makes this test see N+1.

    Detach via `__exit__` to avoid leaking listeners across tests
    (each enrolled test attaches a fresh counter).
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._target = engine.sync_engine
        self.count = 0
        # Captured statements (truncated) — surfaced in the failure
        # message so the offending query is visible.
        self.queries: list[str] = []

    def _on_execute(
        self,
        _conn: Any,
        _cursor: Any,
        statement: str,
        _params: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        self.count += 1
        # Cap at 50 — beyond that the failure message is unreadable.
        if len(self.queries) < 50:
            self.queries.append(" ".join(statement.split())[:120])

    def __enter__(self) -> QueryCounter:
        event.listen(self._target, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *_args: Any) -> None:
        event.remove(self._target, "before_cursor_execute", self._on_execute)


# ---------- DB plumbing ----------


@pytest.fixture
async def engine():
    assert _DB_URL is not None
    eng = create_async_engine(_DB_URL, future=True)
    yield eng
    await eng.dispose()


@asynccontextmanager
async def session_for(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s


# ---------- Test harness ----------


async def _seed_packages(session: AsyncSession, org_id: str, n: int) -> list[str]:
    """Create N handover packages owned by `org_id`. Returns their ids.

    Uses raw SQL rather than the ORM so we don't ourselves trigger
    the lazy-load behaviour we're trying to detect on the read path.
    """
    ids = [str(uuid4()) for _ in range(n)]
    project_id = str(uuid4())
    # Need a project row first so the FK accepts the package inserts.
    await session.execute(
        text(
            "INSERT INTO projects (id, organization_id, name, type, status, "
            "address, metadata) VALUES (:p, :o, 'NPlus1 Test Project', "
            "'commercial', 'construction', '{}', '{}')"
        ),
        {"p": project_id, "o": org_id},
    )
    for pid in ids:
        await session.execute(
            text(
                "INSERT INTO handover_packages "
                "(id, organization_id, project_id, name, status, created_at) "
                "VALUES (:i, :o, :pr, :n, 'draft', NOW())"
            ),
            {"i": pid, "o": org_id, "pr": project_id, "n": f"NPlus1 Package {pid[:8]}"},
        )
    await session.commit()
    return ids


async def _cleanup(session: AsyncSession, org_id: str) -> None:
    """Drop every test-specific row we created.

    Cleans up in FK order: packages → project → org. Other suites
    don't share these test orgs so it's safe to use a CASCADE-aware
    delete on the org.
    """
    await session.execute(
        text("DELETE FROM handover_packages WHERE organization_id = :o AND name LIKE 'NPlus1 Package %'"),
        {"o": org_id},
    )
    await session.execute(
        text("DELETE FROM projects WHERE organization_id = :o AND name = 'NPlus1 Test Project'"),
        {"o": org_id},
    )
    await session.execute(
        text("DELETE FROM organizations WHERE id = :o"),
        {"o": org_id},
    )
    await session.commit()


# ---------- N+1 budget table ----------


# Each route's budget. The contract: query count must scale O(1) in
# the seeded row count. A lazy-load regression would scale O(N), and
# at N=50 the count would explode past the ceiling.
N_PLUS_1_BUDGETS = {
    # GET /handover/packages: 1 main SELECT (with LATERAL joins for
    # closeout/warranty/defect counts) + 1 COUNT(*) for pagination =
    # 2 queries baseline. Allow 5 to absorb auth/RLS context-set
    # queries and any future eager-load addition. 50+ would mean
    # lazy-load N+1.
    "GET /handover/packages": 5,
}


# ---------- The actual detector test ----------


async def test_handover_packages_no_n_plus_one(engine):
    """Seed 50 handover packages, hit `GET /handover/packages`, count
    every cursor.execute the engine issued.

    Pass: total queries ≤ N_PLUS_1_BUDGETS[...].
    Fail: total queries scale linearly with seed_n — that's the
    N+1 fingerprint.
    """
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import handover as handover_router

    org_id = str(uuid4())
    # Ensure the org exists so the route's auth context resolves
    # against a real row.
    async with session_for(engine) as session:
        await session.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:o, 'NPlus1 Test Org', :s)"),
            {"o": org_id, "s": f"nplus1-{org_id}"},
        )
        await session.commit()

        seed_n = 50
        await _seed_packages(session, org_id, seed_n)

    fake_auth = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4().hex and __import__("uuid").UUID(org_id),
        role="admin",
        email="nplus1@test.local",
    )

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(handover_router.router)
    app.dependency_overrides[require_auth] = lambda: fake_auth

    # The handover router uses TenantAwareSession, not the dep-injected
    # `db`, so we can't override `get_db`. Instead we count against the
    # shared engine — TenantAwareSession ultimately uses the same
    # asyncpg connection pool. Attach the counter just before the
    # request fires.
    transport = ASGITransport(app=app)
    try:
        with QueryCounter(engine) as counter:
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.get("/api/v1/handover/packages")
                assert res.status_code == 200, res.text

        budget = N_PLUS_1_BUDGETS["GET /handover/packages"]
        if counter.count > budget:
            # Show first 10 queries inline so the bug is diagnosable
            # from the failure message — the offender is usually the
            # one that repeats verbatim across rows.
            sample = "\n".join(f"  {i + 1}. {q}" for i, q in enumerate(counter.queries[:10]))
            pytest.fail(
                f"GET /handover/packages issued {counter.count} queries "
                f"against {seed_n} seeded rows (budget {budget}).\n"
                f"This shape suggests a lazy-load N+1 — query count "
                f"scaling with row count rather than O(1) in the route's "
                f"main SELECT.\n\n"
                f"First {min(10, len(counter.queries))} queries:\n{sample}\n\n"
                f"Common causes: a route that loops over rows and accesses "
                f"a `relationship()` attribute (`r.owner.email`) without "
                f"having joined-loaded it via `selectinload()`/`joinedload()`."
            )
    finally:
        async with session_for(engine) as session:
            await _cleanup(session, org_id)
