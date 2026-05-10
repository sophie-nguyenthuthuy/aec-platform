"""Project-scoped audit feed (cycle S3).

Pinned seams:
  1. The endpoint is admin-gated.
  2. SQL UNIONs across the five project-scoped tables (change_orders,
     punch_lists, handover_packages, submittals, rfqs).
  3. `_PROJECT_RESOURCE_TABLES` is the shared resource_type → table
     map; pin its keys so a refactor that drops `rfq` doesn't
     silently strip RFQ events from project audit feeds.
  4. Filters compose: action / actor_kind / since_days.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
USER_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
PROJECT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _admin_ctx() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="ops@example.com",
    )


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        sql_text = stmt.text if hasattr(stmt, "text") else str(stmt)
        self.calls.append((sql_text, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.scalar_one.return_value = 0
        r.mappings.return_value.all.return_value = []
        return r


def _scalar(value: Any) -> Any:
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _mappings(rows: list[dict[str, Any]]) -> Any:
    r = MagicMock()
    r.mappings.return_value.all.return_value = rows
    return r


def _build_app(fake_db: _FakeSession, role: str = "admin") -> FastAPI:
    from db.deps import get_db
    from routers import audit as audit_router

    app = FastAPI()
    app.include_router(audit_router.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="ops@example.com",
    )

    async def _db_override() -> AsyncIterator[_FakeSession]:
        yield fake_db

    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[get_db] = _db_override
    return app


# ---------- Resource table map ----------


def test_project_resource_tables_pinned():
    """The five project-scoped resource types MUST be mapped. A
    refactor that drops one (e.g. removes 'rfq') silently strips
    those events from project audit feeds — pin the set."""
    from routers.audit import _PROJECT_RESOURCE_TABLES

    assert set(_PROJECT_RESOURCE_TABLES.keys()) == {
        "change_orders",
        "punchlist_lists",
        "handover_packages",
        "submittals",
        "rfq",
    }
    # Singular/plural mismatch sanity (intentional — values are the
    # resource service emits vs. the table names the resources live
    # in).
    assert _PROJECT_RESOURCE_TABLES["punchlist_lists"] == "punch_lists"
    assert _PROJECT_RESOURCE_TABLES["rfq"] == "rfqs"


# ---------- GET /audit/projects/{project_id}/events ----------


async def test_project_audit_endpoint_returns_paginated_events():
    """Happy path: admin queries project-scoped audit. Pin the
    response shape — the frontend's `data` + `meta` reads the
    same envelope the org-wide endpoint uses."""
    from datetime import UTC, datetime

    db = _FakeSession()
    db.push(_scalar(2))  # COUNT(*)
    db.push(
        _mappings(
            [
                {
                    "id": uuid4(),
                    "organization_id": ORG_ID,
                    "actor_user_id": USER_ID,
                    "actor_api_key_id": None,
                    "actor_email": "alice@example.com",
                    "actor_api_key_name": None,
                    "action": "pulse.change_order.approve",
                    "resource_type": "change_orders",
                    "resource_id": uuid4(),
                    "before": {"status": "draft"},
                    "after": {"status": "approved"},
                    "ip": "203.0.113.7",
                    "user_agent": "Mozilla/5.0",
                    "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                }
            ]
        )
    )

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/audit/projects/{PROJECT_ID}/events")

    assert res.status_code == 200, res.text
    body = res.json()
    assert "data" in body and "meta" in body
    rows = body["data"]
    assert len(rows) == 1
    assert rows[0]["action"] == "pulse.change_order.approve"
    assert body["meta"]["total"] == 2

    # The COUNT query MUST carry both org and project_id bound params
    # — without project_id the query would return org-wide events.
    count_sql, count_params = db.calls[0]
    assert count_params["org"] == str(ORG_ID)
    assert count_params["project_id"] == str(PROJECT_ID)
    # The candidate UNION must reference all five project-scoped
    # resource types — pin the SQL string.
    for rtype in (
        "change_orders",
        "punchlist_lists",
        "handover_packages",
        "submittals",
        "rfq",
    ):
        assert f"resource_type = '{rtype}'" in count_sql, (
            f"resource_type {rtype!r} missing from project-audit candidate query"
        )


async def test_project_audit_endpoint_filters_compose():
    """`action` + `actor_kind` + `since_days` filters compose
    correctly. Pin the bound-params shape so a refactor that drops
    a filter silently surfaces here."""
    db = _FakeSession()
    db.push(_scalar(0))
    db.push(_mappings([]))

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            f"/api/v1/audit/projects/{PROJECT_ID}/events",
            params={
                "action": "pulse.change_order.approve",
                "actor_kind": "user",
                "since_days": 7,
            },
        )

    assert res.status_code == 200, res.text
    count_sql, count_params = db.calls[0]
    # All filter params must be bound.
    assert count_params["action"] == "pulse.change_order.approve"
    assert count_params["since_days"] == 7
    # actor_kind=user → IS NOT NULL clause appears in SQL.
    assert "a.actor_user_id IS NOT NULL" in count_sql


async def test_project_audit_endpoint_403_for_member():
    """Same gating as the org-wide endpoint — Role.ADMIN required.
    Project-scoped audit content can leak who-touched-what within
    the project; non-admins shouldn't see it."""
    db = _FakeSession()
    app = _build_app(db, role="member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/audit/projects/{PROJECT_ID}/events")
    assert res.status_code == 403, res.text


async def test_project_audit_endpoint_404s_on_invalid_project_id_format():
    """Non-UUID path param → 422 from FastAPI's path validator
    (not a hand-rolled 404). Pin the shape so an admin who pastes
    a stale slug doesn't get a confusing 500."""
    db = _FakeSession()
    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/audit/projects/not-a-uuid/events")
    assert res.status_code == 422, res.text
