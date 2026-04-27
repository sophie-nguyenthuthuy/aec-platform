"""Router tests for /api/v1/org/members.

Coverage:
  * GET /members — visible to every role
  * POST /members — admin/owner only; creates user row + membership;
    idempotent for already-member emails
  * PATCH /members/{user_id} — admin/owner only; cannot demote last owner
  * DELETE /members/{user_id} — admin/owner only; cannot remove last owner
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

# Module-level so FastAPI's signature inspector resolves AuthContext.
from middleware.auth import AuthContext, require_auth  # noqa: F401

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
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
        r.mappings.return_value.all.return_value = []
        r.mappings.return_value.first.return_value = None
        r.mappings.return_value.one.return_value = {}
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


def _build_app(role: str, fake_db: FakeAsyncSession) -> FastAPI:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from routers import org as org_router

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="caller@example.com",
    )

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(org_router.router)

    async def _db_override() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[get_db] = _db_override
    return app


async def _client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _member_row(**overrides: Any) -> dict:
    base = {
        "membership_id": uuid4(),
        "user_id": uuid4(),
        "email": "alice@example.com",
        "full_name": "Alice",
        "avatar_url": None,
        "role": "member",
        "joined_at": datetime(2026, 4, 26, tzinfo=UTC),
    }
    base.update(overrides)
    return base


# ---------- List ----------


async def test_list_members_visible_to_viewer(fake_db):
    """Every role can see the team — even viewers."""
    rows = [_member_row(email="a@example.com"), _member_row(email="b@example.com")]
    q = MagicMock()
    q.mappings.return_value.all.return_value = rows
    fake_db.push(q)

    app = _build_app("viewer", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/org/members")

    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert {m["email"] for m in body} == {"a@example.com", "b@example.com"}


# ---------- Invite ----------


async def test_invite_member_403_for_member_role(fake_db):
    """Members cannot invite — admin/owner only."""
    app = _build_app("member", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/org/members",
            json={"email": "new@example.com", "role": "member"},
        )
    assert res.status_code == 403


async def test_invite_member_creates_user_and_membership(fake_db):
    """First-time email: provision users row + org_members row."""
    new_user_id = uuid4()
    new_membership_id = uuid4()

    # 1. SELECT users.id by email — none yet (returning UUID via scalar_one_or_none)
    user_q = MagicMock()
    user_q.scalar_one_or_none.return_value = None
    fake_db.push(user_q)
    # 2. INSERT users — no return needed; default execute() result is fine
    fake_db.push(MagicMock())
    # 3. SELECT existing org_members — none
    existing_q = MagicMock()
    existing_q.mappings.return_value.first.return_value = None
    fake_db.push(existing_q)
    # 4. INSERT org_members — no return needed
    fake_db.push(MagicMock())
    # 5. SELECT joined member row for response
    detail_q = MagicMock()
    detail_q.mappings.return_value.one.return_value = _member_row(
        membership_id=new_membership_id,
        user_id=new_user_id,
        email="new@example.com",
        role="member",
    )
    fake_db.push(detail_q)

    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/org/members",
            json={"email": "new@example.com", "role": "member"},
        )

    assert res.status_code == 201, res.text
    body = res.json()["data"]
    assert body["email"] == "new@example.com"
    assert body["role"] == "member"


async def test_invite_member_is_idempotent_for_existing_member(fake_db):
    """Re-inviting an existing member returns the existing row, no
    duplicate INSERT."""
    existing_user_id = uuid4()
    existing_membership_id = uuid4()

    user_q = MagicMock()
    user_q.scalar_one_or_none.return_value = existing_user_id
    fake_db.push(user_q)
    existing_q = MagicMock()
    existing_q.mappings.return_value.first.return_value = {
        "id": existing_membership_id,
        "role": "member",
    }
    fake_db.push(existing_q)
    detail_q = MagicMock()
    detail_q.mappings.return_value.one.return_value = _member_row(
        membership_id=existing_membership_id,
        user_id=existing_user_id,
    )
    fake_db.push(detail_q)

    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/org/members",
            json={"email": "alice@example.com", "role": "member"},
        )
    assert res.status_code == 201, res.text
    # Verify we did NOT issue a fresh INSERT INTO users (only 3 executes,
    # not 5). The router fires:
    #   1. SELECT user by email
    #   2. SELECT existing membership
    #   3. SELECT detail row for response
    assert len(fake_db.calls) == 3


# ---------- Update role ----------


async def test_update_role_403_for_viewer(fake_db):
    app = _build_app("viewer", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.patch(
            f"/api/v1/org/members/{uuid4()}",
            json={"role": "admin"},
        )
    assert res.status_code == 403


async def test_update_role_409_when_demoting_last_owner(fake_db):
    """Hard-rule: never strand an org with zero owners."""
    target_id = uuid4()
    # 1. SELECT target.role — owner
    target_q = MagicMock()
    target_q.scalar_one_or_none.return_value = "owner"
    fake_db.push(target_q)
    # 2. SELECT count(*) WHERE role='owner' — 1 (the target is the only one)
    count_q = MagicMock()
    count_q.scalar_one.return_value = 1
    fake_db.push(count_q)

    app = _build_app("owner", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.patch(
            f"/api/v1/org/members/{target_id}",
            json={"role": "admin"},  # demoting the only owner
        )
    assert res.status_code == 409
    assert "last owner" in res.json()["errors"][0]["message"].lower()


async def test_update_role_succeeds_when_other_owners_exist(fake_db):
    """Demoting an owner is fine when there's another owner left."""
    target_id = uuid4()
    target_q = MagicMock()
    target_q.scalar_one_or_none.return_value = "owner"
    fake_db.push(target_q)
    count_q = MagicMock()
    count_q.scalar_one.return_value = 2
    fake_db.push(count_q)
    update_q = MagicMock()
    update_q.scalar_one_or_none.return_value = uuid4()
    fake_db.push(update_q)
    detail_q = MagicMock()
    detail_q.mappings.return_value.one.return_value = _member_row(user_id=target_id, role="admin")
    fake_db.push(detail_q)

    app = _build_app("owner", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.patch(
            f"/api/v1/org/members/{target_id}",
            json={"role": "admin"},
        )
    assert res.status_code == 200, res.text
    assert res.json()["data"]["role"] == "admin"


async def test_update_role_404_when_member_not_in_org(fake_db):
    """Target user isn't a member of the caller's org."""
    target_id = uuid4()
    # target.role lookup → None (not a member)
    target_q = MagicMock()
    target_q.scalar_one_or_none.return_value = None
    fake_db.push(target_q)
    # UPDATE returns 0 rows → scalar_one_or_none None
    update_q = MagicMock()
    update_q.scalar_one_or_none.return_value = None
    fake_db.push(update_q)

    app = _build_app("owner", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.patch(
            f"/api/v1/org/members/{target_id}",
            json={"role": "admin"},
        )
    assert res.status_code == 404


# ---------- Delete ----------


async def test_remove_member_403_for_member(fake_db):
    app = _build_app("member", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.delete(f"/api/v1/org/members/{uuid4()}")
    assert res.status_code == 403


async def test_remove_member_409_when_last_owner(fake_db):
    target_id = uuid4()
    target_q = MagicMock()
    target_q.scalar_one_or_none.return_value = "owner"
    fake_db.push(target_q)
    count_q = MagicMock()
    count_q.scalar_one.return_value = 1
    fake_db.push(count_q)

    app = _build_app("owner", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.delete(f"/api/v1/org/members/{target_id}")
    assert res.status_code == 409


async def test_remove_member_succeeds_for_non_owner(fake_db):
    target_id = uuid4()
    target_q = MagicMock()
    target_q.scalar_one_or_none.return_value = "member"
    fake_db.push(target_q)
    # No count query for non-owner — guard short-circuits.
    fake_db.push(MagicMock())  # DELETE result, ignored

    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.delete(f"/api/v1/org/members/{target_id}")
    assert res.status_code == 204
