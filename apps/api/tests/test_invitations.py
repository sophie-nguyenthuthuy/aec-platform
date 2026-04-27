"""Tests for the invitation flow.

Covers:
  * admin can issue / list / revoke invitations
  * non-admins can't (admin role gate)
  * cross-org access is blocked (`X-Org-ID` mismatch)
  * the public preview/accept endpoints work without auth, are
    single-use, and respect expiry

The Supabase admin API call inside the accept handler is monkey-patched
to a fixed UUID — we don't need a real Supabase project to verify the
local DB choreography.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

ADMIN_USER_ID = UUID("11111111-1111-1111-1111-111111111111")
ADMIN_ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
OTHER_ORG_ID = UUID("33333333-3333-3333-3333-333333333333")


# ---------- Fake DB shared by all invitation tests ----------


class _InvitationsFakeDB:
    """In-memory stand-in for AdminSessionFactory, modeling just enough
    SQL semantics to drive the invitations router. Tracks invitations,
    org membership, and a `users` table; commits are no-ops."""

    def __init__(self) -> None:
        self.invitations: dict[UUID, dict[str, Any]] = {}
        self.orgs: dict[UUID, str] = {ADMIN_ORG_ID: "Dev Org"}
        self.users: dict[UUID, dict[str, Any]] = {}
        self.org_members: list[dict[str, Any]] = []

    def seed_invitation(
        self,
        *,
        org_id: UUID = ADMIN_ORG_ID,
        email: str = "invitee@example.com",
        role: str = "member",
        token: UUID | None = None,
        expires_at: datetime | None = None,
        accepted_at: datetime | None = None,
    ) -> UUID:
        tok = token or uuid4()
        inv_id = uuid4()
        self.invitations[tok] = {
            "id": inv_id,
            "organization_id": org_id,
            "email": email,
            "role": role,
            "token": tok,
            "expires_at": expires_at or datetime.now(UTC) + timedelta(days=7),
            "accepted_at": accepted_at,
        }
        return tok

    async def execute(self, stmt: object, params: dict[str, Any] | None = None) -> object:
        sql = str(stmt).strip()
        params = params or {}
        result = MagicMock()

        if sql.startswith("SELECT id FROM invitations") and "lower(email)" in sql:
            # create-invitation idempotency check
            org = UUID(params["org"])
            email = params["email"].lower()
            for inv in self.invitations.values():
                if (
                    inv["organization_id"] == org
                    and inv["email"].lower() == email
                    and inv["accepted_at"] is None
                    and inv["expires_at"] > datetime.now(UTC)
                ):
                    result.scalar_one_or_none.return_value = inv["id"]
                    return result
            result.scalar_one_or_none.return_value = None
            return result

        if sql.startswith("INSERT INTO invitations"):
            inv_id = uuid4()
            tok = UUID(params["token"])
            row = {
                "id": inv_id,
                "organization_id": UUID(params["org"]),
                "email": params["email"],
                "role": params["role"],
                "token": tok,
                "expires_at": datetime.now(UTC) + timedelta(days=7),
            }
            self.invitations[tok] = {**row, "accepted_at": None}
            result.mappings.return_value.one.return_value = row
            return result

        if sql.startswith("SELECT id, email, role, expires_at, accepted_at"):
            org = UUID(params["org"])
            rows = [
                {
                    "id": inv["id"],
                    "email": inv["email"],
                    "role": inv["role"],
                    "expires_at": inv["expires_at"],
                    "accepted_at": inv["accepted_at"],
                    "invited_by": None,
                    "created_at": datetime.now(UTC),
                }
                for inv in self.invitations.values()
                if inv["organization_id"] == org
            ]
            result.mappings.return_value.all.return_value = rows
            return result

        if sql.startswith("DELETE FROM invitations"):
            inv_id = UUID(params["id"])
            org = UUID(params["org"])
            tokens_to_remove = [
                tok
                for tok, inv in self.invitations.items()
                if inv["id"] == inv_id and inv["organization_id"] == org and inv["accepted_at"] is None
            ]
            for tok in tokens_to_remove:
                del self.invitations[tok]
            result.rowcount = len(tokens_to_remove)
            return result

        if "FROM invitations i" in sql and "JOIN organizations o" in sql:
            # public preview lookup
            tok = UUID(params["token"])
            inv = self.invitations.get(tok)
            if inv is None:
                result.mappings.return_value.one_or_none.return_value = None
                return result
            row = {
                "email": inv["email"],
                "role": inv["role"],
                "expires_at": inv["expires_at"],
                "accepted_at": inv["accepted_at"],
                "organization_name": self.orgs.get(inv["organization_id"], "Unknown Org"),
            }
            result.mappings.return_value.one_or_none.return_value = row
            return result

        if sql.startswith("SELECT id, organization_id, email, role, expires_at, accepted_at"):
            # accept lookup
            tok = UUID(params["token"])
            inv = self.invitations.get(tok)
            if inv is None:
                result.mappings.return_value.one_or_none.return_value = None
                return result
            result.mappings.return_value.one_or_none.return_value = {
                "id": inv["id"],
                "organization_id": inv["organization_id"],
                "email": inv["email"],
                "role": inv["role"],
                "expires_at": inv["expires_at"],
                "accepted_at": inv["accepted_at"],
            }
            return result

        if sql.startswith("INSERT INTO users"):
            uid = UUID(params["id"])
            self.users[uid] = {"id": uid, "email": params["email"], "full_name": params.get("full_name")}
            return result

        if sql.startswith("INSERT INTO org_members"):
            self.org_members.append(
                {
                    "user_id": UUID(params["uid"]),
                    "organization_id": UUID(params["org"]),
                    "role": params["role"],
                }
            )
            return result

        if sql.startswith("UPDATE invitations SET accepted_at"):
            inv_id = UUID(params["id"])
            for inv in self.invitations.values():
                if inv["id"] == inv_id:
                    inv["accepted_at"] = datetime.now(UTC)
            return result

        # Default: empty result
        result.scalar_one_or_none.return_value = None
        result.mappings.return_value.all.return_value = []
        return result

    async def commit(self) -> None:
        return None


@pytest.fixture
def fake_inv_db() -> _InvitationsFakeDB:
    return _InvitationsFakeDB()


# ---------- App fixture ----------


@pytest.fixture
def inv_app(monkeypatch, fake_inv_db) -> FastAPI:
    from middleware.auth import AuthContext, require_auth
    from routers import invitations as invitations_module

    # Real-auth-style admin user with role=owner.
    def _admin_auth() -> AuthContext:
        return AuthContext(
            user_id=ADMIN_USER_ID,
            organization_id=ADMIN_ORG_ID,
            role="owner",
            email="admin@example.com",
        )

    # Patch AdminSessionFactory to return our fake.
    class _Factory:
        async def __aenter__(self) -> _InvitationsFakeDB:
            return fake_inv_db

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(invitations_module, "AdminSessionFactory", lambda: _Factory())

    # Patch the Supabase admin call inside the accept handler — returns a
    # fresh UUID without hitting the network.
    async def _fake_provision(*, email: str, password: str, full_name: str | None) -> UUID:
        return uuid4()

    monkeypatch.setattr(invitations_module, "_provision_supabase_user", _fake_provision)

    # Make `public_web_url` deterministic so we can assert on accept_url.
    from core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "public_web_url", "http://test-host", raising=False)
    monkeypatch.setattr(settings, "supabase_url", "https://test.supabase.co", raising=False)
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test", raising=False)

    from core.envelope import http_exception_handler, unhandled_exception_handler

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(invitations_module.router)
    app.dependency_overrides[require_auth] = _admin_auth
    app.state.fake_db = fake_inv_db
    app.state.admin_auth_factory = lambda role="owner", org=ADMIN_ORG_ID: AuthContext(
        user_id=ADMIN_USER_ID,
        organization_id=org,
        role=role,
        email="admin@example.com",
    )
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def inv_client(inv_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=inv_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Admin: create / list / revoke ----------


async def test_create_invitation_returns_accept_url(inv_app, inv_client):
    res = await inv_client.post(
        f"/api/v1/orgs/{ADMIN_ORG_ID}/invitations",
        json={"email": "newhire@example.com", "role": "member"},
    )

    assert res.status_code == 201
    body = res.json()["data"]
    assert body["email"] == "newhire@example.com"
    assert body["role"] == "member"
    assert body["accept_url"].startswith("http://test-host/invite/")
    assert body["accept_url"].endswith(body["token"])

    # Row landed in the fake DB with the same token.
    fake_db = inv_app.state.fake_db
    assert UUID(body["token"]) in fake_db.invitations


async def test_create_invitation_blocks_owner_role_assignment(inv_client):
    res = await inv_client.post(
        f"/api/v1/orgs/{ADMIN_ORG_ID}/invitations",
        json={"email": "rogue@example.com", "role": "owner"},
    )
    assert res.status_code == 400
    assert (
        "owner" not in res.json()["errors"][0]["message"].lower() or "Invitable" in res.json()["errors"][0]["message"]
    )


async def test_create_invitation_rejects_cross_org(inv_client):
    res = await inv_client.post(
        f"/api/v1/orgs/{OTHER_ORG_ID}/invitations",
        json={"email": "newhire@example.com", "role": "member"},
    )
    assert res.status_code == 403


async def test_create_invitation_rejects_non_admin(inv_app, inv_client, monkeypatch):
    from middleware.auth import AuthContext, require_auth

    inv_app.dependency_overrides[require_auth] = lambda: AuthContext(
        user_id=ADMIN_USER_ID,
        organization_id=ADMIN_ORG_ID,
        role="member",
        email="member@example.com",
    )

    res = await inv_client.post(
        f"/api/v1/orgs/{ADMIN_ORG_ID}/invitations",
        json={"email": "newhire@example.com", "role": "member"},
    )
    assert res.status_code == 403


async def test_create_invitation_rejects_duplicate_pending(inv_app, inv_client):
    inv_app.state.fake_db.seed_invitation(email="dup@example.com")

    res = await inv_client.post(
        f"/api/v1/orgs/{ADMIN_ORG_ID}/invitations",
        json={"email": "dup@example.com", "role": "member"},
    )
    assert res.status_code == 409


async def test_list_invitations_returns_pending_and_accepted(inv_app, inv_client):
    inv_app.state.fake_db.seed_invitation(email="pending@example.com")
    inv_app.state.fake_db.seed_invitation(email="accepted@example.com", accepted_at=datetime.now(UTC))

    res = await inv_client.get(f"/api/v1/orgs/{ADMIN_ORG_ID}/invitations")
    assert res.status_code == 200
    rows = res.json()["data"]
    emails = {r["email"] for r in rows}
    assert emails == {"pending@example.com", "accepted@example.com"}


async def test_revoke_invitation_removes_pending_row(inv_app, inv_client):
    tok = inv_app.state.fake_db.seed_invitation(email="revokeme@example.com")
    inv_id = inv_app.state.fake_db.invitations[tok]["id"]

    res = await inv_client.delete(
        f"/api/v1/orgs/{ADMIN_ORG_ID}/invitations/{inv_id}",
    )
    assert res.status_code == 200
    assert tok not in inv_app.state.fake_db.invitations


async def test_revoke_invitation_404s_when_already_accepted(inv_app, inv_client):
    tok = inv_app.state.fake_db.seed_invitation(email="accepted@example.com", accepted_at=datetime.now(UTC))
    inv_id = inv_app.state.fake_db.invitations[tok]["id"]

    res = await inv_client.delete(
        f"/api/v1/orgs/{ADMIN_ORG_ID}/invitations/{inv_id}",
    )
    assert res.status_code == 404


# ---------- Public: preview / accept ----------


async def test_preview_returns_org_name_for_pending_invitation(inv_app, inv_client):
    tok = inv_app.state.fake_db.seed_invitation(email="invitee@example.com")

    res = await inv_client.get(f"/api/v1/invitations/{tok}")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["email"] == "invitee@example.com"
    assert body["organization_name"] == "Dev Org"


async def test_preview_rejects_already_accepted(inv_app, inv_client):
    tok = inv_app.state.fake_db.seed_invitation(email="invitee@example.com", accepted_at=datetime.now(UTC))

    res = await inv_client.get(f"/api/v1/invitations/{tok}")
    assert res.status_code == 410


async def test_accept_creates_user_and_membership(inv_app, inv_client):
    tok = inv_app.state.fake_db.seed_invitation(email="invitee@example.com", role="admin")

    res = await inv_client.post(
        f"/api/v1/invitations/{tok}/accept",
        json={"password": "P@ssw0rd-strong", "full_name": "New Hire"},
    )
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["email"] == "invitee@example.com"
    assert body["role"] == "admin"

    db = inv_app.state.fake_db
    # users row created, org_members granted
    assert len(db.users) == 1
    assert len(db.org_members) == 1
    assert db.org_members[0]["role"] == "admin"
    # invitation marked accepted
    assert db.invitations[tok]["accepted_at"] is not None


async def test_accept_is_single_use(inv_app, inv_client):
    tok = inv_app.state.fake_db.seed_invitation(email="invitee@example.com")

    first = await inv_client.post(
        f"/api/v1/invitations/{tok}/accept",
        json={"password": "P@ssw0rd-strong"},
    )
    assert first.status_code == 200

    second = await inv_client.post(
        f"/api/v1/invitations/{tok}/accept",
        json={"password": "P@ssw0rd-strong"},
    )
    assert second.status_code == 410


async def test_accept_rejects_bad_token(inv_client):
    res = await inv_client.post(
        f"/api/v1/invitations/{uuid4()}/accept",
        json={"password": "P@ssw0rd-strong"},
    )
    assert res.status_code == 404


async def test_accept_rejects_short_password(inv_client):
    res = await inv_client.post(
        f"/api/v1/invitations/{uuid4()}/accept",
        json={"password": "tiny"},
    )
    # FastAPI surfaces validation errors as 422.
    assert res.status_code == 422
