"""Router tests for /api/v1/notifications/watches CRUD."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
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

    async def refresh(self, obj: Any) -> None:
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime.now(UTC)

    async def execute(self, *_a: Any, **_kw: Any) -> Any:
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.all.return_value = []
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
    from routers import notifications as notif_router

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="tester@example.com",
    )

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(notif_router.router)

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


def _project_row():
    return SimpleNamespace(
        id=uuid4(),
        organization_id=ORG_ID,
        name="Tower A",
        type="commercial",
        status="active",
    )


# ---------- List ----------


async def test_list_watches_returns_user_subscriptions(client, fake_db):
    watch_id = uuid4()
    project_id = uuid4()
    row = SimpleNamespace(
        id=watch_id,
        project_id=project_id,
        created_at=datetime.now(UTC),
        project_name="Tower A",
    )
    q = MagicMock()
    q.all.return_value = [row]
    fake_db.push(q)

    res = await client.get("/api/v1/notifications/watches")

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert len(data) == 1
    assert data[0]["watch_id"] == str(watch_id)
    assert data[0]["project_id"] == str(project_id)
    assert data[0]["project_name"] == "Tower A"


async def test_list_watches_empty(client, fake_db):
    q = MagicMock()
    q.all.return_value = []
    fake_db.push(q)

    res = await client.get("/api/v1/notifications/watches")

    assert res.status_code == 200
    assert res.json()["data"] == []


# ---------- Create ----------


async def test_create_watch_creates_new_row(client, fake_db):
    from models.core import ProjectWatch

    project = _project_row()
    project_q = MagicMock()
    project_q.scalar_one_or_none.return_value = project
    existing_q = MagicMock()
    existing_q.scalar_one_or_none.return_value = None
    fake_db.push(project_q)
    fake_db.push(existing_q)

    res = await client.post(
        "/api/v1/notifications/watches",
        json={"project_id": str(project.id)},
    )

    assert res.status_code == 201, res.text
    added = [o for o in fake_db.added if isinstance(o, ProjectWatch)]
    assert len(added) == 1
    assert added[0].user_id == USER_ID
    assert added[0].organization_id == ORG_ID
    assert added[0].project_id == project.id


async def test_create_watch_is_idempotent_when_already_watching(client, fake_db):
    """Re-watching returns the existing row, doesn't create a duplicate."""
    from models.core import ProjectWatch

    project = _project_row()
    existing = SimpleNamespace(
        id=uuid4(),
        organization_id=ORG_ID,
        user_id=USER_ID,
        project_id=project.id,
        created_at=datetime.now(UTC),
    )
    project_q = MagicMock()
    project_q.scalar_one_or_none.return_value = project
    existing_q = MagicMock()
    existing_q.scalar_one_or_none.return_value = existing
    fake_db.push(project_q)
    fake_db.push(existing_q)

    res = await client.post(
        "/api/v1/notifications/watches",
        json={"project_id": str(project.id)},
    )

    assert res.status_code == 201, res.text
    body = res.json()["data"]
    assert body["id"] == str(existing.id)
    # No new row added.
    assert not any(isinstance(o, ProjectWatch) for o in fake_db.added)


async def test_create_watch_404_for_unknown_project(client, fake_db):
    """Cross-tenant project (not in caller's org) → clean 404, not RLS error."""
    from models.core import ProjectWatch

    project_q = MagicMock()

    project_q.scalar_one_or_none.return_value = None
    fake_db.push(project_q)

    res = await client.post(
        "/api/v1/notifications/watches",
        json={"project_id": str(uuid4())},
    )

    assert res.status_code == 404
    assert not any(isinstance(o, ProjectWatch) for o in fake_db.added)


# ---------- Delete ----------


async def test_delete_watch_removes_existing(client, fake_db):
    watch = SimpleNamespace(
        id=uuid4(),
        organization_id=ORG_ID,
        user_id=USER_ID,
        project_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    q = MagicMock()
    q.scalar_one_or_none.return_value = watch
    fake_db.push(q)

    res = await client.delete(f"/api/v1/notifications/watches/{watch.project_id}")

    assert res.status_code == 204
    assert fake_db.deleted == [watch]


async def test_delete_watch_is_idempotent_for_missing(client, fake_db):
    """Deleting a non-existent watch is a 204 — desired end state achieved."""
    q = MagicMock()
    q.scalar_one_or_none.return_value = None
    fake_db.push(q)

    res = await client.delete(f"/api/v1/notifications/watches/{uuid4()}")

    assert res.status_code == 204
    assert fake_db.deleted == []


# ---------- Notification preferences ----------


async def test_list_preferences_prefills_known_keys_with_off_defaults(client, fake_db):
    """Empty DB → response still has every known alert kind, all off."""
    q = MagicMock()
    q.scalars.return_value.all.return_value = []
    fake_db.push(q)

    res = await client.get("/api/v1/notifications/preferences")

    assert res.status_code == 200
    data = res.json()["data"]
    keys = [r["key"] for r in data]
    # Same set + ordering as `_KNOWN_PREF_KEYS` in the router.
    assert keys == ["scraper_drift", "rfq_deadline_summary", "weekly_digest_email"]
    assert all(r["email_enabled"] is False for r in data)
    assert all(r["slack_enabled"] is False for r in data)


async def test_list_preferences_overlays_persisted_rows_on_defaults(client, fake_db):
    """DB rows for known keys override the prefilled defaults."""
    persisted = SimpleNamespace(
        id=uuid4(),
        user_id=USER_ID,
        organization_id=ORG_ID,
        key="scraper_drift",
        email_enabled=True,
        slack_enabled=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    q = MagicMock()
    q.scalars.return_value.all.return_value = [persisted]
    fake_db.push(q)

    res = await client.get("/api/v1/notifications/preferences")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    drift = next(r for r in data if r["key"] == "scraper_drift")
    assert drift["email_enabled"] is True
    other = next(r for r in data if r["key"] == "rfq_deadline_summary")
    assert other["email_enabled"] is False


async def test_list_preferences_surfaces_unknown_keys_user_already_set(client, fake_db):
    """If `_KNOWN_PREF_KEYS` shrinks, the user's existing rows still
    appear in the list — their preference doesn't silently vanish."""
    extra = SimpleNamespace(
        id=uuid4(),
        user_id=USER_ID,
        organization_id=ORG_ID,
        key="legacy_alert_kind",
        email_enabled=True,
        slack_enabled=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    q = MagicMock()
    q.scalars.return_value.all.return_value = [extra]
    fake_db.push(q)

    res = await client.get("/api/v1/notifications/preferences")
    keys = [r["key"] for r in res.json()["data"]]
    assert "legacy_alert_kind" in keys


async def test_upsert_preference_inserts_when_no_row_yet(client, fake_db):
    """First touch on a key creates the row with the requested flags."""
    from models.core import NotificationPreference

    q = MagicMock()
    q.scalar_one_or_none.return_value = None
    fake_db.push(q)

    res = await client.put(
        "/api/v1/notifications/preferences/scraper_drift",
        json={"email_enabled": True},
    )
    assert res.status_code == 200, res.text

    inserted = [o for o in fake_db.added if isinstance(o, NotificationPreference)]
    assert len(inserted) == 1
    row = inserted[0]
    assert row.key == "scraper_drift"
    assert row.email_enabled is True
    # `slack_enabled` defaults to False when not provided.
    assert row.slack_enabled is False


async def test_upsert_preference_partial_update_leaves_other_flag_alone(client, fake_db):
    """PUT with only email_enabled must NOT clobber slack_enabled."""
    existing = SimpleNamespace(
        id=uuid4(),
        user_id=USER_ID,
        organization_id=ORG_ID,
        key="scraper_drift",
        email_enabled=False,
        slack_enabled=True,  # ← previously enabled
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    q = MagicMock()
    q.scalar_one_or_none.return_value = existing
    fake_db.push(q)

    res = await client.put(
        "/api/v1/notifications/preferences/scraper_drift",
        json={"email_enabled": True},
    )
    assert res.status_code == 200
    assert existing.email_enabled is True
    assert existing.slack_enabled is True


async def test_upsert_preference_400_for_oversized_key(client, fake_db):
    res = await client.put(
        "/api/v1/notifications/preferences/" + "x" * 200,
        json={"email_enabled": True},
    )
    assert res.status_code == 400
