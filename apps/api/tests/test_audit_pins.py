"""Audit row pinning (cycle U3).

Pinned seams:
  1. `POST /audit/events/{id}/pin` UPSERTs a pin row. Cross-tenant
     event_id → 404 (audit row's org doesn't match caller's).
  2. `DELETE /audit/events/{id}/pin` is idempotent — both clicks
     return 200.
  3. `GET /audit/pins` returns per-user pinned rows joined to the
     audit_event projection + pin metadata.
  4. Admin-gated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
EVENT_ID = UUID("11111111-1111-1111-1111-111111111111")


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.first.return_value = None
        r.rowcount = 0
        r.mappings.return_value.all.return_value = []
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


def _audit_row_exists() -> Any:
    """SELECT result for the audit-row ownership check — returns
    a tuple-like row signaling existence."""
    r = MagicMock()
    r.first.return_value = (EVENT_ID,)
    return r


def _audit_row_missing() -> Any:
    r = MagicMock()
    r.first.return_value = None
    return r


def _upsert_result() -> Any:
    """Generic INSERT/DELETE result with rowcount=1."""
    r = MagicMock()
    r.rowcount = 1
    return r


# ---------- POST /events/{id}/pin ----------


async def test_pin_endpoint_404s_on_cross_tenant_event():
    """audit_events.organization_id ≠ caller's org → 404. Pin so a
    cross-tenant event_id leak fails closed."""
    db = _FakeSession()
    db.push(_audit_row_missing())  # ownership check returns nothing

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/audit/events/{EVENT_ID}/pin",
            json={"note": "smoking gun"},
        )
    assert res.status_code == 404, res.text
    # Critical: we MUST NOT have written the pin row.
    insert_calls = [c for c in db.calls if "INSERT INTO audit_pins" in str(c[0])]
    assert len(insert_calls) == 0


async def test_pin_endpoint_upserts_with_note():
    """Happy path: ownership check passes, INSERT … ON CONFLICT
    runs. Pin the SQL shape so a refactor that drops the upsert
    creates duplicate-PK errors."""
    db = _FakeSession()
    db.push(_audit_row_exists())  # ownership check
    db.push(_upsert_result())  # INSERT … ON CONFLICT

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/audit/events/{EVENT_ID}/pin",
            json={"note": "smoking gun for outage 2026-05-01"},
        )
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["pinned"] is True
    assert body["note"] == "smoking gun for outage 2026-05-01"

    upsert_sql = str(db.calls[1][0])
    assert "ON CONFLICT (audit_event_id, pinned_by)" in upsert_sql, (
        "Pin INSERT must use ON CONFLICT for idempotent re-pinning."
    )
    params = db.calls[1][1]
    assert params["event_id"] == str(EVENT_ID)
    assert params["user"] == str(USER_ID)
    assert params["note"] == "smoking gun for outage 2026-05-01"


async def test_pin_endpoint_accepts_no_note():
    """Quick "flag this row" pins don't need a note. Pin the
    optional default."""
    db = _FakeSession()
    db.push(_audit_row_exists())
    db.push(_upsert_result())

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/audit/events/{EVENT_ID}/pin",
            json={},  # no note field
        )
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["pinned"] is True
    assert body["note"] is None


# ---------- DELETE /events/{id}/pin ----------


async def test_unpin_endpoint_idempotent_on_no_row():
    """Click unpin twice — both return 200 with `removed` flag.
    Frontend's optimistic update doesn't special-case the no-row
    branch."""
    db = _FakeSession()
    no_row_result = MagicMock()
    no_row_result.rowcount = 0
    db.push(no_row_result)

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.delete(f"/api/v1/audit/events/{EVENT_ID}/pin")
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["pinned"] is False
    assert body["removed"] is False


async def test_unpin_endpoint_returns_removed_true_on_delete():
    db = _FakeSession()
    db.push(_upsert_result())  # rowcount=1

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.delete(f"/api/v1/audit/events/{EVENT_ID}/pin")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["removed"] is True


# ---------- GET /pins ----------


async def test_list_pins_returns_per_user_rows():
    """The listing scopes via `pinned_by = caller's user_id` —
    Bob doesn't see Alice's pins. Pin via the SQL bound params."""
    db = _FakeSession()
    pinned_at = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    list_result = MagicMock()
    list_result.mappings.return_value.all.return_value = [
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
            "ip": None,
            "user_agent": None,
            "created_at": datetime(2026, 5, 1, 11, 0, tzinfo=UTC),
            "pin_note": "smoking gun",
            "pin_pinned_at": pinned_at,
        }
    ]
    db.push(list_result)

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/audit/pins")
    assert res.status_code == 200, res.text
    rows = res.json()["data"]
    assert len(rows) == 1
    # Pin metadata appears alongside the audit-event projection.
    assert rows[0]["pin_note"] == "smoking gun"
    assert rows[0]["action"] == "pulse.change_order.approve"

    # Bound params: pinned_by = caller's user_id, org = caller's org.
    sql, params = db.calls[0]
    assert "WHERE p.pinned_by = :user" in str(sql)
    assert "a.organization_id = :org" in str(sql)
    assert params["user"] == str(USER_ID)
    assert params["org"] == str(ORG_ID)


# ---------- RBAC ----------


async def test_pin_endpoints_403_for_member():
    """All three endpoints are admin-only — audit content is
    sensitive, and pinning surfaces it visually at the top of
    the listing."""
    db = _FakeSession()
    app = _build_app(db, role="member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res_pin = await ac.post(f"/api/v1/audit/events/{EVENT_ID}/pin", json={})
        res_unpin = await ac.delete(f"/api/v1/audit/events/{EVENT_ID}/pin")
        res_list = await ac.get("/api/v1/audit/pins")
    assert res_pin.status_code == 403
    assert res_unpin.status_code == 403
    assert res_list.status_code == 403
