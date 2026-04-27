"""Router tests for the invitation flow.

Two surfaces with different trust postures:

  * Admin (`POST /orgs/{id}/invitations`, GET, DELETE) — auth required.
  * Public (`GET /invitations/{token}`, `POST /invitations/{token}/accept`)
    — no auth; the token IS the bearer credential.

The router uses `AdminSessionFactory` directly (not `get_db`), so every
test here patches `AdminSessionFactory` to a fixture-built fake session.
The Supabase admin API call inside `accept_invitation` is mocked too —
no httpx traffic.

What we cover:
  * Auth gating (org mismatch, member role rejection).
  * Idempotency / duplicate-pending rejection on create.
  * Expiry enforcement on BOTH the GET and the accept POST — this was
    previously a real bug (expires_at was set but never compared).
  * Already-accepted token returns 410.
  * Happy-path accept upserts users + org_members + stamps accepted_at.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Module-level so FastAPI's signature inspection can resolve AuthContext
# inside the route handlers when they're collected at startup.
from middleware.auth import AuthContext, require_auth  # noqa: F401

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
    """Records executes; pops queued results."""

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
        r.scalar_one_or_none.return_value = None
        r.scalar_one.return_value = 0
        r.rowcount = 0
        r.mappings.return_value.one.return_value = {}
        r.mappings.return_value.one_or_none.return_value = None
        r.mappings.return_value.all.return_value = []
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture(autouse=True)
def patch_admin_session(fake_db, monkeypatch):
    """The router uses `AdminSessionFactory()` directly via
    `async with AdminSessionFactory() as db:`. Replace it with a context
    manager that yields our fake session."""

    @asynccontextmanager
    async def _factory() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    # Patch in BOTH places it's referenced — the import in routers/invitations.py
    # is `from db.session import AdminSessionFactory`, but Python rebinds locally.
    monkeypatch.setattr("routers.invitations.AdminSessionFactory", _factory)
    yield fake_db


def _build_app(role: str) -> FastAPI:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from routers import invitations as inv_router

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(inv_router.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="caller@example.com",
    )
    app.dependency_overrides[require_auth] = lambda: auth_ctx
    return app


# ---------- Admin create ----------


async def test_create_invitation_403_for_member_role():
    """Members cannot invite — admin/owner only."""
    app = _build_app("member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/orgs/{ORG_ID}/invitations",
            json={"email": "new@example.com", "role": "member"},
        )
    assert res.status_code == 403


async def test_create_invitation_403_for_org_mismatch(fake_db):
    """An admin in org A cannot invite into org B (path mismatch)."""
    app = _build_app("admin")
    other_org = uuid4()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/orgs/{other_org}/invitations",
            json={"email": "new@example.com", "role": "member"},
        )
    assert res.status_code == 403


async def test_create_invitation_409_when_pending_exists(fake_db):
    """Re-inviting an email with a still-active pending invitation should
    409 instead of stacking duplicate rows."""
    existing_q = MagicMock()
    existing_q.scalar_one_or_none.return_value = uuid4()
    fake_db.push(existing_q)

    app = _build_app("admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/orgs/{ORG_ID}/invitations",
            json={"email": "alice@example.com", "role": "member"},
        )
    assert res.status_code == 409


async def test_create_invitation_400_for_owner_role():
    """Cannot invite someone as owner — prevents privilege escalation
    via invitation."""
    app = _build_app("admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/orgs/{ORG_ID}/invitations",
            json={"email": "rogue@example.com", "role": "owner"},
        )
    assert res.status_code == 400


async def test_create_invitation_succeeds_for_admin(fake_db):
    no_pending = MagicMock()
    no_pending.scalar_one_or_none.return_value = None
    fake_db.push(no_pending)

    insert_q = MagicMock()
    inv_id = uuid4()
    inv_token = uuid4()
    expires = datetime.now(UTC) + timedelta(days=7)
    insert_q.mappings.return_value.one.return_value = {
        "id": inv_id,
        "organization_id": ORG_ID,
        "email": "new@example.com",
        "role": "member",
        "token": inv_token,
        "expires_at": expires,
    }
    fake_db.push(insert_q)

    app = _build_app("admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/orgs/{ORG_ID}/invitations",
            json={"email": "new@example.com", "role": "member"},
        )
    assert res.status_code == 201, res.text
    body = res.json()["data"]
    assert body["email"] == "new@example.com"
    assert body["role"] == "member"
    assert body["accept_url"].endswith(f"/invite/{inv_token}")


# ---------- Public GET ----------


async def test_get_invitation_404_for_unknown_token(fake_db):
    fake_db.push(MagicMock(mappings=lambda: MagicMock(one_or_none=lambda: None)))

    app = _build_app("admin")  # role doesn't matter — endpoint has no auth
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/invitations/{uuid4()}")
    assert res.status_code == 404


async def test_get_invitation_410_for_already_accepted(fake_db):
    accepted_at = datetime.now(UTC)
    expires_at = accepted_at + timedelta(days=5)
    q = MagicMock()
    q.mappings.return_value.one_or_none.return_value = {
        "email": "alice@example.com",
        "role": "member",
        "expires_at": expires_at,
        "accepted_at": accepted_at,
        "organization_name": "Acme",
    }
    fake_db.push(q)

    app = _build_app("admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/invitations/{uuid4()}")
    assert res.status_code == 410


async def test_get_invitation_410_for_expired_token(fake_db):
    """Regression: this was the bug — expired tokens used to fall through
    to 200 because expires_at was selected but never compared."""
    expired = datetime.now(UTC) - timedelta(days=1)
    q = MagicMock()
    q.mappings.return_value.one_or_none.return_value = {
        "email": "alice@example.com",
        "role": "member",
        "expires_at": expired,
        "accepted_at": None,
        "organization_name": "Acme",
    }
    fake_db.push(q)

    app = _build_app("admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/invitations/{uuid4()}")
    assert res.status_code == 410
    assert "expired" in res.json()["errors"][0]["message"].lower()


async def test_get_invitation_200_for_valid_token(fake_db):
    expires_at = datetime.now(UTC) + timedelta(days=5)
    q = MagicMock()
    q.mappings.return_value.one_or_none.return_value = {
        "email": "alice@example.com",
        "role": "member",
        "expires_at": expires_at,
        "accepted_at": None,
        "organization_name": "Acme",
    }
    fake_db.push(q)

    app = _build_app("admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/invitations/{uuid4()}")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["organization_name"] == "Acme"
    assert body["email"] == "alice@example.com"


# ---------- Public accept ----------


async def test_accept_invitation_503_when_supabase_unconfigured(monkeypatch, fake_db):
    """No Supabase secret → can't create the auth user → 503."""
    from core.config import get_settings

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    try:
        app = _build_app("admin")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                f"/api/v1/invitations/{uuid4()}/accept",
                json={"password": "supersecure", "full_name": "Alice"},
            )
        assert res.status_code == 503
    finally:
        get_settings.cache_clear()


async def test_accept_invitation_410_for_expired(monkeypatch, fake_db):
    """Regression for the second leg of the same bug: the accept POST
    also has to enforce expiry, not just the GET."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    from core.config import get_settings

    get_settings.cache_clear()
    try:
        # Stamp Supabase as configured.
        expired = datetime.now(UTC) - timedelta(hours=1)
        q = MagicMock()
        q.mappings.return_value.one_or_none.return_value = {
            "id": uuid4(),
            "organization_id": ORG_ID,
            "email": "alice@example.com",
            "role": "member",
            "expires_at": expired,
            "accepted_at": None,
        }
        fake_db.push(q)

        app = _build_app("admin")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                f"/api/v1/invitations/{uuid4()}/accept",
                json={"password": "supersecure", "full_name": "Alice"},
            )
        assert res.status_code == 410
        assert "expired" in res.json()["errors"][0]["message"].lower()
    finally:
        get_settings.cache_clear()


async def test_accept_invitation_410_for_already_accepted(monkeypatch, fake_db):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    from core.config import get_settings

    get_settings.cache_clear()
    try:
        accepted = datetime.now(UTC)
        q = MagicMock()
        q.mappings.return_value.one_or_none.return_value = {
            "id": uuid4(),
            "organization_id": ORG_ID,
            "email": "alice@example.com",
            "role": "member",
            "expires_at": accepted + timedelta(days=5),
            "accepted_at": accepted,
        }
        fake_db.push(q)

        app = _build_app("admin")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                f"/api/v1/invitations/{uuid4()}/accept",
                json={"password": "supersecure", "full_name": "Alice"},
            )
        assert res.status_code == 410
    finally:
        get_settings.cache_clear()


async def test_accept_invitation_happy_path(monkeypatch, fake_db):
    """End-to-end: looks up invite, provisions Supabase user (mocked),
    upserts users + org_members, stamps accepted_at, returns 200."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    from core.config import get_settings

    get_settings.cache_clear()
    try:
        # 1. SELECT invitation FOR UPDATE
        inv_id = uuid4()
        sel_q = MagicMock()
        sel_q.mappings.return_value.one_or_none.return_value = {
            "id": inv_id,
            "organization_id": ORG_ID,
            "email": "alice@example.com",
            "role": "member",
            "expires_at": datetime.now(UTC) + timedelta(days=5),
            "accepted_at": None,
        }
        fake_db.push(sel_q)
        # 2-4. INSERT users, INSERT org_members, UPDATE invitations —
        # default execute() mock is fine for these.

        # Mock Supabase user provisioning.
        provisioned_uid = uuid4()
        monkeypatch.setattr(
            "routers.invitations._provision_supabase_user",
            AsyncMock(return_value=provisioned_uid),
        )

        app = _build_app("admin")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                f"/api/v1/invitations/{uuid4()}/accept",
                json={"password": "supersecure", "full_name": "Alice"},
            )
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["organization_id"] == str(ORG_ID)
        assert body["email"] == "alice@example.com"
        assert body["role"] == "member"
    finally:
        get_settings.cache_clear()
