"""Router tests for /api/v1/punchlist/*. Same pattern as schedulepilot."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")


def _make_row(**fields: Any) -> SimpleNamespace:
    return SimpleNamespace(_mapping=fields)


def _result(row: SimpleNamespace | None = None, rows: list | None = None) -> MagicMock:
    r = MagicMock()
    r.one.return_value = row
    r.one_or_none.return_value = row
    r.first.return_value = row
    r.all.return_value = rows or ([row] if row is not None else [])
    r.rowcount = 1 if row is not None else 0
    return r


def _scalar(v: Any) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = v
    r.scalar_one_or_none.return_value = v
    return r


class _ProgrammableSession:
    def __init__(self) -> None:
        self._queue: list[Any] = []

    def queue(self, result: Any) -> _ProgrammableSession:
        self._queue.append(result)
        return self

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        if self._queue:
            return self._queue.pop(0)
        r = MagicMock()
        r.one.side_effect = AssertionError("unprogrammed .one()")
        r.one_or_none.return_value = None
        r.all.return_value = []
        r.scalar_one.return_value = 0
        r.rowcount = 0
        return r

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


@pytest.fixture
def patch_session(monkeypatch):
    s = _ProgrammableSession()

    class _Fake:
        def __init__(self, _o: Any) -> None: ...
        async def __aenter__(self):
            return s

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr("routers.punchlist.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import punchlist as router_mod

    auth = AuthContext(user_id=USER_ID, organization_id=ORG_ID, role="admin", email="t@example.com")
    a = FastAPI()
    a.add_exception_handler(HTTPException, http_exception_handler)
    a.add_exception_handler(Exception, unhandled_exception_handler)
    a.include_router(router_mod.router)
    a.dependency_overrides[require_auth] = lambda: auth
    return a


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _list_row(**overrides: Any) -> SimpleNamespace:
    base = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        name="Owner walkthrough — final",
        walkthrough_date=date(2026, 5, 1),
        status="open",
        owner_attendees="Owner, GC, Architect",
        notes=None,
        signed_off_at=None,
        signed_off_by=None,
        created_by=USER_ID,
        created_at=datetime(2026, 5, 1, 9, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, 9, tzinfo=UTC),
        total_items=0,
        open_items=0,
        fixed_items=0,
        verified_items=0,
    )
    base.update(overrides)
    return _make_row(**base)


def _item_row(**overrides: Any) -> SimpleNamespace:
    list_id = overrides.pop("list_id", uuid4())
    base = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        list_id=list_id,
        item_number=1,
        description="Paint scuff in lobby",
        location="Lobby / Floor 1",
        trade="architectural",
        severity="medium",
        status="open",
        photo_id=None,
        assigned_user_id=None,
        due_date=None,
        fixed_at=None,
        verified_at=None,
        verified_by=None,
        notes=None,
        created_at=datetime(2026, 5, 1, 9, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, 9, tzinfo=UTC),
    )
    base.update(overrides)
    return _make_row(**base)


# =============================================================================
# Tests
# =============================================================================


async def test_create_list_returns_201_envelope(client, patch_session):
    patch_session.queue(_result(_list_row(name="Pre-occupancy walkthrough")))

    resp = await client.post(
        "/api/v1/punchlist/lists",
        json={
            "project_id": str(PROJECT_ID),
            "name": "Pre-occupancy walkthrough",
            "walkthrough_date": "2026-05-01",
            "owner_attendees": "Owner, GC, Architect",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["name"] == "Pre-occupancy walkthrough"
    assert body["status"] == "open"


async def test_get_list_404_when_missing(client, patch_session):
    patch_session.queue(_result(None))

    resp = await client.get(f"/api/v1/punchlist/lists/{uuid4()}")
    assert resp.status_code == 404


async def test_add_item_auto_numbers_per_list(client, patch_session):
    list_id = uuid4()
    # 1: SELECT MAX(item_number) → 5; 2: INSERT item RETURNING with item_number=6
    patch_session.queue(_scalar(6))
    patch_session.queue(
        _result(
            _item_row(
                list_id=list_id,
                item_number=6,
                description="Outlet B-103 dead",
                trade="mep",
                severity="high",
            )
        )
    )

    resp = await client.post(
        f"/api/v1/punchlist/lists/{list_id}/items",
        json={
            "description": "Outlet B-103 dead",
            "location": "Suite B / Floor 1",
            "trade": "mep",
            "severity": "high",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["item_number"] == 6
    assert body["trade"] == "mep"
    assert body["severity"] == "high"


async def test_update_item_to_verified_stamps_verified_at_and_by(client, patch_session):
    """Setting status='verified' must stamp verified_at + verified_by atomically."""
    iid = uuid4()
    patch_session.queue(
        _result(
            _item_row(
                id=iid,
                status="verified",
                verified_at=datetime(2026, 5, 5, 10, tzinfo=UTC),
                verified_by=USER_ID,
            )
        )
    )

    resp = await client.patch(
        f"/api/v1/punchlist/items/{iid}",
        json={"status": "verified"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["status"] == "verified"
    assert body["verified_by"] == str(USER_ID)


async def test_sign_off_blocked_when_items_unfinished(client, patch_session):
    """Owner sign-off must 409 if any item is still open/in_progress/fixed —
    only verified or waived items count as 'done'."""
    list_id = uuid4()
    # COUNT(*) WHERE status NOT IN ('verified', 'waived') → 3 unfinished
    patch_session.queue(_scalar(3))

    resp = await client.post(f"/api/v1/punchlist/lists/{list_id}/sign-off", json={"notes": "All clear"})
    assert resp.status_code == 409
    assert "unfinished" in resp.json()["errors"][0]["message"].lower()


async def test_sign_off_succeeds_when_all_items_verified(client, patch_session):
    list_id = uuid4()
    # 1: COUNT unfinished → 0; 2: UPDATE list RETURNING signed_off
    patch_session.queue(_scalar(0))
    patch_session.queue(
        _result(
            _list_row(
                id=list_id,
                status="signed_off",
                signed_off_at=datetime(2026, 5, 10, 14, tzinfo=UTC),
                signed_off_by=USER_ID,
            )
        )
    )

    resp = await client.post(
        f"/api/v1/punchlist/lists/{list_id}/sign-off",
        json={"notes": "Owner accepted, no remaining issues"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["status"] == "signed_off"
    assert body["signed_off_by"] == str(USER_ID)


async def test_delete_item_404_when_missing(client, patch_session):
    # rowcount=0 on the default branch
    resp = await client.delete(f"/api/v1/punchlist/items/{uuid4()}")
    assert resp.status_code == 404


async def test_photo_hints_returns_same_day_photos(client, patch_session):
    """Same-day SiteEye photos surface as attach candidates without
    triggering the broader-window fallback query."""
    list_id = uuid4()
    photo_id = uuid4()
    file_id = uuid4()
    # 1: SELECT list project_id + walkthrough_date
    patch_session.queue(_result(_make_row(project_id=PROJECT_ID, walkthrough_date=date(2026, 5, 1))))
    # 2: SELECT site_photos same-day → 1 row → no fallback
    patch_session.queue(
        _result(
            _make_row(
                photo_id=photo_id,
                file_id=file_id,
                taken_at=datetime(2026, 5, 1, 10, 30, tzinfo=UTC),
                thumbnail_url="https://cdn.test/thumbs/lobby.jpg",
                safety_status="clear",
                tags=["lobby", "paint"],
            )
        )
    )

    resp = await client.get(f"/api/v1/punchlist/lists/{list_id}/photo-hints")
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["walkthrough_date"] == "2026-05-01"
    assert body["window_days"] == 2  # default
    assert len(body["results"]) == 1
    hint = body["results"][0]
    assert hint["photo_id"] == str(photo_id)
    assert hint["thumbnail_url"].endswith("lobby.jpg")
    assert hint["tags"] == ["lobby", "paint"]


async def test_photo_hints_404_when_list_missing(client, patch_session):
    patch_session.queue(_result(None))
    resp = await client.get(f"/api/v1/punchlist/lists/{uuid4()}/photo-hints")
    assert resp.status_code == 404
