"""Tests for the cross-module 'Công việc đang thực hiện' router.

Two endpoints, both auth-gated to any logged-in member of the org:

  * GET /api/v1/my-work            — aggregated list of open tasks +
    schedule activities across every project.
  * GET /api/v1/my-work/summary    — KPI tiles (open / overdue /
    due_today / completed_week).

We exercise the SQL composition (status bucket, assignee scope,
kind filter, project filter) via FastAPI's TestClient with mocked
TenantAwareSession. The session mock records the rendered SQL so we
can assert the right WHERE clauses fire.

Live-DB coverage (tenant isolation, RLS) lives in the
test_vn_modules_integration.py suite — out of scope here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app
from middleware.auth import AuthContext, require_auth


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth_ctx(role: str = "admin") -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=role,
        email="user@example.com",
    )


@pytest.fixture
def mock_session():
    """Build a mock async session whose `execute` returns canned results.

    We capture every (sql, params) pair the router sends so tests can
    assert the right SQL clauses fire under each filter combination.
    """
    captured: list[tuple[str, dict]] = []

    class _Result:
        def __init__(self, rows=None, scalar=0):
            self._rows = rows or []
            self._scalar = scalar

        def mappings(self):
            return self

        def all(self):
            return [self._make_mapping(r) for r in self._rows]

        def one(self):
            return self._make_mapping(self._rows[0]) if self._rows else self._make_mapping({})

        def scalar_one(self):
            return self._scalar

        @staticmethod
        def _make_mapping(d):
            return d

    async def fake_execute(stmt, params=None):
        sql = str(stmt)
        captured.append((sql, dict(params or {})))
        # Distinguish summary vs list calls heuristically.
        if "FROM tasks t" in sql and "FILTER" in sql:
            return _Result(rows=[{
                "open_tasks": 3,
                "overdue_tasks": 1,
                "due_today_tasks": 2,
                "completed_week_tasks": 5,
            }])
        if "FROM schedule_activities a" in sql and "FILTER" in sql:
            return _Result(rows=[{
                "open_acts": 4,
                "overdue_acts": 0,
                "due_today_acts": 1,
                "completed_week_acts": 2,
            }])
        if "COUNT(*) FROM" in sql:
            return _Result(scalar=7)
        # default: list rows
        return _Result(rows=[])

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)

    # The router calls `TenantAwareSession(org_id)` and awaits the context
    # manager — so the patched class is a factory that accepts the org id
    # arg and returns an async context manager.
    def _factory(*args, **kwargs):
        class _Ctx:
            async def __aenter__(self):
                return sess

            async def __aexit__(self, *a):
                return False

        return _Ctx()

    return _factory, captured


def test_endpoint_requires_auth(client):
    """No auth header → require_auth rejects. FastAPI's HTTPBearer raises
    403 ("Not authenticated") rather than 401; either is acceptable as
    long as anonymous access is blocked."""
    resp = client.get("/api/v1/my-work")
    assert resp.status_code in (401, 403)


def test_list_returns_combined_envelope(client, mock_session):
    ctx_cls, _captured = mock_session
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()

    with patch("routers.my_work.TenantAwareSession", ctx_cls):
        resp = client.get("/api/v1/my-work")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "items" in body
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["total"] == 7


def test_status_open_filters_both_sources(client, mock_session):
    """Default `status=open` clause must apply to both task + activity halves."""
    ctx_cls, captured = mock_session
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()

    with patch("routers.my_work.TenantAwareSession", ctx_cls):
        client.get("/api/v1/my-work")

    select_sql = next(s for s, _ in captured if "UNION ALL" in s and "ORDER BY" in s)
    assert "t.status NOT IN ('done', 'cancelled')" in select_sql
    assert "a.status NOT IN ('complete')" in select_sql


def test_status_overdue_includes_date_comparison(client, mock_session):
    ctx_cls, captured = mock_session
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()

    with patch("routers.my_work.TenantAwareSession", ctx_cls):
        client.get("/api/v1/my-work?status=overdue")

    select_sql = next(s for s, _ in captured if "UNION ALL" in s and "ORDER BY" in s)
    assert "t.due_date < CAST(:today AS date)" in select_sql
    assert "a.planned_finish < CAST(:today AS date)" in select_sql


def test_status_all_drops_status_filter(client, mock_session):
    """`status=all` → no status WHERE clauses at all."""
    ctx_cls, captured = mock_session
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()

    with patch("routers.my_work.TenantAwareSession", ctx_cls):
        client.get("/api/v1/my-work?status=all")

    select_sql = next(s for s, _ in captured if "UNION ALL" in s and "ORDER BY" in s)
    assert "t.status NOT IN" not in select_sql
    assert "a.status NOT IN" not in select_sql


def test_assignee_me_scopes_to_caller(client, mock_session):
    ctx_cls, captured = mock_session
    auth = _auth_ctx()
    app.dependency_overrides[require_auth] = lambda: auth

    with patch("routers.my_work.TenantAwareSession", ctx_cls):
        client.get("/api/v1/my-work?assignee=me")

    select_sql = next(s for s, _ in captured if "UNION ALL" in s and "ORDER BY" in s)
    params = next(p for s, p in captured if "UNION ALL" in s and "ORDER BY" in s)
    assert "t.assignee_id = :uid" in select_sql
    assert "a.assignee_id = :uid" in select_sql
    assert params["uid"] == str(auth.user_id)


def test_assignee_anyone_omits_uid_param(client, mock_session):
    ctx_cls, captured = mock_session
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()

    with patch("routers.my_work.TenantAwareSession", ctx_cls):
        client.get("/api/v1/my-work?assignee=anyone")

    select_sql, params = next(
        (s, p) for s, p in captured if "UNION ALL" in s and "ORDER BY" in s
    )
    assert ":uid" not in select_sql
    assert "uid" not in params


def test_kind_task_only_omits_activities_half(client, mock_session):
    ctx_cls, captured = mock_session
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()

    with patch("routers.my_work.TenantAwareSession", ctx_cls):
        client.get("/api/v1/my-work?kind=task")

    select_sql = next(s for s, _ in captured if "ORDER BY" in s)
    assert "FROM tasks t" in select_sql
    assert "FROM schedule_activities" not in select_sql


def test_kind_activity_only_omits_tasks_half(client, mock_session):
    ctx_cls, captured = mock_session
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()

    with patch("routers.my_work.TenantAwareSession", ctx_cls):
        client.get("/api/v1/my-work?kind=activity")

    select_sql = next(s for s, _ in captured if "ORDER BY" in s)
    assert "FROM schedule_activities" in select_sql
    assert "FROM tasks t" not in select_sql


def test_project_filter_binds_project_id(client, mock_session):
    ctx_cls, captured = mock_session
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()
    pid = uuid4()

    with patch("routers.my_work.TenantAwareSession", ctx_cls):
        client.get(f"/api/v1/my-work?project_id={pid}")

    _, params = next(
        (s, p) for s, p in captured if "UNION ALL" in s and "ORDER BY" in s
    )
    assert params["pid"] == str(pid)


def test_summary_returns_combined_kpis(client, mock_session):
    """KPI tile endpoint sums tasks + activities across all 4 buckets."""
    ctx_cls, _ = mock_session
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()

    with patch("routers.my_work.TenantAwareSession", ctx_cls):
        resp = client.get("/api/v1/my-work/summary")

    assert resp.status_code == 200
    body = resp.json()["data"]
    # From the mock_session canned data:
    #   tasks    → open=3 overdue=1 due_today=2 completed_week=5
    #   acts     → open=4 overdue=0 due_today=1 completed_week=2
    assert body["open"] == 7
    assert body["overdue"] == 1
    assert body["due_today"] == 3
    assert body["completed_week"] == 7


def test_limit_validation_rejects_oversized(client):
    """`limit > 200` returns 422 — protects the cross-table query from
    accidentally fanning out into a slow report."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()
    resp = client.get("/api/v1/my-work?limit=500")
    assert resp.status_code == 422
