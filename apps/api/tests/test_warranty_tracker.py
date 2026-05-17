"""Tests for warranty_tracker router.

Coverage:
  * Auth + RBAC on claims (member can file, owner needed for nothing)
  * Cannot file claim against expired / non-active warranty
  * Auto-stamp resolved_on when status flips to resolved
  * Status filter shapes SQL bind
  * Summary KPI math (vendor_covered vs contractor_absorbed split)
"""

from __future__ import annotations

from datetime import date, timedelta
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


def _auth_ctx(role: str = "member") -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=role,
        email="pm@example.com",
    )


def _mock_session(captured: list, *, query_result=None, query_results=None):
    """If `query_results` (list) is given, each `execute` returns the
    next element. Else `query_result` is returned for every call."""
    call_idx = {"i": 0}

    class _R:
        def __init__(self, v):
            self._v = v
            self.rowcount = 1

        def mappings(self):
            return self

        def one_or_none(self):
            return self._v if not isinstance(self._v, list) else (self._v[0] if self._v else None)

        def one(self):
            return self._v if not isinstance(self._v, list) else (self._v[0] if self._v else {})

        def all(self):
            return self._v if isinstance(self._v, list) else []

        def scalar_one(self):
            return self._v

    async def fake_execute(stmt, params=None):
        captured.append((str(stmt), dict(params or {})))
        if query_results is not None:
            v = query_results[min(call_idx["i"], len(query_results) - 1)]
            call_idx["i"] += 1
            return _R(v)
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


def test_file_claim_member_can(client):
    """Member role can file — facilities team is usually member, not admin."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    captured: list = []
    # First execute returns the warranty lookup, second is the INSERT
    future_expiry = date.today() + timedelta(days=180)
    with patch(
        "routers.warranty_tracker.TenantAwareSession",
        _mock_session(
            captured,
            query_result={"id": uuid4(), "expiry_date": future_expiry, "status": "active"},
        ),
    ):
        resp = client.post(
            f"/api/v1/warranty-tracker/items/{uuid4()}/claims",
            json={
                "severity": "major",
                "summary": "Máy lạnh phòng 504 không lạnh",
                "reporter_name": "Nguyễn Văn A",
                "reporter_email": "owner@toa-nha.vn",
            },
        )
    assert resp.status_code == 201
    insert_seen = any("INSERT INTO warranty_claims" in s for s, _ in captured)
    assert insert_seen


def test_file_claim_rejects_short_summary(client):
    """Pydantic min_length=2 — defensive against empty submissions."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    with patch(
        "routers.warranty_tracker.TenantAwareSession",
        _mock_session([]),
    ):
        resp = client.post(
            f"/api/v1/warranty-tracker/items/{uuid4()}/claims",
            json={"severity": "major", "summary": "X"},
        )
    assert resp.status_code == 422


def test_file_claim_blocks_expired_warranty(client):
    """Warranty expired → cannot file new claim (must use dispute path)."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    expired = date.today() - timedelta(days=30)
    with patch(
        "routers.warranty_tracker.TenantAwareSession",
        _mock_session(
            [], query_result={"id": uuid4(), "expiry_date": expired, "status": "active"},
        ),
    ):
        resp = client.post(
            f"/api/v1/warranty-tracker/items/{uuid4()}/claims",
            json={"severity": "major", "summary": "Phát hiện rò rỉ ống nước tầng 2"},
        )
    assert resp.status_code == 400
    assert "expired" in str(resp.json()).lower()


def test_file_claim_blocks_inactive_warranty(client):
    """Warranty status != active → blocked."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    future = date.today() + timedelta(days=180)
    with patch(
        "routers.warranty_tracker.TenantAwareSession",
        _mock_session(
            [],
            query_result={"id": uuid4(), "expiry_date": future, "status": "voided"},
        ),
    ):
        resp = client.post(
            f"/api/v1/warranty-tracker/items/{uuid4()}/claims",
            json={"severity": "major", "summary": "Vấn đề về sàn"},
        )
    assert resp.status_code == 400


def test_update_claim_auto_stamps_resolved_on(client):
    """When PATCH flips status='resolved' without resolved_on, auto-stamp today."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    captured: list = []
    with patch(
        "routers.warranty_tracker.TenantAwareSession",
        _mock_session(captured),
    ):
        resp = client.patch(
            f"/api/v1/warranty-tracker/claims/{uuid4()}",
            json={"status": "resolved", "cost_vnd": 5_000_000, "paid_by": "vendor_covered"},
        )
    assert resp.status_code == 200
    # Verify the UPDATE SQL included resolved_on
    update_call = next(
        (s, p) for s, p in captured if "UPDATE warranty_claims" in s
    )
    _, params = update_call
    assert "resolved_on" in params
    assert params["resolved_on"] == date.today()
    assert params["paid_by"] == "vendor_covered"


def test_update_claim_no_fields_returns_400(client):
    """Empty PATCH body → 400 instead of silent no-op."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    with patch(
        "routers.warranty_tracker.TenantAwareSession",
        _mock_session([]),
    ):
        resp = client.patch(
            f"/api/v1/warranty-tracker/claims/{uuid4()}", json={}
        )
    assert resp.status_code == 400


def test_list_claims_status_filter_binds(client):
    """`?status=open` shapes the SQL WHERE clause."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    captured: list = []
    with patch(
        "routers.warranty_tracker.TenantAwareSession",
        _mock_session(captured, query_result=[]),
    ):
        resp = client.get(
            f"/api/v1/warranty-tracker/projects/{uuid4()}/claims?status=open"
        )
    assert resp.status_code == 200
    sql, params = captured[-1]
    assert "c.status = :status" in sql
    assert params["status"] == "open"


def test_expiring_default_window_90_days(client):
    """`days=90` is the default; rows ordered by expiry ASC."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    captured: list = []
    with patch(
        "routers.warranty_tracker.TenantAwareSession",
        _mock_session(captured, query_result=[]),
    ):
        resp = client.get(
            f"/api/v1/warranty-tracker/projects/{uuid4()}/expiring"
        )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["horizon_days"] == 90


def test_expiring_days_param_bounded(client):
    """days ∈ [7, 365]."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    resp = client.get(
        f"/api/v1/warranty-tracker/projects/{uuid4()}/expiring?days=5"
    )
    assert resp.status_code == 422


def test_summary_aggregates_vendor_vs_contractor_cost(client):
    """Summary KPI sums cost_vnd separately for vendor_covered vs
    contractor_absorbed. Load-bearing financial signal — proves warranty
    value to the building owner."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    with patch(
        "routers.warranty_tracker.TenantAwareSession",
        _mock_session(
            [],
            query_results=[
                {"active_count": 12, "expiring_30": 2, "expiring_90": 5},
                {
                    "open_count": 3,
                    "resolved_count": 8,
                    "rejected_count": 1,
                    "vendor_covered_vnd": 25_000_000,
                    "contractor_absorbed_vnd": 4_500_000,
                },
            ],
        ),
    ):
        resp = client.get(
            f"/api/v1/warranty-tracker/projects/{uuid4()}/summary"
        )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["active_count"] == 12
    assert body["expiring_30"] == 2
    assert body["open_claims"] == 3
    assert body["vendor_covered_vnd"] == 25_000_000
    assert body["contractor_absorbed_vnd"] == 4_500_000
