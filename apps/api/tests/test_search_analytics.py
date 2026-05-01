"""Telemetry + analytics tests for search.

Three layers under test:
  * `summarise_results` — pure function reducing a result list to the
    `(top_scope, matched_distribution)` columns we persist.
  * `log_search` — the fire-and-forget writer wired into the router as
    a BackgroundTask. Verified through both a unit-level call and an
    end-to-end trip through `POST /api/v1/search`.
  * `GET /api/v1/search/analytics` — admin-only endpoint that runs
    five aggregate queries against `search_queries`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role
from schemas.search import SearchResult, SearchScope
from services.search import log_search, summarise_results

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("33333333-3333-3333-3333-333333333333")
USER_ID = UUID("44444444-4444-4444-4444-444444444444")


# ---------- FakeAsyncSession (matches test_search_router shape) ----------


class FakeAsyncSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.mappings.return_value.all.return_value = []
        r.mappings.return_value.one.return_value = {}
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture(autouse=True)
def patch_tenant_session(fake_db, monkeypatch):
    """Same factory pattern as test_search_router: replace
    TenantAwareSession with a CM that yields the shared fake."""

    @asynccontextmanager
    async def _factory(_org_id: UUID) -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    monkeypatch.setattr("services.search.TenantAwareSession", _factory)
    yield fake_db


# ---------- summarise_results: pure-function reducer ----------


def _result(scope: SearchScope, matched: str | None = None) -> SearchResult:
    r = SearchResult(scope=scope, id=uuid4(), title="t")
    r.matched_on = matched  # type: ignore[assignment]
    return r


async def test_summarise_empty_returns_none_and_empty_dict():
    """Zero hits → no top_scope, empty dict. We persist NULL for
    `top_scope` so the partial-index drill-down on no-result rows
    can ignore the column. (Async only because the module-level
    `pytestmark` applies asyncio to every test — the function itself
    is pure.)"""
    top, dist = summarise_results([])
    assert top is None
    assert dist == {}


async def test_summarise_picks_modal_scope():
    """`top_scope` is whichever scope produced the most rows."""
    results = [
        _result(SearchScope.documents, "keyword"),
        _result(SearchScope.documents, "vector"),
        _result(SearchScope.defects, "keyword"),
    ]
    top, dist = summarise_results(results)
    assert top == "documents"
    assert dist == {"keyword": 2, "vector": 1}


async def test_summarise_skips_null_matched_on():
    """matched_on=None (vector arm disabled) is excluded from the
    distribution — analytics treats those rows as "we never tried"
    rather than counting them as keyword."""
    r = SearchResult(scope=SearchScope.proposals, id=uuid4(), title="t")
    # matched_on stays None
    top, dist = summarise_results([r])
    assert top == "proposals"
    assert dist == {}


# ---------- log_search: writer behaviour ----------


async def test_log_search_inserts_with_summary_columns(fake_db):
    """Happy path: writer produces a single INSERT bound with the
    org/user/query/scope set + the computed summary columns. Pin the
    bound params so a refactor that drops a column flips this red."""
    results = [
        _result(SearchScope.documents, "keyword"),
        _result(SearchScope.documents, "both"),
        _result(SearchScope.defects, "keyword"),
    ]
    await log_search(
        organization_id=ORG_ID,
        user_id=USER_ID,
        query="tower",
        scopes=[SearchScope.documents, SearchScope.defects],
        project_id=None,
        results=results,
    )
    assert len(fake_db.calls) == 1
    _, params = fake_db.calls[0]
    assert params["org_id"] == str(ORG_ID)
    assert params["user_id"] == str(USER_ID)
    assert params["query"] == "tower"
    assert params["scopes"] == ["documents", "defects"]
    assert params["result_count"] == 3
    assert params["top_scope"] == "documents"
    # JSON-encoded payload — analytics jsonb_each_text reads it back.
    import json

    matched = json.loads(params["matched_distribution"])
    assert matched == {"keyword": 2, "both": 1}


async def test_log_search_omitted_scopes_flattens_to_all(fake_db):
    """`scopes=None` (caller wanted "all scopes") gets persisted as the
    full enum list so analytics scope-distribution queries don't need
    a CASE for "NULL means everything"."""
    await log_search(
        organization_id=ORG_ID,
        user_id=USER_ID,
        query="leak",
        scopes=None,
        project_id=None,
        results=[],
    )
    assert len(fake_db.calls) == 1
    params = fake_db.calls[0][1]
    assert set(params["scopes"]) == {s.value for s in SearchScope}
    # Empty results → top_scope NULL, matched_distribution = "{}".
    assert params["top_scope"] is None
    assert params["result_count"] == 0


async def test_log_search_persists_anonymous_user_as_null(fake_db):
    """user_id=None happens for service-token / unauthenticated probes
    — must serialise to NULL, not the string "None"."""
    await log_search(
        organization_id=ORG_ID,
        user_id=None,
        query="x",
        scopes=[SearchScope.documents],
        project_id=None,
        results=[],
    )
    params = fake_db.calls[0][1]
    assert params["user_id"] is None


async def test_log_search_swallows_db_errors(monkeypatch):
    """A telemetry hiccup MUST NOT propagate — the search response has
    already been built; logging is best-effort."""

    class BoomSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def execute(self, *_a, **_kw):
            raise RuntimeError("db on fire")

        async def commit(self):
            return None

    @asynccontextmanager
    async def _boom_factory(_org_id: UUID):
        yield BoomSession()

    monkeypatch.setattr("services.search.TenantAwareSession", _boom_factory)

    # Should NOT raise.
    await log_search(
        organization_id=ORG_ID,
        user_id=USER_ID,
        query="anything",
        scopes=None,
        project_id=None,
        results=[],
    )


# ---------- End-to-end: router schedules log_search as BackgroundTask ----------


async def test_search_router_schedules_telemetry(fake_db, monkeypatch):
    """E2E: a successful POST /api/v1/search must enqueue a log_search
    background task. Use a capturing stub so we don't have to thread
    one fake_db through both the search SQL and the INSERT."""
    captured: dict[str, Any] = {}

    async def _capture(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("routers.search.log_search", _capture)

    # Program one keyword arm result for `defects` (no vector handler).
    defects_q = MagicMock()
    defects_q.mappings.return_value.all.return_value = [
        {
            "id": uuid4(),
            "title": "Leak",
            "description": "x",
            "project_id": uuid4(),
            "priority": "high",
            "status": "open",
            "reported_at": datetime(2026, 4, 27, tzinfo=UTC),
            "project_name": "Tower A",
        }
    ]
    fake_db.push(defects_q)

    from routers import search as search_router

    app = FastAPI()
    app.include_router(search_router.router)
    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="member",
        email="caller@example.com",
    )
    app.dependency_overrides[require_auth] = lambda: auth_ctx

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "leak", "scopes": ["defects"]},
        )
    assert res.status_code == 200, res.text
    # BackgroundTasks run after the response but inside the same ASGI
    # call — by the time httpx returns, `_capture` has fired.
    assert captured["organization_id"] == ORG_ID
    assert captured["user_id"] == USER_ID
    assert captured["query"] == "leak"
    assert captured["scopes"] == [SearchScope.defects]
    assert len(captured["results"]) == 1


# ---------- GET /api/v1/search/analytics ----------


def _build_analytics_app() -> FastAPI:
    """Spin up the search router with admin auth pre-overridden."""
    from routers import search as search_router

    app = FastAPI()
    app.include_router(search_router.router)
    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="caller@example.com",
    )
    # require_min_role is a factory — overriding by `Role.ADMIN`
    # depends on FastAPI's identity-based dependency lookup. The
    # cleanest way is to override the actual returned dependency by
    # finding it in the router dependencies; but a simpler idiom (used
    # elsewhere in this codebase) is overriding require_auth — which
    # require_min_role wraps. Use the function-identity override.
    dep = require_min_role(Role.ADMIN)
    app.dependency_overrides[dep] = lambda: auth_ctx
    app.dependency_overrides[require_auth] = lambda: auth_ctx
    return app


async def test_analytics_returns_five_breakdowns(fake_db):
    """Pin the response shape: totals + 4 lists. Programs the 5
    expected execute() results (top_queries, no_result, scope, matched,
    totals) into the queue in service-call order."""
    # 1) top_queries
    q1 = MagicMock()
    q1.mappings.return_value.all.return_value = [
        {"query": "tower", "run_count": 12, "avg_results": 4.5, "empty_count": 1},
        {"query": "leak", "run_count": 3, "avg_results": 0.0, "empty_count": 3},
    ]
    fake_db.push(q1)
    # 2) no_result_queries
    q2 = MagicMock()
    q2.mappings.return_value.all.return_value = [
        {"query": "leak", "run_count": 3, "last_run": datetime(2026, 4, 27, tzinfo=UTC)},
    ]
    fake_db.push(q2)
    # 3) scope_distribution
    q3 = MagicMock()
    q3.mappings.return_value.all.return_value = [
        {"top_scope": "documents", "run_count": 10},
        {"top_scope": "rfis", "run_count": 4},
    ]
    fake_db.push(q3)
    # 4) matched_distribution
    q4 = MagicMock()
    q4.mappings.return_value.all.return_value = [
        {"label": "keyword", "run_count": 18},
        {"label": "both", "run_count": 6},
    ]
    fake_db.push(q4)
    # 5) totals
    q5 = MagicMock()
    q5.mappings.return_value.one.return_value = {
        "total_searches": 25,
        "empty_searches": 4,
        "unique_users": 3,
    }
    fake_db.push(q5)

    app = _build_analytics_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/search/analytics?days=30&top_n=10")

    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["window_days"] == 30
    assert body["totals"] == {
        "total_searches": 25,
        "empty_searches": 4,
        "unique_users": 3,
    }
    assert body["top_queries"][0]["query"] == "tower"
    assert body["top_queries"][0]["run_count"] == 12
    assert body["no_result_queries"][0]["query"] == "leak"
    assert body["scope_distribution"][0]["scope"] == "documents"
    assert body["matched_distribution"][0]["label"] == "keyword"


async def test_analytics_rejects_non_admin():
    """Members must NOT see search telemetry — query strings can leak
    project / client names from across the org."""
    from routers import search as search_router

    app = FastAPI()
    app.include_router(search_router.router)
    member_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="member",
        email="m@example.com",
    )
    # Don't override the admin dependency — let it run naturally.
    app.dependency_overrides[require_auth] = lambda: member_ctx

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/search/analytics")
    assert res.status_code == 403


async def test_analytics_validates_window_bounds(fake_db):
    """`days` must be 1..365. Out-of-range returns 422 BEFORE we touch
    the DB — guards against pathological window expansion."""
    app = _build_analytics_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/search/analytics?days=999")
    assert res.status_code == 422
    assert fake_db.calls == []
