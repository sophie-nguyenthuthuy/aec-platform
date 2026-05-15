"""Tests for EquipmentRental router.

Coverage:
  * Create rental + validate dates / rate bounds
  * Daily log + UQ(rental, log_date) duplicate detection
  * Invoice reconciliation math (variance = claimed - per_logs)
  * Utilization KPI (used / billable, with idle-heavy surfacing)
"""

from __future__ import annotations

from datetime import date
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
        email="pm@example.com",
    )


def _mock_session(captured: list, *, query_result=None, scalar=None):
    class _R:
        def __init__(self, v):
            self._v = v
            self.rowcount = 1

        def mappings(self):
            return self

        def one_or_none(self):
            return self._v

        def one(self):
            return self._v or {}

        def all(self):
            return self._v if isinstance(self._v, list) else []

        def scalar_one(self):
            if scalar is not None:
                return scalar
            return self._v

        def scalar_one_or_none(self):
            return self._v

    async def fake_execute(stmt, params=None):
        captured.append((str(stmt), dict(params or {})))
        return _R(query_result)

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)
    sess.commit = AsyncMock()

    def factory(*a, **kw):
        class _Ctx:
            async def __aenter__(self_inner):
                return sess

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()

    return factory


def test_create_rental_member_succeeds(client):
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    captured: list = []
    with patch(
        "routers.equipment_rental.TenantAwareSession",
        _mock_session(captured),
    ):
        resp = client.post(
            f"/api/v1/equipment/projects/{uuid4()}/rentals",
            json={
                "equipment_type": "crane",
                "equipment_name": "Cẩu tháp TC5610",
                "supplier_name": "Cty Cho thuê Máy Hà Nội",
                "rate_vnd_per_day": 3_500_000,
                "planned_start": "2026-06-01",
                "planned_finish": "2026-08-31",
            },
        )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert "id" in body
    assert any("INSERT INTO equipment_rentals" in s for s, _ in captured)


def test_create_rental_validates_planned_dates_pydantic(client):
    """planned_finish < planned_start is a DB check, but date-string
    validation runs at Pydantic level for malformed input."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    with patch(
        "routers.equipment_rental.TenantAwareSession",
        _mock_session([]),
    ):
        resp = client.post(
            f"/api/v1/equipment/projects/{uuid4()}/rentals",
            json={
                "equipment_type": "crane",
                "equipment_name": "X",  # too short → 422
                "supplier_name": "Cty Y",
                "rate_vnd_per_day": 1_000_000,
                "planned_start": "2026-06-01",
                "planned_finish": "2026-08-31",
            },
        )
    assert resp.status_code == 422


def test_create_rental_rate_must_be_nonneg(client):
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    with patch(
        "routers.equipment_rental.TenantAwareSession",
        _mock_session([]),
    ):
        resp = client.post(
            f"/api/v1/equipment/projects/{uuid4()}/rentals",
            json={
                "equipment_type": "crane",
                "equipment_name": "Cẩu tháp",
                "supplier_name": "Cty A",
                "rate_vnd_per_day": -100,  # ge=0
                "planned_start": "2026-06-01",
                "planned_finish": "2026-08-31",
            },
        )
    assert resp.status_code == 422


def test_log_usage_duplicate_returns_409(client):
    """UQ on (rental, log_date) → 409 on duplicate."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")

    async def raising_execute(stmt, params=None):
        sql = str(stmt)
        if "INSERT INTO equipment_rental_logs" in sql:
            raise RuntimeError(
                "duplicate key value violates unique constraint "
                '"uq_equipment_log_rental_date"'
            )

        class _R:
            rowcount = 1

            def mappings(self):
                return self

            def one_or_none(self):
                return None

            def scalar_one_or_none(self):
                # rental existence check → exists
                return 1

        return _R()

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=raising_execute)
    sess.commit = AsyncMock()

    def factory(*a, **kw):
        class _Ctx:
            async def __aenter__(self_inner):
                return sess

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()

    with patch("routers.equipment_rental.TenantAwareSession", factory):
        resp = client.post(
            f"/api/v1/equipment/rentals/{uuid4()}/logs",
            json={"log_date": "2026-06-05", "usage_state": "used"},
        )
    assert resp.status_code == 409


def test_log_invalid_usage_state_returns_422(client):
    """`usage_state` must be one of the 4 Literal values."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    with patch(
        "routers.equipment_rental.TenantAwareSession",
        _mock_session([]),
    ):
        resp = client.post(
            f"/api/v1/equipment/rentals/{uuid4()}/logs",
            json={"log_date": "2026-06-05", "usage_state": "broken"},
        )
    assert resp.status_code == 422


def test_invoice_reconciliation_computes_variance(client):
    """billable_days_per_logs × rate vs amount_claimed → variance with
    a verdict (ok / review / overbilled)."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")

    # Rental rate 3.5M/day. Logs show 22 billable days. NCC bills 25
    # days × 3.5M = 87.5M → variance +10.5M (overbilled).
    call_state = {"n": 0}

    async def fake_execute(stmt, params=None):
        call_state["n"] += 1
        sql = str(stmt)

        class _R:
            def __init__(self):
                self.rowcount = 1

            def mappings(self):
                return self

            def one_or_none(self):
                if "SELECT rate_vnd_per_day" in sql:
                    return {"rate_vnd_per_day": 3_500_000}
                return None

            def scalar_one(self):
                if "SELECT COUNT(*)" in sql:
                    return 22  # 22 billable days per our logs
                return 0

        return _R()

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)
    sess.commit = AsyncMock()

    def factory(*a, **kw):
        class _Ctx:
            async def __aenter__(self_inner):
                return sess

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()

    with patch("routers.equipment_rental.TenantAwareSession", factory):
        resp = client.post(
            f"/api/v1/equipment/rentals/{uuid4()}/invoices",
            json={
                "invoice_number": "HD-2026-0042",
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
                "billable_days_claimed": 25,
                "amount_vnd_claimed": 87_500_000,
            },
        )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["billable_days_per_logs"] == 22
    assert body["amount_vnd_per_logs"] == 22 * 3_500_000  # 77M
    assert body["variance_vnd"] == 87_500_000 - 77_000_000  # +10.5M
    assert body["verdict"] == "overbilled"


def test_invoice_reconciliation_admin_only(client):
    """Member can log usage but cannot reconcile invoices."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    with patch(
        "routers.equipment_rental.TenantAwareSession",
        _mock_session([], query_result={"rate_vnd_per_day": 1_000_000}),
    ):
        resp = client.post(
            f"/api/v1/equipment/rentals/{uuid4()}/invoices",
            json={
                "invoice_number": "X",
                "period_start": "2026-06-01",
                "period_end": "2026-06-30",
                "billable_days_claimed": 10,
                "amount_vnd_claimed": 10_000_000,
            },
        )
    assert resp.status_code == 403


def test_utilization_kpi_computes_correctly(client):
    """utilization_pct = used / (used + idle), excluding maintenance + off."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")

    async def fake_execute(stmt, params=None):
        sql = str(stmt)

        class _R:
            def mappings(self):
                return self

            def all(self):
                if "HAVING COUNT" in sql:
                    # No idle-heavy rentals in this scenario
                    return []
                return []

            def one(self):
                if "AS total_days" in sql:
                    return {
                        "total_days": 60,
                        "used": 40,
                        "idle": 10,
                        "maint": 5,
                        "off": 5,
                        "fuel_cost": 8_000_000,
                    }
                return {}

        return _R()

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)
    sess.commit = AsyncMock()

    def factory(*a, **kw):
        class _Ctx:
            async def __aenter__(self_inner):
                return sess

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()

    with patch("routers.equipment_rental.TenantAwareSession", factory):
        resp = client.get(
            f"/api/v1/equipment/projects/{uuid4()}/utilization?days=30"
        )

    assert resp.status_code == 200
    body = resp.json()["data"]
    # used=40, idle=10, billable=50, utilization = 40/50 = 80.0%
    assert body["used_days"] == 40
    assert body["idle_days"] == 10
    assert body["billable_days"] == 50
    assert body["utilization_pct"] == 80.0
    assert body["total_fuel_cost_vnd"] == 8_000_000
    assert body["idle_heavy_rentals"] == []


def test_utilization_handles_zero_days(client):
    """Empty window (no logs) → utilization_pct = 0, not division-by-zero crash."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")

    async def fake_execute(stmt, params=None):
        class _R:
            def mappings(self):
                return self

            def all(self):
                return []

            def one(self):
                return {
                    "total_days": 0,
                    "used": 0,
                    "idle": 0,
                    "maint": 0,
                    "off": 0,
                    "fuel_cost": 0,
                }

        return _R()

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)
    sess.commit = AsyncMock()

    def factory(*a, **kw):
        class _Ctx:
            async def __aenter__(self_inner):
                return sess

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()

    with patch("routers.equipment_rental.TenantAwareSession", factory):
        resp = client.get(
            f"/api/v1/equipment/projects/{uuid4()}/utilization?days=30"
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["utilization_pct"] == 0.0
