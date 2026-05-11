"""Per-route query-count budgets.

What it catches
---------------
The classic N+1: someone adds a per-row `await db.execute(...)` inside
a list-render loop. Each individual query passes review (it works, the
unit test still goes green), but the route's overall query count grows
linearly with `len(rows)`. By the time it shows up in production
slow-query logs, the regression has been in main for a week.

This test pins a per-route ceiling on `db.execute()` calls. Mock
sessions can't model real-world lazy-load N+1 (a single `.execute()`
in the route can fan out to N queries via SQLAlchemy `relationship`
loading at access time), but they DO catch the much-more-common
shape: an explicit `for row in rows: await db.execute(...)` where the
loop count is wrong by an order of magnitude.

How budgets were chosen
-----------------------
Each ceiling is `actual_count + 1` — the slack absorbs a single new
query (e.g. adding a `created_by` join) without forcing a budget bump
in the same PR. A drift of two or more queries should be discussed.
When you legitimately need to bump, do it as the LAST commit in the
PR with a one-line justification, so a reviewer sees both the route
change AND the budget change side-by-side.

What this test is NOT
---------------------
* Not a perf benchmark — `.execute()` count is a loose proxy for
  cost. A single 50-table-JOIN can be slower than 5 PK lookups.
* Not real-world N+1 detection — `FakeAsyncSession` returns mock
  results that don't trigger lazy-loads. For genuine N+1 detection
  you'd need to wrap the real asyncpg pool with an event listener
  in an integration test. That's a separate exercise.
* Not a contract on response shape — other tests pin that.

What it IS is the cheapest possible regression gate against
"someone added a query inside a for-loop." Runs in unit lane, no DB.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


# ---------- Counting session wrapper ----------


class _CountingSession:
    """Thin wrapper around `FakeAsyncSession` that counts `.execute()` calls.

    We don't subclass — composing keeps the wrapper independent of
    future changes to the conftest's `FakeAsyncSession` shape (e.g. if
    it gains new methods, we don't need to override them all).
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.execute_count = 0

    def add(self, obj: Any) -> None:
        self._inner.add(obj)

    async def flush(self) -> None:
        await self._inner.flush()

    async def commit(self) -> None:
        await self._inner.commit()

    async def refresh(self, obj: Any) -> None:
        await self._inner.refresh(obj)

    async def close(self) -> None:
        await self._inner.close()

    async def get(self, model: type, id_: Any) -> Any:
        return await self._inner.get(model, id_)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        self.execute_count += 1
        return await self._inner.execute(*args, **kwargs)

    # Pass-through for the test-helper hooks on the underlying fake.
    def set_execute_result(self, result: Any) -> None:
        self._inner.set_execute_result(result)

    def set_get(self, model: type, id_: Any, obj: Any) -> None:
        self._inner.set_get(model, id_, obj)


# ---------- App builder ----------


def _build_counting_app(router_module_name: str, fake_auth, fake_db) -> tuple[FastAPI, _CountingSession]:
    """Mount one router on a fresh app with a counting session.

    `router_module_name` is the dotted path to the router module —
    importing it lazily means tests for one router don't pull in the
    others' module-load side-effects (langchain stubs, etc.).
    """
    from importlib import import_module

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from middleware.auth import require_auth

    counting = _CountingSession(fake_db)

    async def _override_db() -> AsyncIterator:
        yield counting

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(import_module(router_module_name).router)
    app.dependency_overrides[require_auth] = lambda: fake_auth
    app.dependency_overrides[get_db] = _override_db
    return app, counting


# ---------- Per-route budgets ----------


# The budgets. One value per route. Each is `current_count + 1` of
# headroom. Bumping a budget should be a deliberate, separate commit
# with justification in the PR description.
ROUTE_BUDGETS = {
    "GET /pulse/projects/{project_id}/dashboard": 6,  # actual: 5
    "GET /pulse/tasks": 3,  # actual: 2
    "GET /winwork/proposals": 3,  # actual: 2
    "GET /codeguard/checks/{project_id}": 2,  # actual: 1
}


# ---------- /pulse routes ----------


async def test_dashboard_query_budget(fake_auth, fake_db, make_execute_result):
    """Dashboard issues 5 sequential queries (counts, overdue,
    milestones, COs, last_report). Budget = 6.

    A regression to a per-task overdue lookup or per-milestone
    fetch would push this past 6 even on an empty project."""
    app, counting = _build_counting_app("routers.pulse", fake_auth, fake_db)
    counting.set_execute_result(make_execute_result(rows=[]))  # counts
    counting.set_execute_result(make_execute_result(scalar_one=0))  # overdue
    counting.set_execute_result(make_execute_result(rows=[]))  # milestones
    counting.set_execute_result(make_execute_result(one=(0, 0)))  # open CO
    counting.set_execute_result(make_execute_result(scalar_one_or_none=None))  # last report

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/pulse/projects/{uuid4()}/dashboard")
    assert res.status_code == 200, res.text

    budget = ROUTE_BUDGETS["GET /pulse/projects/{project_id}/dashboard"]
    assert counting.execute_count <= budget, (
        f"GET /pulse/projects/{{id}}/dashboard issued {counting.execute_count} "
        f"queries (budget {budget}). If this is intentional (e.g. you added a "
        f"new join), bump the entry in ROUTE_BUDGETS as a separate commit "
        f"with one-line justification."
    )


async def test_list_tasks_query_budget(fake_auth, fake_db, make_execute_result):
    """`list_tasks` issues 2 queries (count, page). Budget = 3.

    A regression that fetched task assignees per-row (rather than
    via a join in the page query) would explode this to ~50."""
    app, counting = _build_counting_app("routers.pulse", fake_auth, fake_db)
    # Total count + page rows.
    counting.set_execute_result(make_execute_result(scalar_one=0))
    counting.set_execute_result(make_execute_result(rows=[]))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/pulse/tasks")
    assert res.status_code == 200, res.text

    budget = ROUTE_BUDGETS["GET /pulse/tasks"]
    assert counting.execute_count <= budget, (
        f"GET /pulse/tasks issued {counting.execute_count} queries (budget {budget}). "
        f"Most likely cause: a new per-row lookup inside the response-shaping loop. "
        f"Move it into the existing select() via a join, or bump the budget."
    )


# ---------- /winwork routes ----------


async def test_list_proposals_query_budget(fake_auth, fake_db, make_execute_result):
    """`list_proposals` issues 2 queries (count, page). Budget = 3."""
    app, counting = _build_counting_app("routers.winwork", fake_auth, fake_db)
    counting.set_execute_result(make_execute_result(scalar_one=0))  # count
    counting.set_execute_result(make_execute_result(rows=[]))  # rows

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/winwork/proposals")
    assert res.status_code == 200, res.text

    budget = ROUTE_BUDGETS["GET /winwork/proposals"]
    assert counting.execute_count <= budget, (
        f"GET /winwork/proposals issued {counting.execute_count} queries (budget {budget})."
    )


# ---------- /codeguard routes ----------


async def test_list_project_checks_query_budget(fake_auth, fake_db, make_execute_result):
    """`list_project_checks` issues 1 query. Budget = 2.

    The route is a single SELECT with project + org filters and
    a `.limit()`. A regression that fetched citations or findings
    per check (rather than relying on the JSONB columns being
    in-row) would multiply this by N."""
    app, counting = _build_counting_app("routers.codeguard", fake_auth, fake_db)
    counting.set_execute_result(make_execute_result(rows=[]))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/codeguard/checks/{uuid4()}")
    assert res.status_code == 200, res.text

    budget = ROUTE_BUDGETS["GET /codeguard/checks/{project_id}"]
    assert counting.execute_count <= budget, (
        f"GET /codeguard/checks/{{id}} issued {counting.execute_count} queries (budget {budget})."
    )


# ---------- Sanity check on the budget table ----------


async def test_route_budgets_are_all_positive_and_reasonable():
    """Sanity check the budgets table itself.

    Catches the embarrassing typo where someone bumps a budget to
    `60` instead of `6`. None of these routes should ever issue
    more than ~10 queries — that's already a "split this endpoint
    or rethink the data model" signal.

    Marked async only so the module-level `pytestmark = asyncio`
    doesn't trip a "non-async function under asyncio mark" warning;
    the body is sync.
    """
    assert all(v > 0 for v in ROUTE_BUDGETS.values()), "Every budget must be positive; a 0 budget would be unmeetable."
    assert all(v <= 10 for v in ROUTE_BUDGETS.values()), (
        f"At least one budget exceeds 10 queries: {ROUTE_BUDGETS}. "
        f"That's a smell — split the endpoint or push the work into a single SQL."
    )
