"""Tests for billing — plan catalogue, VietQR checkout flow, feature gates.

DB-touching paths use a mocked AdminSessionFactory. The Stripe path is
not exercised in unit tests (live SDK needs credentials); we cover the
"sdk missing → 503" failure path so a misconfigured deploy fails loud.
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


def _auth_ctx(role: str = "owner") -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=role,
        email="owner@example.com",
    )


# ---------- Plan catalogue ----------


def test_list_plans_is_public(client):
    """`GET /api/v1/billing/plans` returns the catalogue without auth."""
    resp = client.get("/api/v1/billing/plans")
    assert resp.status_code == 200
    body = resp.json()["data"]
    slugs = [p["slug"] for p in body["plans"]]
    assert slugs == ["starter", "pro", "enterprise"]

    pro = next(p for p in body["plans"] if p["slug"] == "pro")
    assert pro["price_vnd_monthly"] == 4_900_000
    assert pro["max_projects"] == 10
    assert "PDF báo cáo dự án + biên bản bàn giao" in pro["features_vi"]


# ---------- Plan definitions (pure) ----------


def test_plan_definition_falls_back_to_starter_for_unknown():
    """Unknown plan slug → falls back to starter (defensive)."""
    from services.billing import plan_definition

    p = plan_definition("nonsense-tier")
    assert p.slug == "starter"


def test_can_use_feature_gates():
    """Plan gating: pdf_reports + audit_export are Pro+; sso is Enterprise."""
    from services.billing import can_use_feature

    assert can_use_feature("starter", "pdf_reports") is False
    assert can_use_feature("starter", "drawbridge_qa") is True

    assert can_use_feature("pro", "pdf_reports") is True
    assert can_use_feature("pro", "sso") is False

    assert can_use_feature("enterprise", "sso") is True
    assert can_use_feature("enterprise", "anything-new") is True


def test_make_vietqr_reference_shape():
    """Reference format: AEC-<PLAN>-<YYYYMM>-<ORG8>."""
    from services.billing import make_vietqr_reference

    ref = make_vietqr_reference(
        organization_id="12345678-1234-1234-1234-123456789abc", plan="pro"
    )
    assert ref.startswith("AEC-PRO-")
    parts = ref.split("-")
    assert len(parts) == 4
    assert parts[0] == "AEC"
    assert parts[1] == "PRO"
    assert len(parts[2]) == 6  # YYYYMM
    assert len(parts[3]) == 8  # ORG8


# ---------- VietQR checkout (DB-mocked) ----------


def _mock_session(captured: list, *, query_result=None):
    """Build a TenantAware/Admin-style async session context."""

    class _Result:
        def __init__(self, val):
            self._val = val

        def mappings(self):
            return self

        def one_or_none(self):
            return self._val

        def one(self):
            return self._val or {}

        def all(self):
            return self._val or []

        def scalar_one(self):
            return self._val

    async def fake_execute(stmt, params=None):
        sql = str(stmt)
        captured.append((sql, dict(params or {})))
        return _Result(query_result)

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)
    sess.commit = AsyncMock()

    def _factory(*a, **kw):
        class _Ctx:
            async def __aenter__(self_inner):
                return sess

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()

    return _factory


def test_vietqr_checkout_rejects_enterprise(client):
    """Enterprise has no self-serve price — must redirect to sales."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("owner")
    captured: list = []
    with patch("routers.billing.AdminSessionFactory", _mock_session(captured)):
        resp = client.post("/api/v1/billing/checkout/vietqr?plan=enterprise")
    assert resp.status_code == 400
    # Error envelope: errors[0].message carries the detail
    msg = _error_message(resp)
    assert "enterprise" in msg.lower()


def test_vietqr_checkout_requires_owner(client):
    """Member role cannot upgrade — owner only."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    captured: list = []
    with patch("routers.billing.AdminSessionFactory", _mock_session(captured)):
        resp = client.post("/api/v1/billing/checkout/vietqr?plan=pro")
    assert resp.status_code == 403


def test_vietqr_checkout_creates_reference_and_pending_invoice(client):
    """Owner kicks off checkout → reference returned, subscription
    flipped to pending_payment, invoice row inserted as pending."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("owner")
    captured: list = []
    with patch(
        "routers.billing.AdminSessionFactory",
        _mock_session(captured, query_result={"id": uuid4()}),
    ):
        resp = client.post("/api/v1/billing/checkout/vietqr?plan=pro")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["plan"] == "pro"
    assert body["amount_vnd"] == 4_900_000
    assert body["reference"].startswith("AEC-PRO-")
    assert "memo_format" in body["bank"]

    # Two SQL writes: UPDATE subscriptions + INSERT invoices
    update_seen = any(
        "UPDATE subscriptions" in s and "pending_payment" in s for s, _ in captured
    )
    insert_seen = any("INSERT INTO invoices" in s for s, _ in captured)
    assert update_seen
    assert insert_seen


def test_vietqr_confirm_activates_subscription(client):
    """Owner clicks 'Tôi đã chuyển khoản' → status flips active +
    org.plan mirrored + invoice marked paid."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("owner")
    captured: list = []
    auth_org = uuid4()
    sub_row = {
        "id": uuid4(),
        "organization_id": auth_org,
        "plan": "pro",
    }
    with patch(
        "routers.billing.AdminSessionFactory",
        _mock_session(captured, query_result=sub_row),
    ):
        resp = client.post("/api/v1/billing/vietqr/AEC-PRO-202605-DEADBEEF/confirm")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "active"

    # Verify the three SQL writes happened
    activate = any("status = 'active'" in s for s, _ in captured)
    mirror = any("UPDATE organizations" in s and "plan = :plan" in s for s, _ in captured)
    paid = any("status = 'paid'" in s for s, _ in captured)
    assert activate and mirror and paid


# ---------- Stripe (configured-fail paths) ----------


def test_stripe_checkout_503_without_secret_key(client, monkeypatch):
    """No STRIPE_SECRET_KEY set → 503 with hint to use VietQR."""
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("owner")
    resp = client.post("/api/v1/billing/checkout/stripe?plan=pro")
    assert resp.status_code == 503
    assert "vietqr" in _error_message(resp).lower()


def _error_message(resp) -> str:
    body = resp.json()
    if isinstance(body, dict) and body.get("errors"):
        return body["errors"][0].get("message", "")
    return body.get("detail", "") if isinstance(body, dict) else ""


def test_stripe_webhook_400_without_signature(client):
    """Stripe webhook without Stripe-Signature header → 400."""
    resp = client.post("/api/v1/billing/webhooks/stripe", content=b"{}")
    assert resp.status_code == 400
