"""Router tests for /api/v1/dailylog/*. Same pattern as schedulepilot."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
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

    monkeypatch.setattr("routers.dailylog.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def patch_pipeline(monkeypatch):
    mod = ModuleType("ml.pipelines.dailylog")
    mod.extract_observations = AsyncMock(
        return_value=[
            {
                "kind": "risk",
                "severity": "high",
                "description": "Mưa to làm chậm đổ bê tông tầng 3",
                "source": "llm_extracted",
                "rationale": "weather.precipitation_mm = 25",
            }
        ]
    )
    mod.aggregate_patterns = MagicMock(
        return_value={
            "project_id": PROJECT_ID,
            "date_from": date(2026, 4, 1),
            "date_to": date(2026, 4, 26),
            "days_observed": 20,
            "avg_headcount": 18.5,
            "issue_count_by_kind": {"risk": 4, "delay": 2},
            "severity_counts": {"high": 3, "medium": 5},
            "weather_anomaly_days": [],
            "most_common_observations": [{"description": "Trễ vật tư", "count": 3}],
        }
    )
    for parent in ("ml", "ml.pipelines"):
        if parent not in sys.modules:
            monkeypatch.setitem(sys.modules, parent, ModuleType(parent))
    monkeypatch.setitem(sys.modules, "ml.pipelines.dailylog", mod)
    return mod


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import dailylog as router_mod

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


def _log_row(**overrides: Any) -> SimpleNamespace:
    base = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        log_date=date(2026, 4, 26),
        weather={"temp_c": 30, "precipitation_mm": 0},
        supervisor_id=USER_ID,
        narrative="Đổ bê tông cột tầng 3",
        work_completed=None,
        issues_observed=None,
        status="draft",
        submitted_at=None,
        approved_at=None,
        approved_by=None,
        extracted_at=None,
        created_by=USER_ID,
        created_at=datetime(2026, 4, 26, 8, tzinfo=UTC),
        updated_at=datetime(2026, 4, 26, 8, tzinfo=UTC),
        total_headcount=0,
        open_observations=0,
        high_severity_observations=0,
    )
    base.update(overrides)
    return _make_row(**base)


# =============================================================================
# Tests
# =============================================================================


async def test_create_log_with_auto_extract_runs_pipeline(client, patch_session, patch_pipeline):
    log = _log_row()
    obs_id = uuid4()
    obs_row = _make_row(
        id=obs_id,
        organization_id=ORG_ID,
        log_id=log._mapping["id"],
        kind="risk",
        severity="high",
        description="Mưa to làm chậm đổ bê tông tầng 3",
        source="llm_extracted",
        related_safety_incident_id=None,
        status="open",
        resolved_at=None,
        notes=None,
        created_at=datetime(2026, 4, 26, 12, tzinfo=UTC),
    )

    # 1: INSERT log RETURNING; 2: DELETE manpower; 3: DELETE equipment;
    # 4: INSERT observation RETURNING; 5: UPDATE extracted_at
    patch_session.queue(_result(log))
    patch_session.queue(_result(None))
    patch_session.queue(_result(None))
    patch_session.queue(_result(obs_row))
    patch_session.queue(_result(None))

    resp = await client.post(
        "/api/v1/dailylog/logs",
        json={
            "project_id": str(PROJECT_ID),
            "log_date": "2026-04-26",
            "narrative": "Mưa to cả ngày, trễ tiến độ",
            "weather": {"temp_c": 28, "precipitation_mm": 25},
            "manpower": [],
            "equipment": [],
            "auto_extract": True,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["log_date"] == "2026-04-26"
    assert body["high_severity_observations"] == 1
    patch_pipeline.extract_observations.assert_awaited_once()


async def test_create_log_skips_extract_when_auto_extract_false(client, patch_session, patch_pipeline):
    log = _log_row()
    patch_session.queue(_result(log))
    patch_session.queue(_result(None))
    patch_session.queue(_result(None))

    resp = await client.post(
        "/api/v1/dailylog/logs",
        json={
            "project_id": str(PROJECT_ID),
            "log_date": "2026-04-26",
            "narrative": "Bình thường",
            "auto_extract": False,
        },
    )
    assert resp.status_code == 201, resp.text
    patch_pipeline.extract_observations.assert_not_awaited()


async def test_get_log_404_when_missing(client, patch_session):
    patch_session.queue(_result(None))
    resp = await client.get(f"/api/v1/dailylog/logs/{uuid4()}")
    assert resp.status_code == 404


async def test_extract_endpoint_409s_when_already_extracted_without_force(client, patch_session, patch_pipeline):
    lid = uuid4()
    log = _make_row(
        id=lid,
        narrative="x",
        work_completed=None,
        issues_observed=None,
        weather={},
        extracted_at=datetime(2026, 4, 26, tzinfo=UTC),
    )
    patch_session.queue(_result(log))

    resp = await client.post(f"/api/v1/dailylog/logs/{lid}/extract", json={"force": False})
    assert resp.status_code == 409
    patch_pipeline.extract_observations.assert_not_awaited()


async def test_extract_force_true_overwrites_old_observations(client, patch_session, patch_pipeline):
    lid = uuid4()
    log = _make_row(
        id=lid,
        narrative="Mưa to",
        work_completed=None,
        issues_observed=None,
        weather={"precipitation_mm": 25},
        extracted_at=datetime(2026, 4, 26, tzinfo=UTC),
    )
    obs_row = _make_row(
        id=uuid4(),
        organization_id=ORG_ID,
        log_id=lid,
        kind="risk",
        severity="high",
        description="Mưa to làm chậm đổ bê tông tầng 3",
        source="llm_extracted",
        related_safety_incident_id=None,
        status="open",
        resolved_at=None,
        notes=None,
        created_at=datetime(2026, 4, 26, 12, tzinfo=UTC),
    )
    # 1: SELECT log; 2: SELECT manpower; 3: SELECT equipment;
    # 4: DELETE old llm_extracted; 5: INSERT new RETURNING; 6: UPDATE extracted_at
    patch_session.queue(_result(log))
    patch_session.queue(_result(rows=[]))
    patch_session.queue(_result(rows=[]))
    patch_session.queue(_result(None))
    patch_session.queue(_result(obs_row))
    patch_session.queue(_result(None))

    resp = await client.post(f"/api/v1/dailylog/logs/{lid}/extract", json={"force": True})
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert len(body["observations"]) == 1
    assert body["observations"][0]["kind"] == "risk"


async def test_patterns_endpoint_calls_aggregator(client, patch_session, patch_pipeline):
    # 1: SELECT logs; 2: SELECT manpower; 3: SELECT observations
    patch_session.queue(_result(rows=[]))
    patch_session.queue(_result(rows=[]))
    patch_session.queue(_result(rows=[]))

    resp = await client.get(
        f"/api/v1/dailylog/projects/{PROJECT_ID}/patterns",
        params={"date_from": "2026-04-01", "date_to": "2026-04-26"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["days_observed"] == 20
    assert body["avg_headcount"] == 18.5
    assert body["issue_count_by_kind"]["risk"] == 4
    patch_pipeline.aggregate_patterns.assert_called_once()
