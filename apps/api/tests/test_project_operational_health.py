"""Project-level operational health endpoint (cycle V3).

Pinned seams:
  1. Returns four counts the project widget renders:
     overdue_punch_items, pending_submittals, expired_rfqs,
     pending_change_orders. Pin the field set so a refactor that
     renames any silently breaks the widget.
  2. Org-scoped via WHERE on `organization_id` — cross-tenant
     project_id can't leak counts.
  3. Defensive zero-on-failure for missing tables — the widget
     never 500s the project page.
  4. Member role enough (per-project state ≠ admin secret).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
USER_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
PROJECT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []
        self.scalar_values: list[int] = []

    def push_scalar(self, value: int) -> None:
        self.scalar_values.append(value)

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        r = MagicMock()
        if self.scalar_values:
            r.scalar_one.return_value = self.scalar_values.pop(0)
        else:
            r.scalar_one.return_value = 0
        return r

    async def commit(self) -> None: ...
    async def close(self) -> None: ...


def _ctx(role: str = "member") -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="user@example.com",
    )


def _build_app(fake_db: _FakeSession, role: str = "member") -> FastAPI:
    from db.deps import get_db
    from routers import projects as projects_router

    app = FastAPI()
    app.include_router(projects_router.router)

    async def _db_override() -> AsyncIterator[_FakeSession]:
        yield fake_db

    auth_ctx = _ctx(role)
    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[get_db] = _db_override
    return app


# ---------- Field shape ----------


async def test_returns_four_pinned_counts():
    """The widget renders four counts. Pin the exact field names so
    a rename doesn't silently break the widget."""
    db = _FakeSession()
    db.push_scalar(3)  # overdue_punch_items
    db.push_scalar(7)  # pending_submittals
    db.push_scalar(1)  # expired_rfqs
    db.push_scalar(2)  # pending_change_orders

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/projects/{PROJECT_ID}/operational-health")

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert set(data.keys()) == {
        "overdue_punch_items",
        "pending_submittals",
        "expired_rfqs",
        "pending_change_orders",
    }
    assert data["overdue_punch_items"] == 3
    assert data["pending_submittals"] == 7
    assert data["expired_rfqs"] == 1
    assert data["pending_change_orders"] == 2


# ---------- Org-scope ----------


async def test_org_scope_threads_into_every_query():
    """Each of the four sub-queries MUST filter by `organization_id`
    in the WHERE clause — without it, a cross-tenant project_id
    leak surfaces other tenants' counts. Pin every bound-params dict
    carries `org`."""
    db = _FakeSession()
    db.push_scalar(0)
    db.push_scalar(0)
    db.push_scalar(0)
    db.push_scalar(0)

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get(f"/api/v1/projects/{PROJECT_ID}/operational-health")

    # Four queries (one per count). Every one must carry `org` and
    # `project_id` bind params.
    assert len(db.calls) == 4
    for stmt, params in db.calls:
        assert params["org"] == str(ORG_ID), (
            "Project health query missing organization_id filter — cross-tenant project_id could leak peer counts."
        )
        assert params["project_id"] == str(PROJECT_ID)
        sql = stmt.text if hasattr(stmt, "text") else str(stmt)
        assert "organization_id" in sql or ".organization_id" in sql, (
            f"Query missing organization_id WHERE clause: {sql!r}"
        )


# ---------- Defensive zero-on-failure ----------


async def test_handles_missing_tables_gracefully():
    """A tenant where one of the four tables hasn't been migrated
    (or got rolled back) should return 0 for that count, not 500
    the project page. Pin via a session that raises on every
    execute()."""

    class _FailingSession(_FakeSession):
        async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
            raise RuntimeError('relation "punch_items" does not exist')

    db = _FailingSession()
    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/projects/{PROJECT_ID}/operational-health")

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    # Every count is 0 — the page renders the "all clear" tile.
    assert data == {
        "overdue_punch_items": 0,
        "pending_submittals": 0,
        "expired_rfqs": 0,
        "pending_change_orders": 0,
    }


# ---------- RBAC ----------


async def test_member_role_is_sufficient():
    """Per-project workflow data — members already see this in
    each module's listing. The widget aggregates what they can
    already see, so admin gating would be over-restrictive."""
    db = _FakeSession()
    db.push_scalar(1)
    db.push_scalar(1)
    db.push_scalar(1)
    db.push_scalar(1)

    app = _build_app(db, role="member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/projects/{PROJECT_ID}/operational-health")
    assert res.status_code == 200, res.text


async def test_viewer_role_403s():
    """Viewer is below member — read-only org access shouldn't
    surface workflow signals."""
    db = _FakeSession()
    app = _build_app(db, role="viewer")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/projects/{PROJECT_ID}/operational-health")
    assert res.status_code == 403, res.text
