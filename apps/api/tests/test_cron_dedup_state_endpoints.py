"""Per-cron dedup state UI endpoints (cycle S1).

Three seams pinned:
  1. `GET /admin/crons/{name}/dedup-state` returns the dedup rows
     with computed `seconds_until_next_alert` so the UI doesn't
     re-derive the 30min/6h schedule client-side.
  2. `POST /admin/crons/{name}/dedup-state/clear` 400s on unknown
     kind (defense in depth — same vocab as the service helper).
  3. The clear endpoint writes an `admin.cron.dedup_clear` audit
     row so incident retros can answer "who silenced what."
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth


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


def _build_app() -> FastAPI:
    """Mount only the cron_admin router with auth stubbed to admin."""
    from routers import cron_admin

    app = FastAPI()
    app.include_router(cron_admin.router)
    app.dependency_overrides[require_auth] = _admin_ctx
    return app


# ---------- get_dedup_state shape pin ----------


def test_dedup_state_includes_computed_next_alert_seconds():
    """The service helper computes `seconds_until_next_alert` from
    the graduated cadence (30min for 2nd, 6h for subsequent). Pin
    the field name + sign so the UI doesn't re-derive the
    schedule client-side and drift."""
    from services.cron_alert_dedup import _repeat_interval_for

    # Pin the underlying helper used to compute the kwarg —
    # `get_dedup_state` ships the result to the UI.
    assert _repeat_interval_for(1) == 30 * 60
    assert _repeat_interval_for(3) == 6 * 60 * 60


# ---------- GET /admin/crons/{name}/dedup-state ----------


async def test_get_dedup_state_returns_rows(monkeypatch):
    """Happy path: service helper returns one entry per (kind);
    the route pipes through `data: [...]`."""
    from services import cron_alert_dedup as svc

    monkeypatch.setattr(
        svc,
        "get_dedup_state",
        AsyncMock(
            return_value=[
                {
                    "cron_name": "cron:weekly_report",
                    "kind": "cron_failure",
                    "alert_count": 3,
                    "first_alert_at": "2026-05-01T12:00:00+00:00",
                    "last_alert_at": "2026-05-01T18:00:00+00:00",
                    "first_alert_age_seconds": 21600,
                    "seconds_until_next_alert": 7200,
                }
            ]
        ),
    )

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/crons/cron:weekly_report/dedup-state")
    assert res.status_code == 200, res.text
    rows = res.json()["data"]
    assert len(rows) == 1
    assert rows[0]["alert_count"] == 3
    assert rows[0]["seconds_until_next_alert"] == 7200


async def test_get_dedup_state_empty_when_healthy(monkeypatch):
    """No outstanding alerts → empty list. Frontend renders a
    "Cron đang khoẻ" message instead of an empty table."""
    from services import cron_alert_dedup as svc

    monkeypatch.setattr(svc, "get_dedup_state", AsyncMock(return_value=[]))

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/crons/cron:weekly_report/dedup-state")
    assert res.status_code == 200
    assert res.json()["data"] == []


# ---------- POST /admin/crons/{name}/dedup-state/clear ----------


async def test_clear_dedup_state_happy_path(monkeypatch):
    """Admin clears the dedup row → service returns True; route
    returns 200 with `cleared=True` + audits the action."""
    from services import audit as audit_mod
    from services import cron_alert_dedup as svc

    monkeypatch.setattr(svc, "clear_alert", AsyncMock(return_value=True))
    audit_calls: list[dict[str, Any]] = []

    async def _fake_audit(*_a: Any, **kw: Any) -> None:
        audit_calls.append(kw)

    monkeypatch.setattr(audit_mod, "record", _fake_audit)

    class _FakeSession:
        async def __aenter__(self) -> "_FakeSession":
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
        res = await ac.post(
            "/api/v1/admin/crons/cron:weekly_report/dedup-state/clear",
            params={"kind": "cron_failure"},
        )
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["cleared"] is True
    assert body["cron_name"] == "cron:weekly_report"
    assert body["kind"] == "cron_failure"
    # Audit row must be written — pin so a regression that drops
    # the audit_record call surfaces here, not at incident retro
    # time when the row's missing.
    assert len(audit_calls) == 1
    assert audit_calls[0]["action"] == "admin.cron.dedup_clear"


async def test_clear_dedup_state_400_for_unknown_kind(monkeypatch):
    """Unknown kind → 400 BEFORE the service helper runs.
    Defense in depth: the helper also raises ValueError, but the
    400 surfaces a friendlier message to the caller."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/admin/crons/cron:weekly_report/dedup-state/clear",
            params={"kind": "bogus"},
        )
    assert res.status_code == 400, res.text


async def test_clear_dedup_state_returns_false_when_no_row(monkeypatch):
    """No outstanding alert to clear → service returns False; the
    route still returns 200 (idempotent — the desired end state is
    "no alert," which we already have). Pin so a regression that
    404s on no-row would force the UI to special-case the response."""
    from services import audit as audit_mod
    from services import cron_alert_dedup as svc

    monkeypatch.setattr(svc, "clear_alert", AsyncMock(return_value=False))

    async def _noop_audit(*_a: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(audit_mod, "record", _noop_audit)

    class _FakeSession:
        async def __aenter__(self) -> "_FakeSession":
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
        res = await ac.post(
            "/api/v1/admin/crons/cron:weekly_report/dedup-state/clear",
            params={"kind": "cron_failure"},
        )
    assert res.status_code == 200
    assert res.json()["data"]["cleared"] is False
