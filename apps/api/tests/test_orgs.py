"""Tests for self-serve org creation (`POST /api/v1/orgs`).

Covers:
  * authenticated user creates an org and becomes owner
  * users row is auto-provisioned if missing
  * duplicate explicit slug is rejected
  * derived slug picks up a UUID suffix when the auto-slug collides
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

USER_ID = UUID("44444444-4444-4444-4444-444444444444")


class _OrgsFakeDB:
    """In-memory stand-in for AdminSessionFactory. Tracks orgs (with a
    slug uniqueness constraint) plus users/org_members inserts."""

    def __init__(self, taken_slugs: set[str] | None = None) -> None:
        self.orgs: list[dict[str, Any]] = []
        self.users: dict[UUID, dict[str, Any]] = {}
        self.org_members: list[dict[str, Any]] = []
        self.taken_slugs: set[str] = set(taken_slugs or set())

    async def execute(self, stmt: object, params: dict[str, Any] | None = None) -> object:
        sql = str(stmt).strip()
        params = params or {}
        result = MagicMock()

        if sql.startswith("SELECT 1 FROM organizations WHERE slug"):
            result.scalar_one_or_none.return_value = 1 if params["slug"] in self.taken_slugs else None
            return result

        if sql.startswith("INSERT INTO users"):
            uid = UUID(params["id"])
            self.users[uid] = {"id": uid, "email": params["email"]}
            return result

        if sql.startswith("INSERT INTO organizations"):
            row = {
                "id": UUID(params["id"]),
                "name": params["name"],
                "slug": params["slug"],
                "plan": "starter",
                "country_code": params["country"],
                "created_at": datetime.now(UTC),
            }
            self.orgs.append(row)
            self.taken_slugs.add(params["slug"])
            result.mappings.return_value.one.return_value = row
            return result

        if sql.startswith("INSERT INTO org_members"):
            self.org_members.append(
                {
                    "user_id": UUID(params["uid"]),
                    "organization_id": UUID(params["org"]),
                    "role": "owner",
                }
            )
            return result

        result.scalar_one_or_none.return_value = None
        return result

    async def commit(self) -> None:
        return None


@pytest.fixture
def fake_orgs_db() -> _OrgsFakeDB:
    return _OrgsFakeDB()


@pytest.fixture
def orgs_app(monkeypatch, fake_orgs_db) -> FastAPI:
    from middleware.auth import UserContext, require_user
    from routers import orgs as orgs_module

    def _user() -> UserContext:
        return UserContext(user_id=USER_ID, email="founder@example.com")

    class _Factory:
        async def __aenter__(self) -> _OrgsFakeDB:
            return fake_orgs_db

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(orgs_module, "AdminSessionFactory", lambda: _Factory())

    from core.envelope import http_exception_handler, unhandled_exception_handler

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(orgs_module.router)
    app.dependency_overrides[require_user] = _user
    app.state.fake_db = fake_orgs_db
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def orgs_client(orgs_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=orgs_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Tests ----------


async def test_create_org_makes_caller_owner(orgs_app, orgs_client):
    res = await orgs_client.post("/api/v1/orgs", json={"name": "Acme Architects"})

    assert res.status_code == 201
    data = res.json()["data"]
    assert data["name"] == "Acme Architects"
    assert data["slug"] == "acme-architects"
    assert data["role"] == "owner"

    db = orgs_app.state.fake_db
    assert len(db.orgs) == 1
    # users row was auto-provisioned
    assert USER_ID in db.users
    # owner membership granted on the new org
    assert len(db.org_members) == 1
    assert db.org_members[0]["role"] == "owner"
    assert db.org_members[0]["user_id"] == USER_ID


async def test_create_org_rejects_explicit_duplicate_slug(orgs_app, orgs_client):
    orgs_app.state.fake_db.taken_slugs.add("acme")

    res = await orgs_client.post(
        "/api/v1/orgs",
        json={"name": "Different Acme", "slug": "acme"},
    )
    assert res.status_code == 409
    assert "taken" in res.json()["errors"][0]["message"].lower()


async def test_create_org_appends_uuid_when_derived_slug_collides(orgs_app, orgs_client):
    """If the user did NOT pass an explicit slug and the derived one is
    taken, append the org_id prefix instead of erroring — better UX
    than forcing the user to think of a unique slug."""
    orgs_app.state.fake_db.taken_slugs.add("foo-bar")

    res = await orgs_client.post("/api/v1/orgs", json={"name": "Foo Bar"})
    assert res.status_code == 201
    slug = res.json()["data"]["slug"]
    assert slug.startswith("foo-bar-")
    assert len(slug) > len("foo-bar-")  # has the suffix


async def test_create_org_validates_slug_shape(orgs_client):
    """The schema validator rejects slugs with capital letters / leading
    or trailing hyphens / non-ASCII."""
    res = await orgs_client.post(
        "/api/v1/orgs",
        json={"name": "Bad Slug Org", "slug": "BAD_SLUG"},
    )
    assert res.status_code == 422


async def test_create_org_rejects_short_name(orgs_client):
    res = await orgs_client.post("/api/v1/orgs", json={"name": "x"})
    assert res.status_code == 422
