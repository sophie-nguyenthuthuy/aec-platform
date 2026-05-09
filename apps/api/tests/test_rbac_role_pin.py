"""Pin `middleware.rbac` — the Role enum + hierarchy + role-gate
dependency factories that EVERY protected route's auth chain
depends on.

Three distinct surfaces in this module, all with high cost-of-
regression:

  * **Role enum.** Four canonical values: `owner`, `admin`,
    `member`, `viewer`. The wire literal lives in
    `org_members.role` (a Postgres `text` column with a CHECK
    constraint). A rename without coordinated DB migration =
    the role check 403s every legitimate user OR (worse) silently
    matches the wrong tier.

  * **Hierarchy.** `viewer < member < admin < owner`. The
    `_RANK` mapping AND `Role.at_least` together encode this.
    A drift in either silently flips the rank order:
      - Lifting `member` above `admin` (e.g. accidentally
        swapping the dict values) would let members hit
        admin-only routes.
      - Dropping a key from `_RANK` would `KeyError` on every
        `at_least()` call — loud, but ugly.

  * **`require_role` / `require_min_role` factories.** Every
    protected route in the codebase ends with one of these.
    A regression that returned a non-callable (or skipped the
    role check) would either crash the FastAPI dep-resolution
    at boot OR (worse) silently let unauthenticated callers
    through.

  * **`Role.parse` tolerant lookup.** Returns `None` on
    unrecognised strings — lets the role-check fall through to
    a clean 403 instead of crashing on stale DB data (a row
    written before a role rename, an experiment value, etc.).
    A regression to raising would 500 every request from a
    user whose row has any non-canonical role string.

This file is read-only — exercises pure helpers + factories.
Survives reverts.

Pinned contracts:

  * Role values: `owner|admin|member|viewer` (exact string set).
  * `_RANK`: `{viewer: 1, member: 2, admin: 3, owner: 4}` exact mapping.
  * `Role.parse(unknown)` returns `None` (not raises).
  * `Role.at_least` strict order on every pair.
  * `require_role(*allowed)` returns async callable.
  * `require_role` accepts BOTH Role enums AND raw strings (back-compat).
  * `require_min_role(floor)` admits roles at or above floor; 403s otherwise.
  * 403 detail includes the documented "Insufficient role" message.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

# ---------- Module + Role enum presence ----------


def test_rbac_module_imports():
    """All public + private surfaces importable."""
    from middleware.rbac import (  # noqa: F401
        _RANK,
        Role,
        require_min_role,
        require_role,
    )


def test_role_enum_value_set_pinned():
    """SECURITY-CRITICAL pin. The four wire values MUST stay
    exactly `owner|admin|member|viewer`. The DB CHECK constraint
    on `org_members.role` AND every role-gate decorator hardcodes
    these strings. A rename here without a coordinated DB
    migration breaks every protected route.
    """
    from middleware.rbac import Role

    expected = {"owner", "admin", "member", "viewer"}
    actual = {r.value for r in Role}
    assert actual == expected, (
        f"Role enum drifted: have {actual}, want {expected}. The "
        "DB CHECK constraint on org_members.role hardcodes these "
        "values; a rename here breaks every protected route AND "
        "rejects every existing org_members row."
    )


def test_role_enum_is_strenum():
    """`Role` is a `StrEnum`. The == comparison against raw strings
    (e.g. `auth.role == "admin"`) is what every route's role check
    relies on. A regression to plain `Enum` would silently break
    every comparison without raising."""
    from enum import StrEnum

    from middleware.rbac import Role

    assert issubclass(Role, StrEnum), (
        "Role is not a StrEnum subclass; want StrEnum so `auth.role "
        "== 'admin'` comparisons work without explicit `.value` access."
    )
    # Belt-and-braces: the comparison itself works.
    assert Role.ADMIN == "admin"
    assert Role.OWNER == "owner"


# ---------- Hierarchy ----------


def test_rank_mapping_pinned():
    """`_RANK` is the source of truth for the role hierarchy. A
    drift here silently changes who passes `require_min_role(...)`
    checks.

    Specific failure modes:
      * Swapping `admin` and `member` ranks would let members hit
        admin-only routes.
      * Setting `viewer` above `member` would let read-only
        accounts modify data.
      * Removing a Role key would KeyError on every at_least()
        call (loud) but the loud failure path is itself a
        regression — pin the full mapping.
    """
    from middleware.rbac import _RANK, Role

    expected = {
        Role.VIEWER: 1,
        Role.MEMBER: 2,
        Role.ADMIN: 3,
        Role.OWNER: 4,
    }
    assert expected == _RANK, (
        f"_RANK drifted: have {_RANK}, want {expected}. The role "
        "hierarchy is the single source of truth for who passes "
        "require_min_role checks; a swap silently elevates the "
        "wrong roles."
    )


def test_at_least_strict_ordering():
    """`at_least` MUST encode the documented hierarchy. We
    exhaustively assert every (a, b) pair so a partial-rewrite
    drift can't sneak in.
    """
    from middleware.rbac import Role

    # owner is at-least everything (including itself).
    for r in Role:
        assert Role.OWNER.at_least(r), (
            f"Role.OWNER.at_least({r!r}) is False; owner should exceed every role including peers."
        )

    # viewer is at-least only viewer.
    assert Role.VIEWER.at_least(Role.VIEWER)
    assert not Role.VIEWER.at_least(Role.MEMBER)
    assert not Role.VIEWER.at_least(Role.ADMIN)
    assert not Role.VIEWER.at_least(Role.OWNER)

    # admin > member > viewer; admin < owner.
    assert Role.ADMIN.at_least(Role.MEMBER)
    assert Role.ADMIN.at_least(Role.VIEWER)
    assert not Role.ADMIN.at_least(Role.OWNER)

    # member > viewer; member < admin/owner.
    assert Role.MEMBER.at_least(Role.VIEWER)
    assert not Role.MEMBER.at_least(Role.ADMIN)
    assert not Role.MEMBER.at_least(Role.OWNER)


# ---------- Role.parse tolerant lookup ----------


def test_role_parse_returns_none_on_unknown_string():
    """SECURITY/AVAILABILITY pin. `parse` MUST return None on
    unrecognised strings — lets the role check 403 cleanly
    instead of crashing on stale DB data.

    A regression to raising ValueError would 500 every request
    from a user whose `org_members.role` row has any
    non-canonical string (e.g. legacy `superuser`, an experiment
    value, a typo from a manual SQL fix).
    """
    from middleware.rbac import Role

    assert Role.parse("not_a_role") is None
    assert Role.parse("") is None
    assert Role.parse("ADMIN") is None  # case-sensitive; canonical is lowercase
    assert Role.parse("god") is None

    # Sanity: known values still parse.
    assert Role.parse("admin") is Role.ADMIN
    assert Role.parse("owner") is Role.OWNER


# ---------- require_role factory ----------


def test_require_role_returns_async_callable():
    """`require_role(*allowed)` MUST return an async callable. A
    regression that returned None or a sync function would either
    crash FastAPI's dep-resolution at boot OR silently no-op the
    role check on async stacks."""
    from middleware.rbac import Role, require_role

    dep = require_role(Role.ADMIN)
    assert callable(dep)
    assert inspect.iscoroutinefunction(dep)


def test_require_role_accepts_role_enum_and_raw_string():
    """Back-compat pin. `require_role` accepts BOTH Role enums
    AND raw strings — historical call sites use either form. A
    regression that rejected one would break every call site
    using the rejected form."""
    from middleware.rbac import Role, require_role

    # Both forms construct without raising.
    require_role(Role.ADMIN)
    require_role("admin")
    require_role(Role.ADMIN, "owner")  # mixed
    require_role(Role.ADMIN, Role.OWNER)


@pytest.mark.asyncio
async def test_require_role_admits_listed_role():
    """Caller's role IS in the allowed set → returns the AuthContext
    unchanged. The dep is transparent on the success path."""
    from middleware.auth import AuthContext
    from middleware.rbac import Role, require_role

    dep = require_role(Role.ADMIN)
    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="admin",
        email="admin@example.com",
    )
    out = await dep(ctx)
    assert out is ctx


@pytest.mark.asyncio
async def test_require_role_denies_with_403():
    """Caller's role NOT in the allowed set → HTTP 403. NOT 401
    (that would imply 're-auth' in the frontend toast logic) and
    NOT 500 (that would surface as 'platform error')."""
    from fastapi import HTTPException, status

    from middleware.auth import AuthContext
    from middleware.rbac import Role, require_role

    dep = require_role(Role.ADMIN)
    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="member",
        email="member@example.com",
    )
    with pytest.raises(HTTPException) as exc_info:
        await dep(ctx)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ---------- require_min_role factory ----------


def test_require_min_role_returns_async_callable():
    """Same async-callable contract as `require_role`."""
    from middleware.rbac import Role, require_min_role

    dep = require_min_role(Role.ADMIN)
    assert callable(dep)
    assert inspect.iscoroutinefunction(dep)


@pytest.mark.asyncio
async def test_require_min_role_admits_floor_and_above():
    """`require_min_role(ADMIN)` admits both `admin` AND `owner`
    (the rank above). A regression that admitted only the exact
    role would silently lock owners out of admin-only routes."""
    from middleware.auth import AuthContext
    from middleware.rbac import Role, require_min_role

    dep = require_min_role(Role.ADMIN)

    for role_str in ("admin", "owner"):
        ctx = AuthContext(
            user_id=uuid4(),
            organization_id=uuid4(),
            role=role_str,
            email=f"{role_str}@example.com",
        )
        out = await dep(ctx)
        assert out is ctx


@pytest.mark.asyncio
async def test_require_min_role_denies_below_floor():
    """`require_min_role(ADMIN)` rejects `member` and `viewer`."""
    from fastapi import HTTPException, status

    from middleware.auth import AuthContext
    from middleware.rbac import Role, require_min_role

    dep = require_min_role(Role.ADMIN)

    for role_str in ("member", "viewer"):
        ctx = AuthContext(
            user_id=uuid4(),
            organization_id=uuid4(),
            role=role_str,
            email=f"{role_str}@example.com",
        )
        with pytest.raises(HTTPException) as exc_info:
            await dep(ctx)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_require_min_role_denies_unknown_role_with_403():
    """SECURITY pin. A user with a non-canonical role string
    (stale DB row, experiment value) MUST 403 — NOT 500. The
    `Role.parse` returns None, the dep returns 403. A regression
    that crashed here would let a corrupt role row 500 every
    request from that user."""
    from fastapi import HTTPException, status

    from middleware.auth import AuthContext
    from middleware.rbac import Role, require_min_role

    dep = require_min_role(Role.MEMBER)
    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="superadmin",  # non-canonical — Role.parse returns None
        email="x@example.com",
    )
    with pytest.raises(HTTPException) as exc_info:
        await dep(ctx)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ---------- 403 message shape ----------


@pytest.mark.asyncio
async def test_require_role_403_message_includes_required_set():
    """The 403 detail string includes `Insufficient role` (the
    documented prefix that frontend toast logic greps for) AND
    the required role set (so the developer reading the toast
    can fix their request).
    """
    from fastapi import HTTPException

    from middleware.auth import AuthContext
    from middleware.rbac import Role, require_role

    dep = require_role(Role.ADMIN)
    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="member",
        email="m@example.com",
    )
    with pytest.raises(HTTPException) as exc_info:
        await dep(ctx)
    detail = str(exc_info.value.detail)
    assert "Insufficient role" in detail
    assert "admin" in detail


@pytest.mark.asyncio
async def test_require_min_role_403_message_includes_floor():
    """The min-role 403 detail names the floor — so the developer
    seeing the toast knows whether their role mismatch is a
    config issue or an intent change."""
    from fastapi import HTTPException

    from middleware.auth import AuthContext
    from middleware.rbac import Role, require_min_role

    dep = require_min_role(Role.ADMIN)
    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="member",
        email="m@example.com",
    )
    with pytest.raises(HTTPException) as exc_info:
        await dep(ctx)
    detail = str(exc_info.value.detail)
    assert "Insufficient role" in detail
    assert "admin" in detail
