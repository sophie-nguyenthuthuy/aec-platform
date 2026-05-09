"""Tests for the api_keys subsystem.

Three layers:

  * Pure helpers — `hash_key`, `key_prefix`, `_generate_key`,
    `has_scope`. No session, no Redis.

  * Service — `mint_key` (bound params), `verify_key` (positive +
    negative paths), `check_rate_limit` (Redis token bucket against a
    fake redis pipeline).

  * Router CRUD — POST mint returns the plaintext exactly once,
    listing redacts secrets, revoke is idempotent.

The dual-auth dependency `require_user_or_api_key` is exercised
end-to-end via a tiny synthetic protected route — verify a user JWT
override + an api-key path both resolve to the same AuthContext shape.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role
from services.api_keys import (
    KEY_PREFIX,
    SCOPES,
    _generate_key,
    check_rate_limit,
    has_scope,
    hash_key,
    key_prefix,
    mint_key,
    verify_key,
)

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
KEY_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


# ---------- FakeAsyncSession ----------


class FakeAsyncSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.mappings.return_value.one.return_value = {}
        r.mappings.return_value.one_or_none.return_value = None
        r.mappings.return_value.all.return_value = []
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture(autouse=True)
def patch_tenant_session(fake_db, monkeypatch):
    """Replace TenantAwareSession + AdminSessionFactory with CMs that
    yield the shared fake. The api-key auth path uses
    AdminSessionFactory; the CRUD endpoints use TenantAwareSession."""

    @asynccontextmanager
    async def _tenant(_org_id: UUID) -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    @asynccontextmanager
    async def _admin() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    monkeypatch.setattr("routers.api_keys.TenantAwareSession", _tenant)
    monkeypatch.setattr("middleware.api_key_auth.AdminSessionFactory", _admin)
    yield fake_db


# ---------- Pure helpers ----------


async def test_generate_key_has_aec_prefix_and_high_entropy():
    """Every key must start with `aec_` (log-scrubber + auth path
    pattern-match) and the body must be 64 hex chars (256 bits before
    the `aec_` prefix prep). Pin both."""
    k = _generate_key()
    assert k.startswith(KEY_PREFIX)
    body = k.removeprefix(KEY_PREFIX)
    assert len(body) == 64
    int(body, 16)  # raises ValueError if not hex
    # Two independent draws collide with vanishingly small probability.
    assert _generate_key() != _generate_key()


async def test_hash_key_is_deterministic_sha256():
    """sha256 of "aec_test" hex-encoded. Spot-check the wire format."""
    h = hash_key("aec_test")
    assert len(h) == 64
    int(h, 16)
    # Determinism: same input → same output.
    assert hash_key("aec_test") == h
    # Different input → different output (avalanche).
    assert hash_key("aec_other") != h


async def test_key_prefix_drops_aec_and_takes_first_8():
    raw = "aec_a1b2c3d4e5f6abcdef1234567890abcdef1234567890abcdef1234567890ab"
    assert key_prefix(raw) == "a1b2c3d4"


async def test_has_scope_treats_wildcard_as_full_access():
    """`*` scope short-circuits — used for org-admin keys. Required
    behaviour because scope handlers shouldn't have to enumerate
    every possible permission for a `*` key."""
    assert has_scope(["*"], "projects:read") is True
    assert has_scope(["projects:read"], "projects:read") is True
    assert has_scope(["projects:read"], "projects:write") is False
    assert has_scope([], "projects:read") is False


# ---------- Mint ----------


async def test_mint_key_persists_hash_not_plaintext(fake_db):
    """The bound params must contain `hash` (sha256-hex) and NOT the
    raw key. Pin the contract — a regression here would leak secrets
    on a DB compromise."""
    insert_result = MagicMock()
    insert_result.mappings.return_value.one.return_value = {
        "id": KEY_ID,
        "name": "Production CRM",
        "prefix": "deadbeef",
        "scopes": ["projects:read"],
        "rate_limit_per_minute": None,
        "created_at": datetime(2026, 5, 4, tzinfo=UTC),
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
    }
    fake_db.push(insert_result)

    raw, row = await mint_key(
        fake_db,
        organization_id=ORG_ID,
        created_by=USER_ID,
        name="Production CRM",
        scopes=["projects:read"],
        rate_limit_per_minute=None,
        expires_at=None,
    )

    assert raw.startswith(KEY_PREFIX)
    params = fake_db.calls[0][1]
    # Hash matches what we just generated.
    assert params["hash"] == hash_key(raw)
    # Plaintext is NOT in the bound params under any name.
    for v in params.values():
        if isinstance(v, str):
            assert raw not in v
    # Prefix matches the first 8 chars of the body.
    assert params["prefix"] == key_prefix(raw)


async def test_mint_key_rejects_unknown_scope(fake_db):
    """Service-level scope check — defense in depth on top of the
    router's pydantic validation. An unknown scope must NOT reach
    the INSERT."""
    with pytest.raises(ValueError, match="unknown_scope"):
        await mint_key(
            fake_db,
            organization_id=ORG_ID,
            created_by=USER_ID,
            name="bad",
            scopes=["fake:scope"],
            rate_limit_per_minute=None,
            expires_at=None,
        )
    assert fake_db.calls == []


# ---------- Verify ----------


async def test_verify_key_returns_row_for_active_key(fake_db):
    """Happy path: hash matches, key not revoked, not expired."""
    raw = _generate_key()
    update_result = MagicMock()
    update_result.mappings.return_value.one_or_none.return_value = {
        "id": KEY_ID,
        "organization_id": ORG_ID,
        "scopes": ["projects:read"],
        "rate_limit_per_minute": None,
        "name": "test",
        "prefix": key_prefix(raw),
    }
    fake_db.push(update_result)

    out = await verify_key(fake_db, raw=raw, client_ip="1.2.3.4")
    assert out is not None
    assert out["organization_id"] == ORG_ID
    # Bound hash matches the raw input.
    params = fake_db.calls[0][1]
    assert params["hash"] == hash_key(raw)
    assert params["ip"] == "1.2.3.4"
    # SQL filters revoked + expired in one round trip.
    sql = str(fake_db.calls[0][0])
    assert "revoked_at IS NULL" in sql
    assert "expires_at IS NULL OR expires_at > NOW()" in sql


async def test_verify_key_returns_none_for_unknown_hash(fake_db):
    """No row → None. The router maps that to 401."""
    update_result = MagicMock()
    update_result.mappings.return_value.one_or_none.return_value = None
    fake_db.push(update_result)
    out = await verify_key(fake_db, raw=_generate_key(), client_ip=None)
    assert out is None


async def test_verify_key_rejects_non_aec_token(fake_db):
    """A plain JWT (`eyJ…`) must NOT be looked up — saves a round trip
    and avoids accidentally treating a JWT as a key."""
    out = await verify_key(fake_db, raw="eyJhbGciOiJIUzI1NiJ9.foo.bar", client_ip=None)
    assert out is None
    assert fake_db.calls == []


# ---------- Rate limit ----------


async def test_check_rate_limit_allows_under_limit():
    """First request of the minute → count=1, under any reasonable
    limit. INCR returns 1, EXPIRE returns True, allowed=True."""
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=[1, True])
    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=pipe)

    allowed, count, limit = await check_rate_limit(
        redis,
        api_key_id=KEY_ID,
        limit_per_minute=60,
    )
    assert allowed is True
    assert count == 1
    assert limit == 60


async def test_check_rate_limit_denies_over_limit():
    """Count above the per-key limit → allowed=False. Router maps to 429."""
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=[61, True])
    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=pipe)

    allowed, count, limit = await check_rate_limit(
        redis,
        api_key_id=KEY_ID,
        limit_per_minute=60,
    )
    assert allowed is False
    assert count == 61


async def test_check_rate_limit_no_redis_permits_all():
    """Dev path with no Redis: short-circuit to allowed=True. Avoids
    the chicken-and-egg of "needs Redis to boot a single-process
    server"."""
    allowed, count, limit = await check_rate_limit(
        None,
        api_key_id=KEY_ID,
        limit_per_minute=60,
    )
    assert allowed is True
    assert count == 0
    assert limit == 60


# ---------- Router: list_scopes ----------


def _build_app() -> FastAPI:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from routers import api_keys as ak_router

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(ak_router.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="caller@example.com",
    )
    app.dependency_overrides[require_min_role(Role.ADMIN)] = lambda: auth_ctx
    app.dependency_overrides[require_auth] = lambda: auth_ctx
    return app


async def test_scopes_endpoint_returns_canonical_vocabulary():
    """Pin the response so a typo on a single scope name doesn't
    silently land in the create form."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/api-keys/scopes")
    assert res.status_code == 200
    body = res.json()["data"]
    assert set(body) == set(SCOPES)
    assert body == sorted(body)  # deterministic ordering


# ---------- Router: create ----------


async def test_create_returns_plaintext_exactly_once(fake_db):
    """The POST body MUST contain the raw key. Pin the response shape
    so the frontend's "copy and store" warning lines up with reality."""
    insert_result = MagicMock()
    insert_result.mappings.return_value.one.return_value = {
        "id": KEY_ID,
        "name": "test key",
        "prefix": "deadbeef",
        "scopes": ["projects:read"],
        "rate_limit_per_minute": None,
        "created_at": datetime(2026, 5, 4, tzinfo=UTC),
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
    }
    fake_db.push(insert_result)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/api-keys",
            json={"name": "test key", "scopes": ["projects:read"]},
        )
    assert res.status_code == 201, res.text
    body = res.json()["data"]
    assert "key" in body
    assert body["key"].startswith(KEY_PREFIX)
    assert body["prefix"] == "deadbeef"
    # No `hash` field in the response.
    assert "hash" not in body


async def test_create_rejects_unknown_scope_with_400(fake_db):
    """Service-side ValueError → 400 with the offending scope quoted
    in the message. UI surfaces this directly."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/api-keys",
            json={"name": "bad", "scopes": ["fake:scope"]},
        )
    assert res.status_code == 400
    assert "fake:scope" in res.text


# ---------- Router: list ----------


async def test_list_keys_redacts_hash_and_omits_plaintext(fake_db):
    """Listing must NEVER return `hash` (DB-only) or `key`
    (one-shot at create). Pin both omissions."""
    list_result = MagicMock()
    list_result.mappings.return_value.all.return_value = [
        {
            "id": KEY_ID,
            "name": "k1",
            "prefix": "deadbeef",
            "scopes": ["projects:read"],
            "rate_limit_per_minute": 120,
            "last_used_at": datetime(2026, 5, 4, tzinfo=UTC),
            "last_used_ip": "1.2.3.4",
            "revoked_at": None,
            "expires_at": None,
            "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        }
    ]
    fake_db.push(list_result)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/api-keys")
    assert res.status_code == 200
    body = res.json()["data"]
    assert len(body) == 1
    row = body[0]
    assert "hash" not in row
    assert "key" not in row
    assert row["prefix"] == "deadbeef"
    assert row["last_used_ip"] == "1.2.3.4"


# ---------- Router: revoke ----------


async def test_revoke_is_idempotent(fake_db):
    """Calling revoke twice must NOT bump revoked_at (the COALESCE
    keeps the original timestamp). Pin so a UI double-click doesn't
    overwrite the audit value."""
    revoke_result = MagicMock()
    fixed = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
    revoke_result.mappings.return_value.one_or_none.return_value = {
        "id": KEY_ID,
        "revoked_at": fixed,
    }
    fake_db.push(revoke_result)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(f"/api/v1/api-keys/{KEY_ID}/revoke")
    assert res.status_code == 200
    sql = str(fake_db.calls[0][0])
    assert "COALESCE(revoked_at, NOW())" in sql


async def test_revoke_404_on_unknown_key(fake_db):
    """RLS keeps cross-org IDs out of reach — those manifest as 404."""
    revoke_result = MagicMock()
    revoke_result.mappings.return_value.one_or_none.return_value = None
    fake_db.push(revoke_result)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(f"/api/v1/api-keys/{uuid4()}/revoke")
    assert res.status_code == 404


# ---------- Dual auth: require_user_or_api_key ----------


async def test_dual_auth_resolves_api_key_to_authcontext(fake_db, monkeypatch):
    """A request with `Authorization: Bearer aec_…` must resolve to
    an AuthContext with role=api_key and the org_id from the key row.

    Use a synthetic protected route — no need to spin up the whole
    user-auth dependency chain just to verify the api-key branch.
    """
    raw_key = _generate_key()
    # verify_key UPDATE result
    update_result = MagicMock()
    update_result.mappings.return_value.one_or_none.return_value = {
        "id": KEY_ID,
        "organization_id": ORG_ID,
        "scopes": ["projects:read"],
        "rate_limit_per_minute": None,
        "name": "test",
        "prefix": key_prefix(raw_key),
    }
    fake_db.push(update_result)

    # Stub Redis so the rate-limit check returns "allowed" without
    # touching real Redis.
    async def _stub_redis():
        return None  # check_rate_limit treats None as allowed

    monkeypatch.setattr("middleware.api_key_auth._get_redis", _stub_redis)

    from middleware.api_key_auth import require_user_or_api_key

    app = FastAPI()

    @app.get("/test/protected")
    async def protected(auth: AuthContext = pytest.importorskip("fastapi").Depends(require_user_or_api_key)):  # noqa: B008
        return {"user_id": str(auth.user_id), "role": auth.role, "org": str(auth.organization_id)}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            "/test/protected",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["role"] == "api_key"
    assert body["org"] == str(ORG_ID)
    assert body["user_id"] == str(KEY_ID)


async def test_dual_auth_rate_limits_to_429(fake_db, monkeypatch):
    """Over-limit request returns 429 with a Retry-After header.
    Pin so a misbehaving client can't DoS the cluster — and so
    well-behaved clients see the retry hint.

    Realistic shape: per-key limit of 1/min, Redis already at 2 (the
    bucket survived from a previous request this same minute). The
    INCR bumps to 2, which is `> 1` → deny.
    """
    raw_key = _generate_key()
    update_result = MagicMock()
    update_result.mappings.return_value.one_or_none.return_value = {
        "id": KEY_ID,
        "organization_id": ORG_ID,
        "scopes": ["*"],
        "rate_limit_per_minute": 1,
        "name": "test",
        "prefix": key_prefix(raw_key),
    }
    fake_db.push(update_result)

    # INCR returns 2 → exceeds limit_per_minute=1 → denied.
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=[2, True])
    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=pipe)

    async def _stub_redis():
        return redis

    monkeypatch.setattr("middleware.api_key_auth._get_redis", _stub_redis)

    from middleware.api_key_auth import require_user_or_api_key

    app = FastAPI()

    @app.get("/test/protected")
    async def protected(auth: AuthContext = pytest.importorskip("fastapi").Depends(require_user_or_api_key)):  # noqa: B008
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            "/test/protected",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert res.status_code == 429
    assert "retry-after" in res.headers
