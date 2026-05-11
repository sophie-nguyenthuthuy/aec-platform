"""Operational health widget endpoint (cycle S2).

Pinned seams:
  1. The endpoint returns a flat dict with the four counts the
     widget renders. The frontend keys off these exact field names;
     a refactor that renames "stuck_crons" → "crons_stuck" would
     silently break the widget.
  2. Defensive zero-on-failure for missing tables — the widget
     should NEVER 500 the inbox just because audit_exports hasn't
     been migrated yet on this tenant.
  3. Admin-gated; member callers 403.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
USER_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


def _ctx(role: str = "admin") -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="ops@example.com",
    )


def _build_app(role: str = "admin") -> FastAPI:
    """Mount the admin router with auth stubbed."""
    from routers import admin as admin_router

    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[require_auth] = lambda: _ctx(role)
    return app


# ---------- Field shape ----------


async def test_operational_health_returns_four_pinned_counts(monkeypatch):
    """The widget renders four counts: unused_api_keys, stuck_crons,
    pending_audit_exports, failing_webhook_subscriptions. Pin the
    exact field names."""
    from services import api_keys as api_keys_mod
    from services import cron_alerts as cron_alerts_mod

    # Stub each data source so the test doesn't touch the DB.
    monkeypatch.setattr(
        api_keys_mod,
        "find_unused_keys",
        AsyncMock(return_value=[{"id": "x"}, {"id": "y"}]),  # 2 unused
    )
    monkeypatch.setattr(
        cron_alerts_mod,
        "_running_crons_with_baseline",
        AsyncMock(
            return_value=[
                # Stuck row: elapsed > 3× p95 with sufficient samples.
                {"elapsed_ms": 60_000, "p95_ms": 1000, "sample_count": 10},
                # Healthy row: elapsed < 3× p95 — should NOT count.
                {"elapsed_ms": 500, "p95_ms": 1000, "sample_count": 10},
            ]
        ),
    )

    # Stub session factory so the SQL queries return canned counts.
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def execute(self, *_a, **_kw):
            r = MagicMock()
            # Return 3 for both webhook + audit-export count queries.
            r.scalar_one.return_value = 3
            return r

    # Patch the AdminSessionFactory binding INSIDE the admin router
    # module — the router does `from db.session import AdminSessionFactory`
    # at module load, so patching `db.session.AdminSessionFactory`
    # alone wouldn't reach the call site.
    from routers import admin as admin_router

    monkeypatch.setattr(admin_router, "AdminSessionFactory", lambda: _FakeSession())

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/operational-health")

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    # Exact field set — pin so a rename doesn't silently break the widget.
    assert set(data.keys()) == {
        "unused_api_keys",
        "stuck_crons",
        "pending_audit_exports",
        "failing_webhook_subscriptions",
    }
    assert data["unused_api_keys"] == 2
    assert data["stuck_crons"] == 1  # only one of the two `running` rows is stuck
    assert data["pending_audit_exports"] == 3
    assert data["failing_webhook_subscriptions"] == 3


# ---------- Defensive: missing audit_exports table ----------


async def test_operational_health_handles_missing_audit_exports_table(monkeypatch):
    """A tenant where `audit_exports` migration hasn't been applied
    (or got rolled back) should return 0 for that count, not 500
    the whole inbox. Pin the defense-in-depth."""
    from services import api_keys as api_keys_mod
    from services import cron_alerts as cron_alerts_mod

    monkeypatch.setattr(api_keys_mod, "find_unused_keys", AsyncMock(return_value=[]))
    monkeypatch.setattr(cron_alerts_mod, "_running_crons_with_baseline", AsyncMock(return_value=[]))

    class _FailingSession:
        """Session whose every execute() raises — simulates a missing
        table. The handler should swallow + return 0 for the audit-
        exports branch + the webhook branch handles its own try."""

        def __init__(self) -> None:
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def execute(self, *_a, **_kw):
            self.calls += 1
            # Webhook query (call 1) succeeds with 0; audit_exports
            # (call 2) raises to simulate the missing table.
            if self.calls == 1:
                r = MagicMock()
                r.scalar_one.return_value = 0
                return r
            raise RuntimeError('relation "audit_exports" does not exist')

    from routers import admin as admin_router

    fake = _FailingSession()
    monkeypatch.setattr(admin_router, "AdminSessionFactory", lambda: fake)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/operational-health")

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["pending_audit_exports"] == 0
    # Webhooks query succeeded → 0 (the test session returned 0).
    assert data["failing_webhook_subscriptions"] == 0


# ---------- RBAC ----------


async def test_operational_health_403_for_member():
    """Same gating as the rest of the admin namespace.
    Members/viewers can't see the operational-health counts."""
    app = _build_app(role="member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/operational-health")
    assert res.status_code == 403, res.text
