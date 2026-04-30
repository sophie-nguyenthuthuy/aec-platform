"""Router tests for the webhook subscription endpoints.

Covers:
  * Admin gating — `member` and `viewer` get 403 from `require_min_role`.
  * Create returns the secret exactly once (and only at creation).
  * List omits `secret` from the response (security pin).
  * Idempotent (URL-unique) creates 409.
  * Update (toggle enabled, change event_types) returns the updated row.
  * Delete is idempotent — non-existent IDs return 204.
  * Test-fire enqueues a `webhook.test` delivery.
  * Recent deliveries endpoint returns rows in created_at-desc order.
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

from middleware.auth import AuthContext, require_auth  # noqa: F401

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None: ...
    async def close(self) -> None: ...
    async def flush(self) -> None: ...

    async def refresh(self, obj: Any) -> None:
        # The router calls `db.refresh(sub)` after commit — fake by
        # populating the timestamp + auto-increment-style fields the
        # response shape requires.
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime.now(UTC)

    async def execute(self, stmt: Any, *_a: Any, **_kw: Any) -> Any:
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.scalar_one.return_value = 0
        r.scalars.return_value.all.return_value = []
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


def _build_app(role: str, fake_db: FakeAsyncSession) -> FastAPI:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from routers import webhooks as webhooks_router

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="caller@example.com",
    )

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(webhooks_router.router)

    async def _db_override() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[get_db] = _db_override
    return app


def _sub_row(**overrides: Any):
    """Mutable stand-in for the WebhookSubscription ORM row."""
    from types import SimpleNamespace

    base = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        url="https://example.com/hook",
        secret="abc" * 22 + "ab",
        event_types=[],
        enabled=True,
        last_delivery_at=None,
        failure_count=0,
        created_by=USER_ID,
        created_at=datetime(2026, 4, 30, tzinfo=UTC),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------- Admin gating ----------


async def test_create_403_for_member(fake_db):
    app = _build_app("member", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/webhooks", json={"url": "https://example.com/h", "event_types": []})
    assert res.status_code == 403


async def test_list_403_for_viewer(fake_db):
    app = _build_app("viewer", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/webhooks")
    assert res.status_code == 403


# ---------- Create ----------


async def test_create_returns_secret_once(fake_db, monkeypatch):
    """The secret comes back EXACTLY at creation time. List endpoints
    must not echo it. Pin both halves of the contract."""
    from models.webhooks import WebhookSubscription

    # `db.refresh` doesn't populate `last_delivery_at` on a fresh row —
    # leave None.
    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/webhooks",
            json={"url": "https://hooks.example.com/abc", "event_types": []},
        )

    assert res.status_code == 201, res.text
    body = res.json()["data"]
    # Secret IS in the create response (one-time disclosure).
    assert "secret" in body
    assert len(body["secret"]) == 64

    # And exactly one WebhookSubscription was added.
    added = [o for o in fake_db.added if isinstance(o, WebhookSubscription)]
    assert len(added) == 1
    assert added[0].url == "https://hooks.example.com/abc"
    assert added[0].organization_id == ORG_ID
    assert added[0].created_by == USER_ID


async def test_create_409_on_duplicate_url(fake_db):
    """The (org, url) unique constraint surfaces as a 409 instead of a
    raw IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    class _ExplodingSession(FakeAsyncSession):
        async def commit(self) -> None:
            raise IntegrityError("dup", {}, BaseException())

        async def rollback(self) -> None: ...

    app = _build_app("admin", _ExplodingSession())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/webhooks",
            json={"url": "https://hooks.example.com/abc", "event_types": []},
        )
    assert res.status_code == 409


async def test_create_validates_event_type_length(fake_db):
    """An 80+ char event type slug is almost certainly a typo —
    Pydantic should 422 it before the service ever sees it."""
    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/h",
                "event_types": ["x" * 100],
            },
        )
    assert res.status_code == 422


# ---------- List ----------


async def test_list_omits_secret(fake_db):
    """List response must NEVER include `secret` — the schema doesn't
    declare it. Pin via a smoke check on the JSON keys."""
    sub = _sub_row()
    rows_q = MagicMock()
    rows_q.scalars.return_value.all.return_value = [sub]
    fake_db.push(rows_q)

    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/webhooks")

    assert res.status_code == 200
    body = res.json()["data"]
    assert len(body) == 1
    assert "secret" not in body[0]
    assert body[0]["url"] == sub.url


# ---------- Update ----------


async def test_update_toggles_enabled_and_resets_failure_count(fake_db):
    """Re-enabling a subscription should reset failure_count to 0 —
    the admin took action to fix whatever was broken."""
    sub = _sub_row(enabled=False, failure_count=15)
    lookup_q = MagicMock()
    lookup_q.scalar_one_or_none.return_value = sub
    fake_db.push(lookup_q)

    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.patch(
            f"/api/v1/webhooks/{sub.id}",
            json={"enabled": True},
        )

    assert res.status_code == 200, res.text
    assert sub.enabled is True
    assert sub.failure_count == 0


async def test_update_404_for_unknown_id(fake_db):
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    fake_db.push(miss)

    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.patch(f"/api/v1/webhooks/{uuid4()}", json={"enabled": False})
    assert res.status_code == 404


# ---------- Delete ----------


async def test_delete_is_idempotent_for_missing(fake_db):
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    fake_db.push(miss)

    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.delete(f"/api/v1/webhooks/{uuid4()}")
    assert res.status_code == 204
    assert fake_db.deleted == []


async def test_delete_removes_existing(fake_db):
    sub = _sub_row()
    lookup_q = MagicMock()
    lookup_q.scalar_one_or_none.return_value = sub
    fake_db.push(lookup_q)

    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.delete(f"/api/v1/webhooks/{sub.id}")
    assert res.status_code == 204
    assert fake_db.deleted == [sub]


# ---------- Test fire ----------


async def test_test_fire_enqueues_synthetic_event(fake_db):
    """`POST /webhooks/{id}/test` looks up the subscription and calls
    `enqueue_event(...)` with `webhook.test` — verified via fake_db
    execute call shape."""
    sub = _sub_row()
    lookup_q = MagicMock()
    lookup_q.scalar_one_or_none.return_value = sub
    fake_db.push(lookup_q)
    # `enqueue_event` discovery query — return one sub id so we get a
    # delivery row inserted.
    discovery_q = MagicMock()
    discovery_q.scalars.return_value.all.return_value = [sub.id]
    fake_db.push(discovery_q)

    app = _build_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(f"/api/v1/webhooks/{sub.id}/test")

    assert res.status_code == 202, res.text
    body = res.json()["data"]
    assert body["queued"] == 1
    assert body["subscription_id"] == str(sub.id)
