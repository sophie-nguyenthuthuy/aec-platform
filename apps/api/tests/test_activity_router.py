"""Router tests for /api/v1/activity (cross-project event feed).

The router fires two raw-SQL statements per request:
  1. The UNION-ALL feed query (`_FEED_SQL`) — returns the ordered events.
  2. A counterpart count query (`_COUNT_SQL`) — drives `meta.total`.

We assert: (a) both queries get caller's org_id parameter-bound (no leakage
across tenants); (b) the response shape envelopes the rows correctly; (c)
filters (project_id, module, since_days) flow through to bound params.
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

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
    """Records execute() params; returns programmable results."""

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
        r.mappings.return_value.all.return_value = []
        r.scalar_one.return_value = 0
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture
def app(fake_db) -> FastAPI:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from middleware.auth import AuthContext, require_auth
    from routers import activity as activity_router

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="tester@example.com",
    )

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(activity_router.router)

    async def _db_override() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[get_db] = _db_override
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _event_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": uuid4(),
        "project_id": uuid4(),
        "project_name": "Tower A",
        "module": "pulse",
        "event_type": "change_order_created",
        "title": "CO #CO-001 — Slab thickness change",
        "description": "Designer-initiated revision",
        "timestamp": datetime(2026, 4, 24, 12, 30, tzinfo=UTC),
        "actor_id": USER_ID,
        "metadata": {"status": "draft", "initiator": "designer"},
    }
    base.update(overrides)
    return base


# ---------- Happy path ----------


async def test_activity_feed_returns_events_in_envelope(client, fake_db):
    rows = [
        _event_row(),
        _event_row(
            module="siteeye",
            event_type="safety_incident_detected",
            title="Safety incident: no_ppe",
        ),
    ]
    feed_q = MagicMock()
    feed_q.mappings.return_value.all.return_value = rows
    count_q = MagicMock()
    count_q.scalar_one.return_value = 2
    fake_db.push(feed_q)
    fake_db.push(count_q)

    res = await client.get("/api/v1/activity")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 2
    first = body["data"][0]
    assert first["module"] == "pulse"
    assert first["event_type"] == "change_order_created"
    assert first["project_name"] == "Tower A"
    assert first["metadata"]["initiator"] == "designer"


async def test_activity_feed_empty_returns_empty_envelope(client, fake_db):
    feed_q = MagicMock()
    feed_q.mappings.return_value.all.return_value = []
    count_q = MagicMock()
    count_q.scalar_one.return_value = 0
    fake_db.push(feed_q)
    fake_db.push(count_q)

    res = await client.get("/api/v1/activity")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


# ---------- Tenant scoping ----------


async def test_activity_feed_passes_caller_org_to_query(client, fake_db):
    feed_q = MagicMock()
    feed_q.mappings.return_value.all.return_value = []
    count_q = MagicMock()
    count_q.scalar_one.return_value = 0
    fake_db.push(feed_q)
    fake_db.push(count_q)

    await client.get("/api/v1/activity")

    # Both queries (feed + count) should bind caller's org_id — never the
    # filter's project_id alone, never a static literal.
    assert len(fake_db.calls) == 2
    for _stmt, params in fake_db.calls:
        assert params["org_id"] == str(ORG_ID), f"query bound org_id={params.get('org_id')!r}, expected {ORG_ID!r}"


# ---------- Filters ----------


async def test_activity_feed_threads_filters_into_params(client, fake_db):
    feed_q = MagicMock()
    feed_q.mappings.return_value.all.return_value = []
    count_q = MagicMock()
    count_q.scalar_one.return_value = 0
    fake_db.push(feed_q)
    fake_db.push(count_q)

    project_id = uuid4()
    res = await client.get(
        "/api/v1/activity",
        params={
            "project_id": str(project_id),
            "module": "handover",
            "since_days": 7,
            "limit": 10,
            "offset": 20,
        },
    )

    assert res.status_code == 200
    feed_params = fake_db.calls[0][1]
    assert feed_params["project_id"] == str(project_id)
    assert feed_params["module"] == "handover"
    assert feed_params["limit"] == 10
    assert feed_params["offset"] == 20
    # `since` is computed server-side from since_days; just verify it's set.
    assert feed_params["since"] is not None


async def test_activity_feed_defaults_to_30_day_window(client, fake_db):
    feed_q = MagicMock()
    feed_q.mappings.return_value.all.return_value = []
    count_q = MagicMock()
    count_q.scalar_one.return_value = 0
    fake_db.push(feed_q)
    fake_db.push(count_q)

    before = datetime.now(UTC)
    await client.get("/api/v1/activity")
    after = datetime.now(UTC)

    feed_params = fake_db.calls[0][1]
    since: datetime = feed_params["since"]
    delta = before - since
    # ~30 days. Allow a wide latitude (29.5 → 30.5) for clock drift.
    assert 29.5 < delta.total_seconds() / 86400 < 30.5
    assert since < before
    assert since < after


async def test_activity_feed_rejects_out_of_range_since_days(client, fake_db):
    res = await client.get("/api/v1/activity", params={"since_days": 0})
    assert res.status_code == 422
    res = await client.get("/api/v1/activity", params={"since_days": 366})
    assert res.status_code == 422


async def test_activity_feed_rejects_out_of_range_limit(client, fake_db):
    res = await client.get("/api/v1/activity", params={"limit": 0})
    assert res.status_code == 422
    res = await client.get("/api/v1/activity", params={"limit": 201})
    assert res.status_code == 422


async def test_activity_feed_rejects_unknown_module(client, fake_db):
    """`module` is constrained to the ActivityModule enum."""
    res = await client.get("/api/v1/activity", params={"module": "not_a_module"})
    assert res.status_code == 422
