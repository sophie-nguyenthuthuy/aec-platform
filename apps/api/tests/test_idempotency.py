"""Tests for the Idempotency-Key replay cache.

Two layers:

  * Pure helpers — `canonicalise_body`, `hash_body`, `lookup_or_lock`,
    `persist_response`. Fake-session level; no real Postgres.

  * `IdempotentRoute` — exercised end-to-end via a synthetic FastAPI
    app that mounts a tiny POST handler with `route_class=
    IdempotentRoute`. Verifies cache miss → handler runs → response
    cached, and cache hit → handler short-circuited with the cached
    body + `X-AEC-Idempotent-Replay: true`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.idempotency import (
    canonicalise_body,
    hash_body,
    lookup_or_lock,
    persist_response,
)

pytestmark = pytest.mark.asyncio


KEY_ID = UUID("11111111-2222-3333-4444-555555555555")
KEY = "test-idempotency-uuid-001"


# ---------- FakeAsyncSession ----------


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
        r.mappings.return_value.one_or_none.return_value = None
        r.scalar_one_or_none.return_value = None
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


# ---------- canonicalise_body / hash_body ----------


async def test_canonicalise_collapses_key_order():
    """JSON with reordered keys MUST hash the same — partners using
    different serialisers across retries would otherwise miss the
    cache."""
    a = b'{"a":1,"b":2}'
    b = b'{"b":2,"a":1}'
    assert canonicalise_body(a) == canonicalise_body(b)
    assert hash_body(a) == hash_body(b)


async def test_canonicalise_collapses_whitespace():
    """Pretty-printed vs compact JSON hash the same."""
    a = b'{"a":1,"b":2}'
    b = b'{\n  "a": 1,\n  "b": 2\n}'
    assert hash_body(a) == hash_body(b)


async def test_canonicalise_passes_non_json_through():
    """Multipart uploads / plain text bodies are hashed as-is.
    The shape doesn't matter as long as the same bytes hash the same."""
    body = b"--boundary\r\nContent-Disposition: form-data\r\n\r\nblob"
    assert canonicalise_body(body) == body
    # Different bytes → different hash.
    assert hash_body(body) != hash_body(body + b"x")


async def test_hash_body_handles_empty():
    """Empty body still produces a valid hash (the sha256 of zero
    bytes). Pin so DELETE requests with no body still cache."""
    assert hash_body(None) == hash_body(b"") == hash_body("")


# ---------- lookup_or_lock ----------


async def test_lookup_returns_fresh_when_no_prior_record(fake_db):
    """No row in idempotency_records → fresh result. Caller runs the
    handler."""
    miss = MagicMock()
    miss.mappings.return_value.one_or_none.return_value = None
    fake_db.push(miss)

    out = await lookup_or_lock(
        fake_db,
        api_key_id=KEY_ID,
        key=KEY,
        request_hash="abc",
        method="POST",
        path="/api/v1/handover/defects",
    )
    assert out.fresh is True
    assert out.cached is False
    assert out.mismatch is False


async def test_lookup_returns_cached_on_full_match(fake_db):
    """Same hash + method + path → replay the cached response."""
    hit = MagicMock()
    hit.mappings.return_value.one_or_none.return_value = {
        "request_hash": "abc",
        "request_method": "POST",
        "request_path": "/api/v1/handover/defects",
        "response_status": 201,
        "response_body": {"data": {"id": "..."}},
    }
    fake_db.push(hit)

    out = await lookup_or_lock(
        fake_db,
        api_key_id=KEY_ID,
        key=KEY,
        request_hash="abc",
        method="POST",
        path="/api/v1/handover/defects",
    )
    assert out.cached is True
    assert out.cached_status == 201
    assert out.cached_body == {"data": {"id": "..."}}


async def test_lookup_returns_mismatch_on_different_body_hash(fake_db):
    """Same key but different body → 422 path. Catches partner bugs
    where the same Idempotency-Key gets reused with mutated payload."""
    hit = MagicMock()
    hit.mappings.return_value.one_or_none.return_value = {
        "request_hash": "OLD-hash",
        "request_method": "POST",
        "request_path": "/api/v1/handover/defects",
        "response_status": 201,
        "response_body": {},
    }
    fake_db.push(hit)

    out = await lookup_or_lock(
        fake_db,
        api_key_id=KEY_ID,
        key=KEY,
        request_hash="NEW-hash",
        method="POST",
        path="/api/v1/handover/defects",
    )
    assert out.mismatch is True
    assert out.cached is False


async def test_lookup_returns_mismatch_on_different_route(fake_db):
    """Same key reused on a DIFFERENT method/path → 422. Stripe-style
    behaviour: catches partners who copy-paste an idempotency key
    across distinct integration calls."""
    hit = MagicMock()
    hit.mappings.return_value.one_or_none.return_value = {
        "request_hash": "abc",
        "request_method": "POST",
        "request_path": "/api/v1/handover/defects",
        "response_status": 201,
        "response_body": {},
    }
    fake_db.push(hit)

    out = await lookup_or_lock(
        fake_db,
        api_key_id=KEY_ID,
        key=KEY,
        request_hash="abc",
        method="POST",
        path="/api/v1/handover/packages",  # different path
    )
    assert out.mismatch is True


async def test_lookup_uses_for_update_lock(fake_db):
    """The SELECT MUST acquire a row lock so concurrent retries
    serialise. Pin the SQL — otherwise two parallel retries could
    both find no row and double-execute the handler."""
    miss = MagicMock()
    miss.mappings.return_value.one_or_none.return_value = None
    fake_db.push(miss)

    await lookup_or_lock(
        fake_db,
        api_key_id=KEY_ID,
        key=KEY,
        request_hash="abc",
        method="POST",
        path="/x",
    )
    sql = str(fake_db.calls[0][0])
    assert "FOR UPDATE" in sql


# ---------- persist_response ----------


async def test_persist_response_uses_on_conflict_do_nothing(fake_db):
    """Concurrent writers MUST NOT 500 with PK violation. Pin the
    `ON CONFLICT (api_key_id, key) DO NOTHING` clause — first writer
    wins; second writer's cache attempt is a no-op."""
    await persist_response(
        fake_db,
        api_key_id=KEY_ID,
        key=KEY,
        request_hash="abc",
        method="POST",
        path="/x",
        response_status=201,
        response_body={"ok": True},
    )
    sql = str(fake_db.calls[0][0])
    assert "ON CONFLICT (api_key_id, key) DO NOTHING" in sql


async def test_persist_response_swallows_db_errors():
    """Cache failure must not propagate — the user-facing response
    has already been built. The next retry just executes the handler
    again (worse, but correct)."""

    class BoomSession:
        async def execute(self, *_a, **_kw):
            raise RuntimeError("table missing")

    # Should NOT raise.
    await persist_response(
        BoomSession(),
        api_key_id=KEY_ID,
        key=KEY,
        request_hash="abc",
        method="POST",
        path="/x",
        response_status=201,
        response_body={},
    )


# ---------- IdempotentRoute end-to-end ----------


def _build_e2e_app(fake_db: FakeAsyncSession, api_key_lookup_id: UUID | None) -> FastAPI:
    """Spin up a minimal FastAPI app with one POST handler under
    `route_class=IdempotentRoute`. The handler increments a counter
    so we can assert "ran twice" vs "ran once + replay"."""

    from fastapi import APIRouter

    from middleware.idempotency_route import IdempotentRoute

    counter = {"n": 0}

    test_router = APIRouter(route_class=IdempotentRoute)

    @test_router.post("/test/echo", status_code=201)
    async def echo() -> dict:
        counter["n"] += 1
        return {"data": {"count": counter["n"]}}

    app = FastAPI()
    app.include_router(test_router)
    app.state.handler_counter = counter
    return app


@pytest.fixture
def patch_idempotency(fake_db, monkeypatch):
    """Replace `AdminSessionFactory` in the route module with a CM
    yielding the shared fake. The same fake handles both the
    api_key_id lookup AND the idempotency lookup/persist."""

    @asynccontextmanager
    async def _factory():
        yield fake_db

    monkeypatch.setattr("middleware.idempotency_route.AdminSessionFactory", _factory)


async def test_route_passes_through_when_no_idempotency_header(fake_db, patch_idempotency):
    """No `Idempotency-Key` → handler runs normally, no DB lookup."""
    app = _build_e2e_app(fake_db, KEY_ID)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/test/echo", json={"x": 1})
    assert res.status_code == 201
    assert app.state.handler_counter["n"] == 1
    # No DB calls — fast path.
    assert fake_db.calls == []


async def test_route_passes_through_for_user_jwt(fake_db, patch_idempotency):
    """Authorization header that doesn't start with `aec_` → user JWT
    path; idempotency is api-key-only in v1, so falls through."""
    app = _build_e2e_app(fake_db, KEY_ID)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/test/echo",
            json={"x": 1},
            headers={
                "Idempotency-Key": KEY,
                "Authorization": "Bearer eyJfake.jwt",
            },
        )
    assert res.status_code == 201
    assert app.state.handler_counter["n"] == 1


async def test_route_caches_first_response_and_replays_second(fake_db, patch_idempotency):
    """Cache miss on first request → handler runs once → response
    cached. Cache hit on second request → handler NOT invoked, body
    replayed, `X-AEC-Idempotent-Replay: true` header present."""
    app = _build_e2e_app(fake_db, KEY_ID)

    # Request 1: api_key lookup hits (api_key_id), idempotency lookup misses,
    # then persist.
    api_key_hit = MagicMock()
    api_key_hit.scalar_one_or_none.return_value = KEY_ID
    fake_db.push(api_key_hit)
    idem_miss = MagicMock()
    idem_miss.mappings.return_value.one_or_none.return_value = None
    fake_db.push(idem_miss)
    # persist INSERT — default empty MagicMock is fine.

    transport = ASGITransport(app=app)
    headers = {
        "Idempotency-Key": KEY,
        "Authorization": "Bearer aec_a1b2c3d4e5f6abcdef1234567890abcdef1234567890abcdef1234567890ab",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res1 = await ac.post("/test/echo", json={"x": 1}, headers=headers)
    assert res1.status_code == 201
    assert res1.json() == {"data": {"count": 1}}
    assert app.state.handler_counter["n"] == 1

    # Request 2: api_key lookup hits, idempotency lookup hits → replay.
    api_key_hit2 = MagicMock()
    api_key_hit2.scalar_one_or_none.return_value = KEY_ID
    fake_db.push(api_key_hit2)
    idem_hit = MagicMock()
    idem_hit.mappings.return_value.one_or_none.return_value = {
        "request_hash": hash_body(b'{"x":1}'),
        "request_method": "POST",
        "request_path": "/test/echo",
        "response_status": 201,
        "response_body": {"data": {"count": 1}},
    }
    fake_db.push(idem_hit)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res2 = await ac.post("/test/echo", json={"x": 1}, headers=headers)
    assert res2.status_code == 201
    assert res2.json() == {"data": {"count": 1}}
    # Handler counter UNCHANGED — replay short-circuited.
    assert app.state.handler_counter["n"] == 1
    # Replay marker present.
    assert res2.headers.get("x-aec-idempotent-replay") == "true"


async def test_route_returns_422_on_body_mismatch(fake_db, patch_idempotency):
    """Same key, different body → 422. The original handler is NOT
    re-invoked (the partner's bug needs to be fixed before any new
    write happens)."""
    app = _build_e2e_app(fake_db, KEY_ID)

    api_key_hit = MagicMock()
    api_key_hit.scalar_one_or_none.return_value = KEY_ID
    fake_db.push(api_key_hit)
    idem_mismatch = MagicMock()
    idem_mismatch.mappings.return_value.one_or_none.return_value = {
        "request_hash": "OLD",
        "request_method": "POST",
        "request_path": "/test/echo",
        "response_status": 201,
        "response_body": {},
    }
    fake_db.push(idem_mismatch)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/test/echo",
            json={"different": "body"},
            headers={
                "Idempotency-Key": KEY,
                "Authorization": "Bearer aec_a1b2c3d4e5f6abcdef1234567890abcdef1234567890abcdef1234567890ab",
            },
        )
    assert res.status_code == 422
    assert "idempotency_key_reused_with_different_body" in res.text
    # Handler NOT called.
    assert app.state.handler_counter["n"] == 0


async def test_route_rejects_oversized_key(fake_db, patch_idempotency):
    """Key > MAX_KEY_LEN → 400 BEFORE we hash any body. Defense
    against "1MB payload + 10MB key" DoS shapes."""
    app = _build_e2e_app(fake_db, KEY_ID)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/test/echo",
            json={"x": 1},
            headers={
                "Idempotency-Key": "x" * 1024,
                "Authorization": "Bearer aec_a1b2c3d4e5f6abcdef1234567890abcdef1234567890abcdef1234567890ab",
            },
        )
    assert res.status_code == 400
    assert "idempotency_key_too_long" in res.text
    # No DB calls — fast path.
    assert fake_db.calls == []
