"""Router-level tests for /api/v1/siteeye/*.

The SiteEye router reaches into the DB via `TenantAwareSession(org_id)` as an
async context manager — NOT via `Depends(get_db)` — so the shared conftest's
DB override doesn't apply here. Instead we patch `routers.siteeye.TenantAwareSession`
with a `FakeTenantSession` that yields an in-memory session with programmable
`execute()` results. External side-effects (photo-analysis queue, weekly-report
pipeline, email transport) are mocked at their import site.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime, timezone
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.asyncio


PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")


# ---------- Fake TenantAwareSession ----------

class FakeAsyncSession:
    """Minimal AsyncSession stand-in. Router code only calls `.execute(stmt, params)`
    then chains `.mappings().one() / .all() / .first()` or `.scalar_one()`. We queue
    up prepared results per test."""

    def __init__(self) -> None:
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.scalar_one.return_value = 0
        r.mappings.return_value.all.return_value = []
        r.mappings.return_value.first.return_value = None
        r.mappings.return_value.one.side_effect = RuntimeError(
            "FakeAsyncSession: no execute() result queued for .mappings().one()"
        )
        return r


class FakeTenantSession:
    """Replaces `routers.siteeye.TenantAwareSession`. Acts as an async context
    manager that yields a shared `FakeAsyncSession` across all test invocations
    for a single test — which matches how the router reuses the session within
    one request (multiple `.execute()` calls inside one `async with`)."""

    # Set per-test by assigning `FakeTenantSession.session = FakeAsyncSession()`
    session: FakeAsyncSession | None = None

    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id

    async def __aenter__(self) -> FakeAsyncSession:
        assert FakeTenantSession.session is not None, (
            "test did not seed FakeTenantSession.session"
        )
        return FakeTenantSession.session

    async def __aexit__(self, *_exc: Any) -> None:
        return None


# ---------- App fixture (overrides codeguard-only conftest default) ----------

@pytest.fixture
def app(fake_auth, monkeypatch) -> Iterator[FastAPI]:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import require_auth
    from routers import siteeye as siteeye_router

    # Every test gets a fresh fake session — avoids cross-test queue pollution.
    FakeTenantSession.session = FakeAsyncSession()
    monkeypatch.setattr(siteeye_router, "TenantAwareSession", FakeTenantSession)

    test_app = FastAPI()
    test_app.add_exception_handler(HTTPException, http_exception_handler)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)
    test_app.include_router(siteeye_router.router)
    test_app.dependency_overrides[require_auth] = lambda: fake_auth
    try:
        yield test_app
    finally:
        test_app.dependency_overrides.clear()
        FakeTenantSession.session = None


@pytest.fixture
def fake_session() -> FakeAsyncSession:
    """Alias for the session the `app` fixture installs into the router. Tests
    push execute results onto it via `.push(...)`."""
    assert FakeTenantSession.session is not None
    return FakeTenantSession.session


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Row factories (match what the raw-SQL queries return) ----------

def _visit_row(**overrides: Any) -> dict:
    base = {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "visit_date": date(2026, 4, 22),
        "location": None,
        "reported_by": UUID("11111111-1111-1111-1111-111111111111"),
        "weather": "Clear, 28°C",
        "workers_count": 42,
        "notes": "L3 slab pour started.",
        "ai_summary": None,
        "photo_count": 0,
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


def _photo_row(**overrides: Any) -> dict:
    base = {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "site_visit_id": None,
        "file_id": uuid4(),
        "thumbnail_url": None,
        "taken_at": datetime.now(timezone.utc),
        "location": None,
        "tags": [],
        "ai_analysis": None,
        "safety_status": "clear",
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


def _incident_row(**overrides: Any) -> dict:
    base = {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "detected_at": datetime.now(timezone.utc),
        "incident_type": "no_ppe",
        "severity": "medium",
        "photo_id": None,
        "detection_box": None,
        "ai_description": "Worker without hard hat near crane operation.",
        "status": "open",
        "acknowledged_by": None,
        "resolved_at": None,
    }
    base.update(overrides)
    return base


def _report_row(**overrides: Any) -> dict:
    base = {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "week_start": date(2026, 4, 13),
        "week_end": date(2026, 4, 19),
        "content": None,
        "rendered_html": None,
        "pdf_url": None,
        "sent_to": [],
        "sent_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


def _mappings_one(row: dict) -> MagicMock:
    r = MagicMock()
    r.mappings.return_value.one.return_value = row
    return r


def _mappings_all(rows: list[dict]) -> MagicMock:
    r = MagicMock()
    r.mappings.return_value.all.return_value = rows
    return r


def _mappings_first(row: dict | None) -> MagicMock:
    r = MagicMock()
    r.mappings.return_value.first.return_value = row
    return r


def _scalar(value: Any) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


# ============================================================
# Visits
# ============================================================

async def test_create_visit_returns_201_with_row(client, fake_session, fake_auth):
    row = _visit_row()
    fake_session.push(_mappings_one(row))

    res = await client.post(
        "/api/v1/siteeye/visits",
        json={
            "project_id": str(PROJECT_ID),
            "visit_date": "2026-04-22",
            "weather": "Clear, 28°C",
            "workers_count": 42,
            "notes": "L3 slab pour started.",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()["data"]
    assert body["id"] == str(row["id"])
    assert body["workers_count"] == 42
    assert body["photo_count"] == 0


async def test_list_visits_paginates_with_count_and_rows(client, fake_session):
    rows = [_visit_row() for _ in range(2)]
    # list-query first, then count-query
    fake_session.push(_mappings_all(rows))
    fake_session.push(_scalar(7))

    res = await client.get(
        "/api/v1/siteeye/visits",
        params={"project_id": str(PROJECT_ID), "limit": 20, "offset": 0},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["data"]) == 2
    assert body["meta"]["total"] == 7
    assert body["meta"]["page"] == 1
    assert body["meta"]["per_page"] == 20


# ============================================================
# Photos
# ============================================================

async def test_upload_photos_persists_each_and_enqueues_job(
    client, fake_session, fake_auth, monkeypatch
):
    """Router loops N INSERTs inside one session, then calls `enqueue_photo_analysis`."""
    # 3 photos → 3 execute() calls inside the loop. Fake session happily returns
    # the default MagicMock for each since the router doesn't consume their result.
    enqueue = AsyncMock(return_value=uuid4())
    monkeypatch.setattr("workers.queue.enqueue_photo_analysis", enqueue)

    res = await client.post(
        "/api/v1/siteeye/photos/upload",
        json={
            "project_id": str(PROJECT_ID),
            "photos": [
                {"file_id": str(uuid4()), "taken_at": "2026-04-22T09:15:00Z"},
                {"file_id": str(uuid4()), "taken_at": "2026-04-22T09:16:00Z"},
                {"file_id": str(uuid4()), "taken_at": "2026-04-22T09:17:00Z"},
            ],
        },
    )
    assert res.status_code == 202, res.text
    body = res.json()["data"]
    assert body["accepted"] == 3
    assert len(body["photo_ids"]) == 3

    enqueue.assert_awaited_once()
    kwargs = enqueue.await_args.kwargs
    assert kwargs["organization_id"] == fake_auth.organization_id
    assert kwargs["project_id"] == PROJECT_ID
    assert len(kwargs["photo_ids"]) == 3


async def test_upload_photos_rejects_empty_batch(client):
    res = await client.post(
        "/api/v1/siteeye/photos/upload",
        json={"project_id": str(PROJECT_ID), "photos": []},
    )
    assert res.status_code == 422


async def test_list_photos_returns_paginated_envelope(client, fake_session):
    rows = [_photo_row() for _ in range(3)]
    fake_session.push(_mappings_all(rows))
    fake_session.push(_scalar(3))

    res = await client.get(
        "/api/v1/siteeye/photos",
        params={"project_id": str(PROJECT_ID), "limit": 30, "offset": 0},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["data"]) == 3
    assert body["meta"]["total"] == 3


# ============================================================
# Progress
# ============================================================

async def test_progress_timeline_infers_ahead_when_delta_ge_3(client, fake_session):
    t0 = {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "snapshot_date": date(2026, 4, 8),
        "overall_progress_pct": 40.0,
        "phase_progress": {"structure": 50.0},
        "ai_notes": None,
        "photo_ids": [],
        "created_at": datetime.now(timezone.utc),
    }
    t1 = {**t0, "id": uuid4(), "snapshot_date": date(2026, 4, 15),
          "overall_progress_pct": 44.0}
    fake_session.push(_mappings_all([t0, t1]))

    res = await client.get(
        "/api/v1/siteeye/progress",
        params={"project_id": str(PROJECT_ID)},
    )
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["schedule_status"] == "ahead"  # delta 4 >= 3
    assert len(body["snapshots"]) == 2


async def test_progress_timeline_unknown_with_single_snapshot(client, fake_session):
    snap = {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "snapshot_date": date(2026, 4, 15),
        "overall_progress_pct": 44.0,
        "phase_progress": {},
        "ai_notes": None,
        "photo_ids": [],
        "created_at": datetime.now(timezone.utc),
    }
    fake_session.push(_mappings_all([snap]))

    res = await client.get(
        "/api/v1/siteeye/progress",
        params={"project_id": str(PROJECT_ID)},
    )
    assert res.status_code == 200
    assert res.json()["data"]["schedule_status"] == "unknown"


# ============================================================
# Safety incidents
# ============================================================

async def test_list_safety_incidents_respects_filters(client, fake_session):
    rows = [_incident_row(severity="high", status="open") for _ in range(2)]
    fake_session.push(_mappings_all(rows))
    fake_session.push(_scalar(2))

    res = await client.get(
        "/api/v1/siteeye/safety-incidents",
        params={"status": "open", "severity": "high"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["total"] == 2
    for row in body["data"]:
        assert row["severity"] == "high"
        assert row["status"] == "open"


async def test_acknowledge_incident_marks_resolved(client, fake_session, fake_auth):
    incident_id = uuid4()
    row = _incident_row(
        id=incident_id,
        status="resolved",
        acknowledged_by=fake_auth.user_id,
        resolved_at=datetime.now(timezone.utc),
    )
    fake_session.push(_mappings_first(row))

    res = await client.patch(
        f"/api/v1/siteeye/safety-incidents/{incident_id}/ack",
        json={"resolve": True, "notes": "PPE supplied + crew briefed"},
    )
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["status"] == "resolved"
    assert body["id"] == str(incident_id)


async def test_acknowledge_incident_404_when_missing(client, fake_session):
    fake_session.push(_mappings_first(None))

    res = await client.patch(
        f"/api/v1/siteeye/safety-incidents/{uuid4()}/ack",
        json={"resolve": False},
    )
    assert res.status_code == 404


# ============================================================
# Weekly reports
# ============================================================

async def test_generate_report_rejects_end_before_start(client):
    res = await client.post(
        "/api/v1/siteeye/reports/generate",
        json={
            "project_id": str(PROJECT_ID),
            "week_start": "2026-04-19",
            "week_end": "2026-04-13",
        },
    )
    assert res.status_code == 400
    assert "week_end" in res.json()["errors"][0]["message"]


async def test_generate_report_delegates_to_pipeline(
    client, fake_auth, monkeypatch
):
    """`from apps.ml.pipelines.siteeye import generate_weekly_report` is lazy —
    stub the module in sys.modules so the import inside the handler hits our fake."""
    import sys

    report_id = uuid4()
    from schemas.siteeye import WeeklyReport

    report = WeeklyReport.model_validate({
        "id": report_id,
        "project_id": PROJECT_ID,
        "week_start": date(2026, 4, 13),
        "week_end": date(2026, 4, 19),
        "content": None,
        "rendered_html": None,
        "pdf_url": None,
        "sent_to": [],
        "sent_at": None,
        "created_at": datetime.now(timezone.utc),
    })

    generate = AsyncMock(return_value=report)

    fake_mod = ModuleType("apps.ml.pipelines.siteeye")
    fake_mod.generate_weekly_report = generate
    monkeypatch.setitem(sys.modules, "apps.ml.pipelines.siteeye", fake_mod)

    res = await client.post(
        "/api/v1/siteeye/reports/generate",
        json={
            "project_id": str(PROJECT_ID),
            "week_start": "2026-04-13",
            "week_end": "2026-04-19",
        },
    )
    assert res.status_code == 202, res.text
    assert res.json()["data"]["id"] == str(report_id)

    generate.assert_awaited_once_with(
        organization_id=fake_auth.organization_id,
        project_id=PROJECT_ID,
        week_start=date(2026, 4, 13),
        week_end=date(2026, 4, 19),
    )


async def test_list_reports_returns_paginated_envelope(client, fake_session):
    rows = [_report_row() for _ in range(2)]
    fake_session.push(_mappings_all(rows))
    fake_session.push(_scalar(2))

    res = await client.get(
        "/api/v1/siteeye/reports",
        params={"project_id": str(PROJECT_ID)},
    )
    assert res.status_code == 200
    assert len(res.json()["data"]) == 2
    assert res.json()["meta"]["total"] == 2


async def test_send_report_delegates_and_returns_envelope(
    client, fake_auth, monkeypatch
):
    import sys

    report_id = uuid4()
    email_fn = AsyncMock(return_value=True)

    fake_mod = ModuleType("apps.ml.pipelines.siteeye")
    fake_mod.email_weekly_report = email_fn
    monkeypatch.setitem(sys.modules, "apps.ml.pipelines.siteeye", fake_mod)

    res = await client.post(
        f"/api/v1/siteeye/reports/{report_id}/send",
        json={"recipients": ["pm@example.com", "owner@example.com"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["report_id"] == str(report_id)
    assert "pm@example.com" in body["sent_to"]

    email_fn.assert_awaited_once()
    kwargs = email_fn.await_args.kwargs
    assert kwargs["organization_id"] == fake_auth.organization_id
    assert kwargs["report_id"] == report_id
    assert kwargs["recipients"] == ["pm@example.com", "owner@example.com"]


async def test_send_report_404_when_pipeline_returns_false(
    client, monkeypatch
):
    import sys

    fake_mod = ModuleType("apps.ml.pipelines.siteeye")
    fake_mod.email_weekly_report = AsyncMock(return_value=False)
    monkeypatch.setitem(sys.modules, "apps.ml.pipelines.siteeye", fake_mod)

    res = await client.post(
        f"/api/v1/siteeye/reports/{uuid4()}/send",
        json={"recipients": ["pm@example.com"]},
    )
    assert res.status_code == 404
