"""Tests for the RBAC primitives in `middleware/rbac.py`.

Two layers under test:
  1. The `Role` enum + `at_least()` hierarchy.
  2. The `require_role` / `require_min_role` dependency factories — we
     mount them on a stub route and verify the right callers pass /
     get 403'd.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

# Module-level import so FastAPI's signature inspection can resolve
# `AuthContext` when our nested route handlers are introspected at
# app-startup time. (Importing inside `_build_app` works for runtime
# but Pydantic's annotation resolver can't see it.)
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role, require_role

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


# ---------- Enum ----------


def test_role_hierarchy_owner_outranks_admin():
    from middleware.rbac import Role

    assert Role.OWNER.at_least(Role.ADMIN) is True
    assert Role.ADMIN.at_least(Role.OWNER) is False


def test_role_hierarchy_member_below_admin_above_viewer():
    from middleware.rbac import Role

    assert Role.MEMBER.at_least(Role.VIEWER) is True
    assert Role.MEMBER.at_least(Role.ADMIN) is False


def test_role_at_least_self_is_true():
    """Reflexive: every role satisfies `at_least(self)`."""
    from middleware.rbac import Role

    for r in (Role.VIEWER, Role.MEMBER, Role.ADMIN, Role.OWNER):
        assert r.at_least(r), f"{r} should satisfy at_least(self)"


def test_role_parse_returns_none_for_unknown():
    """Unrecognised role strings → None, not exception. Routers get a
    clean 403 instead of crashing on stale DB data."""
    from middleware.rbac import Role

    assert Role.parse("bogus") is None
    assert Role.parse("") is None
    assert Role.parse("owner") is Role.OWNER


# ---------- Decorator behavior ----------


def _build_app(role_for_caller: str) -> FastAPI:
    """Build a minimal app with `require_auth` overridden to inject a
    canned AuthContext. Lets us exercise the dependency without a real
    JWT or DB."""
    app = FastAPI()

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role_for_caller,
        email="x@example.com",
    )
    app.dependency_overrides[require_auth] = lambda: auth_ctx

    @app.get("/admin-only")
    async def admin_only(
        _ctx: Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.OWNER))],
    ) -> dict:
        return {"ok": True}

    @app.get("/member-or-up")
    async def member_or_up(
        _ctx: Annotated[AuthContext, Depends(require_min_role(Role.MEMBER))],
    ) -> dict:
        return {"ok": True}

    @app.get("/owner-only")
    async def owner_only(
        _ctx: Annotated[AuthContext, Depends(require_min_role(Role.OWNER))],
    ) -> dict:
        return {"ok": True}

    return app


async def _client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.parametrize(
    "role,expected",
    [
        ("admin", 200),
        ("owner", 200),
        ("member", 403),
        ("viewer", 403),
    ],
)
async def test_require_role_explicit_list(role, expected):
    app = _build_app(role)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/admin-only")
    assert res.status_code == expected, res.text


@pytest.mark.parametrize(
    "role,expected",
    [
        ("owner", 200),
        ("admin", 200),
        ("member", 200),
        ("viewer", 403),
    ],
)
async def test_require_min_role_member(role, expected):
    app = _build_app(role)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/member-or-up")
    assert res.status_code == expected, res.text


@pytest.mark.parametrize(
    "role,expected",
    [
        ("owner", 200),
        ("admin", 403),
        ("member", 403),
        ("viewer", 403),
    ],
)
async def test_require_min_role_owner(role, expected):
    """`require_min_role(OWNER)` is the strict-hierarchy check — only
    owner passes, even admins are blocked."""
    app = _build_app(role)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/owner-only")
    assert res.status_code == expected, res.text


async def test_require_min_role_rejects_unknown_role_string():
    """Stale DB data with a role like 'guest' (not in the enum) must
    not bypass the check — should 403."""
    app = _build_app("guest")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/member-or-up")
    assert res.status_code == 403


async def test_require_role_accepts_string_aliases():
    """For back-compat with existing call sites that pass raw strings."""
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="x@example.com",
    )

    @app.get("/legacy")
    async def legacy(
        _ctx: Annotated[AuthContext, Depends(require_role("admin", "owner"))],
    ) -> dict:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/legacy")
    assert res.status_code == 200
