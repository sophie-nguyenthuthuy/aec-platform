"""Tests for the SSE activity-stream subsystem.

Three layers:

  * **Service helpers** — `mint_ticket`, `redeem_ticket`,
    `publish_activity`. Pure functions against a fake redis client.

  * **Ticket replay rejection** — `redeem_ticket` is one-shot
    (GETDEL). Pin the contract so a leaked ticket can't be re-used
    after the legitimate connection.

  * **Router** — `POST /stream/ticket` mints + returns; bad / no
    Redis → 503 fallback. `GET /stream` rejects bad tickets.
    SSE happy-path streaming is unit-tested at the
    `subscribe_activity` level — exercising the StreamingResponse
    end-to-end is brittle without a real Redis.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth
from services.activity_stream import (
    TICKET_TTL_SECONDS,
    _channel_name,
    mint_ticket,
    publish_activity,
    redeem_ticket,
)

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
USER_ID = UUID("66666666-7777-8888-9999-aaaaaaaaaaaa")
PROJECT_ID = UUID("bbbbbbbb-cccc-dddd-eeee-ffffffffffff")


# ---------- Fake redis ----------


class FakeRedis:
    """Minimal Redis stand-in supporting `set` (with ex), `getdel`,
    and `publish` capture. Doesn't simulate TTL countdown — tests
    that need expiry behavior simulate it via direct dict mutation."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.kv[key] = value
        return True

    async def getdel(self, key: str) -> str | None:
        return self.kv.pop(key, None)

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1


# ---------- mint_ticket ----------


async def test_mint_ticket_stores_payload_with_ttl():
    """SETEX call must include the bound (user, org, project) and a
    30s TTL. Pin so a refactor that drops the TTL doesn't turn the
    ticket into a forever-credential."""
    r = FakeRedis()
    ticket = await mint_ticket(
        r,
        user_id=USER_ID,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
    )
    assert ticket is not None
    assert len(ticket) == 32  # uuid4 hex
    key = f"aec:sse:ticket:{ticket}"
    assert key in r.kv
    payload = json.loads(r.kv[key])
    assert payload["user_id"] == str(USER_ID)
    assert payload["organization_id"] == str(ORG_ID)
    assert payload["project_id"] == str(PROJECT_ID)


async def test_mint_ticket_returns_none_when_redis_unavailable():
    """No Redis → no ticket. Caller surfaces 503 so the frontend
    falls back to polling."""
    out = await mint_ticket(None, user_id=USER_ID, organization_id=ORG_ID, project_id=None)
    assert out is None


async def test_mint_ticket_persists_null_project_for_org_wide():
    """When project_id is None, the bound payload preserves None
    rather than serialising as 'None' or ''. Pin so org-wide
    subscribers get unambiguous routing."""
    r = FakeRedis()
    ticket = await mint_ticket(r, user_id=USER_ID, organization_id=ORG_ID, project_id=None)
    assert ticket is not None
    payload = json.loads(r.kv[f"aec:sse:ticket:{ticket}"])
    assert payload["project_id"] is None


# ---------- redeem_ticket: one-shot ----------


async def test_redeem_ticket_returns_payload_then_invalidates():
    """First redeem succeeds; second redeem of the same ticket
    returns None. Pin the one-shot semantics — without it a leaked
    ticket lets a passive observer pull the stream alongside the
    real connection."""
    r = FakeRedis()
    ticket = await mint_ticket(r, user_id=USER_ID, organization_id=ORG_ID, project_id=PROJECT_ID)
    assert ticket is not None
    bound = await redeem_ticket(r, ticket)
    assert bound is not None
    assert bound["organization_id"] == str(ORG_ID)
    # Second redeem fails — the GETDEL purged the entry.
    replay = await redeem_ticket(r, ticket)
    assert replay is None


async def test_redeem_ticket_returns_none_for_unknown_id():
    """Forged or expired ticket → None. The router maps to 401."""
    r = FakeRedis()
    out = await redeem_ticket(r, "deadbeef" * 4)
    assert out is None


async def test_redeem_ticket_falls_back_to_pipeline_when_no_getdel():
    """Older Redis versions (<6.2) don't have GETDEL. The service
    falls back to a GET+DEL pipeline. Pin so we don't break ops
    running an older Redis (e.g. AWS Elasticache before the upgrade
    landed)."""

    class OldRedis:
        def __init__(self) -> None:
            self.kv = {"aec:sse:ticket:abc": json.dumps({"organization_id": str(ORG_ID)})}

        # No `getdel` attribute — forces fallback path.
        def pipeline(self):
            return _OldPipeline(self.kv)

    class _OldPipeline:
        def __init__(self, kv) -> None:
            self.kv = kv
            self._ops: list = []

        def get(self, key):
            self._ops.append(("get", key))

        def delete(self, key):
            self._ops.append(("delete", key))

        async def execute(self) -> list[Any]:
            results: list[Any] = []
            for op, k in self._ops:
                if op == "get":
                    results.append(self.kv.get(k))
                else:
                    results.append(1 if self.kv.pop(k, None) is not None else 0)
            return results

    r = OldRedis()
    bound = await redeem_ticket(r, "abc")
    assert bound is not None
    assert bound["organization_id"] == str(ORG_ID)
    # Replay still rejected.
    replay = await redeem_ticket(r, "abc")
    assert replay is None


# ---------- publish_activity ----------


async def test_publish_activity_uses_per_project_channel():
    """Channel format: `aec:activity:<org>:<project>`. Pin so a
    refactor that flattens to org-wide doesn't silently broadcast
    project-A events to project-B subscribers."""
    r = FakeRedis()
    await publish_activity(
        r,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        event={"action": "x", "resource_type": "y"},
    )
    assert len(r.published) == 1
    channel, body = r.published[0]
    assert channel == f"aec:activity:{ORG_ID}:{PROJECT_ID}"
    parsed = json.loads(body)
    assert parsed == {"action": "x", "resource_type": "y"}


async def test_publish_activity_no_op_when_redis_none():
    """Dev path with no Redis — silent no-op, NOT an exception."""
    # Should not raise.
    await publish_activity(None, organization_id=ORG_ID, project_id=None, event={"x": 1})


async def test_publish_activity_swallows_redis_errors():
    """A Redis hiccup must NOT propagate — the audit row already
    committed; the SSE push is a UX nicety. Pin so the audit path
    can't be broken by a Redis blip."""

    class BoomRedis:
        async def publish(self, *_a, **_kw):
            raise RuntimeError("connection refused")

    # Should not raise.
    await publish_activity(
        BoomRedis(),
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        event={"x": 1},
    )


# ---------- Channel naming ----------


async def test_channel_name_distinguishes_org_wide_from_project():
    """Org-wide (project_id=None) uses the ':org' suffix. Pin so
    a future psubscribe-by-pattern subscriber doesn't accidentally
    capture per-project events under the org channel."""
    a = _channel_name(ORG_ID, PROJECT_ID)
    b = _channel_name(ORG_ID, None)
    assert a != b
    assert a.endswith(str(PROJECT_ID))
    assert b.endswith(":org")


# ---------- Router: POST /stream/ticket ----------


def _build_app() -> FastAPI:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from routers import activity_stream as router_module

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(router_module.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="caller@example.com",
    )
    app.dependency_overrides[require_auth] = lambda: auth_ctx
    return app


async def test_ticket_endpoint_returns_ticket_with_ttl(monkeypatch):
    """Happy path: ticket minted + TTL surfaced to the client."""
    fake = FakeRedis()

    async def _stub_redis():
        return fake

    monkeypatch.setattr("routers.activity_stream._redis_or_none", _stub_redis)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(f"/api/v1/activity/stream/ticket?project_id={PROJECT_ID}")
    assert res.status_code == 201, res.text
    body = res.json()["data"]
    assert "ticket" in body
    assert len(body["ticket"]) == 32
    assert body["expires_in"] == TICKET_TTL_SECONDS
    # Bound payload landed in Redis.
    key = f"aec:sse:ticket:{body['ticket']}"
    assert key in fake.kv


async def test_ticket_endpoint_returns_503_when_redis_unavailable(monkeypatch):
    """No Redis → 503 with a friendly message. Pin so the frontend
    can detect the fallback case and revert to polling instead of
    breaking silently."""

    async def _stub_redis():
        return None

    monkeypatch.setattr("routers.activity_stream._redis_or_none", _stub_redis)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/activity/stream/ticket")
    assert res.status_code == 503
    assert "activity_stream_unavailable" in res.text


# ---------- Router: GET /stream ----------


async def test_stream_rejects_bad_ticket(monkeypatch):
    """Forged ticket → 401. Pin so a partner can't open a stream by
    guessing at ticket UUIDs."""
    fake = FakeRedis()

    async def _stub_redis():
        return fake

    monkeypatch.setattr("routers.activity_stream._redis_or_none", _stub_redis)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/activity/stream?ticket=deadbeef" + "0" * 24)
    assert res.status_code == 401
    assert "invalid_or_expired_ticket" in res.text


async def test_stream_rejects_project_mismatch(monkeypatch):
    """Ticket minted for project A + connection asks for project B
    → 401. Defense against URL pivot attacks."""
    fake = FakeRedis()

    async def _stub_redis():
        return fake

    monkeypatch.setattr("routers.activity_stream._redis_or_none", _stub_redis)

    # Mint a ticket bound to PROJECT_ID.
    ticket = await mint_ticket(fake, user_id=USER_ID, organization_id=ORG_ID, project_id=PROJECT_ID)

    other_project = uuid4()
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/activity/stream?ticket={ticket}&project_id={other_project}")
    assert res.status_code == 401
    assert "ticket_project_mismatch" in res.text


async def test_stream_replay_after_redeem_returns_401(monkeypatch):
    """Re-using a ticket after the original connection redeemed it
    → 401. Pin the one-shot semantics at the router level."""
    fake = FakeRedis()

    async def _stub_redis():
        return fake

    monkeypatch.setattr("routers.activity_stream._redis_or_none", _stub_redis)

    ticket = await mint_ticket(fake, user_id=USER_ID, organization_id=ORG_ID, project_id=PROJECT_ID)
    # Manually redeem (simulate the legit connection).
    await redeem_ticket(fake, ticket)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/activity/stream?ticket={ticket}&project_id={PROJECT_ID}")
    assert res.status_code == 401
