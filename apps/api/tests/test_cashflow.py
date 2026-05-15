"""Tests for cashflow router — schema validation + endpoint posture.

DB-touching paths use a mocked TenantAwareSession. The forecast
aggregation SQL itself is covered by integration tests when run
against a live Postgres.
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
        email="user@example.com",
    )


def _mock_tenant_session(captured: list, *, query_result=None):
    """Tenant-session ctx manager that records every SQL + returns
    canned data for read paths."""

    class _Result:
        def __init__(self, val):
            self._v = val
            self.rowcount = 1

        def mappings(self):
            return self

        def all(self):
            return self._v or []

        def one_or_none(self):
            return self._v

        def one(self):
            return self._v or {}

        def scalar_one(self):
            return self._v

    async def fake_execute(stmt, params=None):
        captured.append((str(stmt), dict(params or {})))
        return _Result(query_result)

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


def test_create_entry_requires_admin(client):
    """Member role cannot create cashflow entries — admin gate."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    captured: list = []
    with patch(
        "routers.cashflow.TenantAwareSession",
        _mock_tenant_session(captured),
    ):
        resp = client.post(
            f"/api/v1/cashflow/projects/{uuid4()}/entries",
            json={
                "kind": "inflow",
                "label": "Tạm ứng",
                "amount_vnd": 100_000_000,
                "expected_date": "2026-06-01",
            },
        )
    assert resp.status_code == 403


def test_create_entry_validates_payload(client):
    """Bad payload (negative amount) rejected at the Pydantic layer."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")
    captured: list = []
    with patch(
        "routers.cashflow.TenantAwareSession",
        _mock_tenant_session(captured),
    ):
        resp = client.post(
            f"/api/v1/cashflow/projects/{uuid4()}/entries",
            json={
                "kind": "inflow",
                "label": "x",  # too short (min_length=2)
                "amount_vnd": -50,  # ge=0
                "expected_date": "2026-06-01",
            },
        )
    assert resp.status_code == 422


def test_create_entry_admin_succeeds(client):
    """Happy path — admin creates inflow, SQL fires, returns 201."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")
    captured: list = []
    with patch(
        "routers.cashflow.TenantAwareSession",
        _mock_tenant_session(captured),
    ):
        resp = client.post(
            f"/api/v1/cashflow/projects/{uuid4()}/entries",
            json={
                "kind": "inflow",
                "label": "Thanh toán 30% nghiệm thu kết cấu",
                "amount_vnd": 850_000_000,
                "expected_date": "2026-06-15",
            },
        )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert "id" in body

    # Verify INSERT fired with the right amount + label.
    insert_call = next(
        (s, p) for s, p in captured if "INSERT INTO cashflow_entries" in s
    )
    sql, params = insert_call
    assert params["amt"] == 850_000_000
    assert params["kind"] == "inflow"


def test_delete_entry_owner_only(client):
    """Admin cannot delete (only owner). Defense against fat-finger drift."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")
    with patch(
        "routers.cashflow.TenantAwareSession",
        _mock_tenant_session([]),
    ):
        resp = client.delete(f"/api/v1/cashflow/entries/{uuid4()}")
    assert resp.status_code == 403


def test_update_entry_no_fields_returns_400(client):
    """PATCH with empty body → 400 not 200 — silent no-op would mask bugs."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")
    with patch(
        "routers.cashflow.TenantAwareSession",
        _mock_tenant_session([]),
    ):
        resp = client.patch(f"/api/v1/cashflow/entries/{uuid4()}", json={})
    assert resp.status_code == 400


def test_record_actual_returns_running_total(client):
    """Recording a payment returns the running paid total."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")

    # First call returns entry row, subsequent INSERT, then SUM returns 100M
    call_count = {"n": 0}

    async def fake_execute(stmt, params=None):
        sql = str(stmt)
        call_count["n"] += 1

        class _R:
            def mappings(self):
                return self

            def one_or_none(self):
                # First SELECT returns entry shape
                if "SELECT amount_vnd, status FROM cashflow_entries" in sql:
                    return {"amount_vnd": 200_000_000, "status": "invoiced"}
                return None

            def scalar_one(self):
                # Running total query
                if "SUM(amount_vnd)" in sql:
                    return 100_000_000
                return None

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

    with patch("routers.cashflow.TenantAwareSession", factory):
        resp = client.post(
            f"/api/v1/cashflow/entries/{uuid4()}/actuals",
            json={"amount_vnd": 100_000_000, "paid_on": "2026-06-15"},
        )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["running_total_vnd"] == 100_000_000


def test_forecast_computes_cumulative_correctly(client):
    """Forecast endpoint aggregates inflow/outflow + builds cumulative
    running sum. Deficit months surfaced in summary."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")

    # Synthesise 3 months: +1B, -500M, -800M → cum = +1B, +500M, -300M
    fake_rows = [
        {
            "month": _month_dt(2026, 6),
            "inflow": 1_000_000_000,
            "outflow": 0,
        },
        {
            "month": _month_dt(2026, 7),
            "inflow": 0,
            "outflow": 500_000_000,
        },
        {
            "month": _month_dt(2026, 8),
            "inflow": 0,
            "outflow": 800_000_000,
        },
    ]

    async def fake_execute(stmt, params=None):
        class _R:
            def mappings(self):
                return self

            def all(self):
                return fake_rows

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

    with patch("routers.cashflow.TenantAwareSession", factory):
        resp = client.get(f"/api/v1/cashflow/projects/{uuid4()}/forecast")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body["series"]) == 3
    assert body["series"][0]["cumulative_vnd"] == 1_000_000_000
    assert body["series"][1]["cumulative_vnd"] == 500_000_000
    assert body["series"][2]["cumulative_vnd"] == -300_000_000
    # August is the only deficit month
    assert len(body["summary"]["deficit_months"]) == 1
    assert body["summary"]["total_net_vnd"] == -300_000_000


def _month_dt(year: int, month: int):
    """Postgres date_trunc('month', ...) returns a timestamp at midnight."""
    from datetime import datetime

    return datetime(year, month, 1)
