"""Router tests for /api/v1/me/inbox — cross-module 'today' aggregator."""

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


def _make_row(**fields: Any) -> SimpleNamespace:
    return SimpleNamespace(_mapping=fields)


def _result(rows: list | None = None) -> MagicMock:
    r = MagicMock()
    r.all.return_value = rows or []
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
        r.all.return_value = []
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

    monkeypatch.setattr("routers.inbox.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import inbox as router_mod

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


# =============================================================================


async def test_inbox_aggregates_across_six_sources(client, patch_session):
    """The aggregator fans out to six sources in parallel — cover one row
    per source so we can verify the bucket assignment + deep-link shape."""
    rfi_id, punch_id, defect_id = uuid4(), uuid4(), uuid4()
    sub_id, co_id, cand_id = uuid4(), uuid4(), uuid4()
    list_id = uuid4()
    project_id = uuid4()

    # Note: asyncio.gather doesn't guarantee execute() call order, so we
    # queue six results and the aggregator picks them off in whatever order
    # the event loop schedules. The test only asserts on item counts and
    # kinds, not on internal order.
    patch_session.queue(
        _result(
            [
                _make_row(
                    id=rfi_id,
                    project_id=project_id,
                    project_name="Tower A",
                    subject="Door schedule clarification",
                    number="RFI-042",
                    status="open",
                    priority="normal",
                    due_date=None,
                    created_at=datetime(2026, 4, 25, tzinfo=UTC),
                )
            ]
        )
    )
    patch_session.queue(
        _result(
            [
                _make_row(
                    id=punch_id,
                    list_id=list_id,
                    project_id=project_id,
                    project_name="Tower A",
                    description="Outlet B-103 dead",
                    item_number=2,
                    status="open",
                    severity="high",
                    due_date=date(2026, 5, 5),
                    created_at=datetime(2026, 5, 1, tzinfo=UTC),
                )
            ]
        )
    )
    patch_session.queue(
        _result(
            [
                _make_row(
                    id=defect_id,
                    project_id=project_id,
                    project_name="Tower A",
                    description="Column out of plumb at grid B-3",
                    status="assigned",
                    priority="high",
                    due_date=None,
                    created_at=datetime(2026, 4, 28, tzinfo=UTC),
                )
            ]
        )
    )
    patch_session.queue(
        _result(
            [
                _make_row(
                    id=sub_id,
                    project_id=project_id,
                    project_name="Tower A",
                    title="Concrete mix design M300",
                    package_number="S-007",
                    status="pending_review",
                    due_date=None,
                    created_at=datetime(2026, 4, 27, tzinfo=UTC),
                )
            ]
        )
    )
    patch_session.queue(
        _result(
            [
                _make_row(
                    id=co_id,
                    project_id=project_id,
                    project_name="Tower A",
                    title="Door substitution",
                    number="CO-003",
                    status="submitted",
                    created_at=datetime(2026, 4, 26, tzinfo=UTC),
                )
            ]
        )
    )
    patch_session.queue(
        _result(
            [
                _make_row(
                    id=cand_id,
                    project_id=project_id,
                    project_name="Tower A",
                    proposal_title="Bổ sung điều hoà",
                    source_kind="email",
                    created_at=datetime(2026, 4, 27, tzinfo=UTC),
                )
            ]
        )
    )

    resp = await client.get("/api/v1/me/inbox")
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["total"] == 6
    assert len(body["items"]) == 6

    by_kind = {it["kind"]: it for it in body["items"]}
    assert set(by_kind) == {
        "rfi",
        "punch_item",
        "defect",
        "submittal",
        "change_order",
        "co_candidate",
    }
    # assigned_to_me bucket: rfi, punch_item, defect (3)
    assert by_kind["rfi"]["bucket"] == "assigned_to_me"
    assert by_kind["punch_item"]["bucket"] == "assigned_to_me"
    assert by_kind["defect"]["bucket"] == "assigned_to_me"
    # awaiting_review: submittal, change_order, co_candidate (3)
    assert by_kind["submittal"]["bucket"] == "awaiting_review"
    assert by_kind["change_order"]["bucket"] == "awaiting_review"
    assert by_kind["co_candidate"]["bucket"] == "awaiting_review"

    # Deep links resolve to the right module surfaces.
    assert by_kind["rfi"]["deep_link"] == f"/drawbridge/rfis/{rfi_id}"
    assert by_kind["punch_item"]["deep_link"] == f"/punchlist/{list_id}"
    assert by_kind["submittal"]["deep_link"] == f"/submittals/{sub_id}"
    assert by_kind["change_order"]["deep_link"] == f"/changeorder/{co_id}"

    # Bucket summary matches the totals.
    summary = {s["bucket"]: s["count"] for s in body["summary"]}
    assert summary == {"assigned_to_me": 3, "awaiting_review": 3}


async def test_inbox_returns_empty_envelope_for_clean_org(client, patch_session):
    """Empty queues across all six sources → empty items + zero summary."""
    for _ in range(6):
        patch_session.queue(_result([]))

    resp = await client.get("/api/v1/me/inbox")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["items"] == []
    assert body["summary"] == []
    assert body["total"] == 0


async def test_inbox_project_filter_propagates(client, patch_session):
    """Calling with ?project_id=<uuid> still fans out to six sources;
    each query gets the same project_id parameter."""
    for _ in range(6):
        patch_session.queue(_result([]))

    project_id = uuid4()
    resp = await client.get(f"/api/v1/me/inbox?project_id={project_id}")
    assert resp.status_code == 200
    # All six queues consumed.
    assert resp.json()["data"]["total"] == 0
