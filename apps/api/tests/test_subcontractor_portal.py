"""Tests for SubcontractorPortal.

Two surface areas:
  * Admin (auth-gated) — grant minting + revoke + assignment creation.
  * Public (token-auth) — sub views assignments + reports progress.

Token-related tests live at the unit level (no DB round-trip).
DB-touching tests mock TenantAwareSession + AdminSessionFactory.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
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


def _mock_session(captured: list, *, query_result=None):
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


# ---------- Token helpers (pure) ----------


def test_hash_token_is_deterministic():
    from services.subcontractor_tokens import hash_token

    h1 = hash_token("abc.def.ghi")
    h2 = hash_token("abc.def.ghi")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_hash_token_differs_per_input():
    from services.subcontractor_tokens import hash_token

    assert hash_token("a") != hash_token("b")


def test_mint_and_verify_roundtrip(monkeypatch):
    """A freshly-minted token decodes back to the same claims."""
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "a" * 32)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    # Force settings to re-read from env
    from core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    from services.subcontractor_tokens import (
        mint_subcontractor_token,
        verify_subcontractor_token,
    )

    grant_id = uuid4()
    org_id = uuid4()
    proj_id = uuid4()
    raw = mint_subcontractor_token(
        grant_id=grant_id,
        organization_id=org_id,
        project_id=proj_id,
        email="sub@example.com",
        ttl_days=7,
    )
    claims = verify_subcontractor_token(raw)
    assert claims.grant_id == grant_id
    assert claims.organization_id == org_id
    assert claims.project_id == proj_id
    assert claims.email == "sub@example.com"


def test_verify_rejects_rfq_audience(monkeypatch):
    """A token minted for the RFQ portal must NOT unlock the sub
    portal. Two-audience separation is the load-bearing security
    guard for cross-portal confusion."""
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "b" * 32)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    from core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    from services.rfq_tokens import mint_response_token
    from services.subcontractor_tokens import (
        TokenError,
        verify_subcontractor_token,
    )

    rfq_token = mint_response_token(rfq_id=uuid4(), supplier_id=uuid4())

    # The exact failure mode depends on the PyJWT check order — could
    # be 'audience mismatch' or 'missing claim'. Either way, the
    # security guard is "an RFQ token does NOT verify as a sub
    # token", which is what we assert.
    with pytest.raises(TokenError):
        verify_subcontractor_token(rfq_token)


def test_verify_rejects_malformed(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "c" * 32)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    from core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    from services.subcontractor_tokens import (
        TokenError,
        verify_subcontractor_token,
    )

    with pytest.raises(TokenError):
        verify_subcontractor_token("not-a-jwt")


# ---------- Admin endpoint posture ----------


def test_mint_grant_requires_admin(client):
    """Member cannot mint portal tokens — admin gate."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    with patch(
        "routers.subcontractor_portal.TenantAwareSession",
        _mock_session([]),
    ):
        resp = client.post(
            f"/api/v1/subcontractors/projects/{uuid4()}/grants",
            json={
                "subcontractor_name": "Cty TNHH XD A",
                "subcontractor_email": "sub@example.com",
            },
        )
    assert resp.status_code == 403


def test_mint_grant_returns_token_once(client, monkeypatch):
    """Happy path — admin mints, gets raw token in response (this is
    the ONLY time the raw token is visible)."""
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "d" * 32)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    from core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")
    captured: list = []
    with patch(
        "routers.subcontractor_portal.TenantAwareSession",
        _mock_session(captured),
    ):
        resp = client.post(
            f"/api/v1/subcontractors/projects/{uuid4()}/grants",
            json={
                "subcontractor_name": "Cty TNHH XD A",
                "subcontractor_email": "sub@example.com",
                "ttl_days": 90,
            },
        )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert "token" in body
    assert "portal_url" in body
    assert body["portal_url"].endswith(f"/subcontractor?t={body['token']}")
    assert "warning" in body
    # Verify INSERT fired with hashed token (not raw)
    insert_call = next(
        (s, p) for s, p in captured if "INSERT INTO subcontractor_portal_grants" in s
    )
    _, params = insert_call
    assert params["hash"] != body["token"]
    assert len(params["hash"]) == 64  # SHA-256 hex


def test_mint_grant_duplicate_active_returns_409(client, monkeypatch):
    """Active-grant-per-email-per-project UQ partial index → 409."""
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "e" * 32)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    from core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")

    async def raising_execute(stmt, params=None):
        if "INSERT INTO subcontractor_portal_grants" in str(stmt):
            raise RuntimeError(
                "duplicate key value violates unique constraint "
                '"ix_subportal_grants_active_email_project"'
            )

        class _R:
            rowcount = 1

            def mappings(self):
                return self

            def one_or_none(self):
                return None

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

    with patch("routers.subcontractor_portal.TenantAwareSession", factory):
        resp = client.post(
            f"/api/v1/subcontractors/projects/{uuid4()}/grants",
            json={
                "subcontractor_name": "Công ty TNHH XD A",
                "subcontractor_email": "dup@example.com",
            },
        )

    assert resp.status_code == 409


# ---------- Public endpoint posture ----------


def test_public_dashboard_rejects_missing_token(client):
    """Public route without ?t= → 422 (Pydantic validation)."""
    resp = client.get("/api/v1/public/sub")
    assert resp.status_code == 422


def test_public_dashboard_rejects_invalid_token(client):
    """Bad token → 401 from _resolve_grant_or_401."""
    captured: list = []
    with patch(
        "routers.subcontractor_portal.AdminSessionFactory",
        _mock_session(captured),
    ):
        resp = client.get("/api/v1/public/sub?t=not-a-real-token-but-long-enough")
    assert resp.status_code == 401


def test_public_progress_rejects_cross_grant_assignment(
    client, monkeypatch
):
    """Sub A can't report progress on sub B's assignment — the
    `WHERE grant_id = :grant` clause in the verification query is
    the load-bearing security guard."""
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "f" * 32)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    from core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    from services.subcontractor_tokens import (
        hash_token,
        mint_subcontractor_token,
    )

    grant_id = uuid4()
    org_id = uuid4()
    proj_id = uuid4()
    token = mint_subcontractor_token(
        grant_id=grant_id,
        organization_id=org_id,
        project_id=proj_id,
        email="sub@example.com",
    )

    # AdminSessionFactory returns: grant active first, then None for
    # the cross-grant assignment lookup.
    call_state = {"n": 0}

    async def fake_execute(stmt, params=None):
        call_state["n"] += 1
        sql = str(stmt)

        class _R:
            rowcount = 0

            def mappings(self):
                return self

            def one_or_none(self_inner):
                if "FROM subcontractor_portal_grants" in sql:
                    return {
                        "id": grant_id,
                        "organization_id": org_id,
                        "project_id": proj_id,
                        "revoked_at": None,
                        "expires_at": datetime.now(UTC) + timedelta(days=10),
                    }
                if "FROM subcontractor_assignments" in sql:
                    # No assignment found for THIS grant → cross-grant
                    # attack rejected.
                    return None
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

    with patch("routers.subcontractor_portal.AdminSessionFactory", factory):
        resp = client.post(
            f"/api/v1/public/sub/assignments/{uuid4()}/progress?t={token}",
            json={"percent_complete": 50, "status": "in_progress"},
        )

    assert resp.status_code == 404
    msg = resp.json()
    assert "assignment_not_found_for_this_grant" in str(msg)


def test_public_progress_validates_percent_bounds(client, monkeypatch):
    """percent_complete must be 0-100 — Pydantic ge=0 le=100."""
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "g" * 32)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    from core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    from services.subcontractor_tokens import mint_subcontractor_token

    token = mint_subcontractor_token(
        grant_id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        email="sub@example.com",
    )

    resp = client.post(
        f"/api/v1/public/sub/assignments/{uuid4()}/progress?t={token}",
        json={"percent_complete": 150, "status": "in_progress"},
    )
    assert resp.status_code == 422
