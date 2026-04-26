"""Router tests for /api/v1/schedule/*.

Mirrors the handover pattern: `TenantAwareSession` is replaced with a
recording session whose `execute()` returns pre-programmed Result objects.
The ML pipeline is stubbed via `sys.modules["ml.pipelines.schedulepilot"]`.

These are smoke tests — they verify HTTP wiring, validation, envelope shape,
and basic happy paths. SQL correctness needs an integration test against
real Postgres.
"""

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


# ---------- Fakes ----------


def _make_row(**fields: Any) -> SimpleNamespace:
    """Result-row stub: my router does `dict(row._mapping)`, so anything
    with a `_mapping` attribute that's iterable as a dict will round-trip."""
    return SimpleNamespace(_mapping=fields)


def _result_returning(row: SimpleNamespace | None = None, rows: list | None = None) -> MagicMock:
    """An execute() result with `.one() / .one_or_none() / .all()` populated."""
    r = MagicMock()
    r.one.return_value = row
    r.one_or_none.return_value = row
    r.first.return_value = row
    r.all.return_value = rows or ([row] if row is not None else [])
    r.rowcount = 1 if row is not None else 0
    return r


def _scalar_result(value: Any) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = value
    r.scalar_one_or_none.return_value = value
    return r


class _ProgrammableSession:
    """Async session that returns pre-queued `execute()` results in order."""

    def __init__(self) -> None:
        self._queue: list[Any] = []
        self.executes: list[tuple[str, dict]] = []

    def queue(self, result: Any) -> _ProgrammableSession:
        self._queue.append(result)
        return self

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        self.executes.append((str(stmt), params or {}))
        if self._queue:
            return self._queue.pop(0)
        # Default: harmless empty result so untested branches don't blow up.
        r = MagicMock()
        r.one.side_effect = AssertionError("unprogrammed .one()")
        r.one_or_none.return_value = None
        r.all.return_value = []
        r.scalar_one.return_value = 0
        r.scalar_one_or_none.return_value = None
        r.rowcount = 0
        r.first.return_value = None
        return r

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


# ---------- Fixtures ----------


@pytest.fixture
def patch_session(monkeypatch):
    session = _ProgrammableSession()

    class _FakeTenantAwareSession:
        def __init__(self, org_id: Any) -> None:
            self._org_id = org_id

        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("routers.schedulepilot.TenantAwareSession", _FakeTenantAwareSession)
    return session


@pytest.fixture
def patch_pipeline(monkeypatch):
    """Stub `ml.pipelines.schedulepilot` so the lazy import in
    `run_risk_assessment` doesn't pull langchain.
    """
    mod = ModuleType("ml.pipelines.schedulepilot")
    mod.run_risk_assessment = AsyncMock(
        return_value={
            "model_version": "schedulepilot/test",
            "overall_slip_days": 5,
            "confidence_pct": 70,
            "critical_path_codes": ["A", "B", "C"],
            "top_risks": [
                {
                    "activity_id": "00000000-0000-0000-0000-000000000002",
                    "code": "B",
                    "name": "Walls",
                    "expected_slip_days": 7,
                    "reason": "50% complete with calendar overshoot",
                    "mitigation": "Add a second crew",
                }
            ],
            "input_summary": {"activity_count": 3, "in_progress": 1},
            "notes": "test narration",
        }
    )
    for parent in ("ml", "ml.pipelines"):
        if parent not in sys.modules:
            monkeypatch.setitem(sys.modules, parent, ModuleType(parent))
    monkeypatch.setitem(sys.modules, "ml.pipelines.schedulepilot", mod)
    return mod


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import schedulepilot as router_mod

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="t@example.com",
    )
    a = FastAPI()
    a.add_exception_handler(HTTPException, http_exception_handler)
    a.add_exception_handler(Exception, unhandled_exception_handler)
    a.include_router(router_mod.router)
    a.dependency_overrides[require_auth] = lambda: auth_ctx
    return a


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------- Helpers ----------


def _schedule_row(**overrides: Any) -> SimpleNamespace:
    base = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        name="Master schedule v1",
        status="draft",
        baseline_set_at=None,
        data_date=None,
        notes=None,
        created_by=USER_ID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return _make_row(**base)


def _activity_row(**overrides: Any) -> SimpleNamespace:
    base = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        schedule_id=uuid4(),
        code="A",
        name="Foundation",
        activity_type="task",
        planned_start=date(2026, 1, 1),
        planned_finish=date(2026, 1, 10),
        planned_duration_days=10,
        baseline_start=None,
        baseline_finish=None,
        actual_start=None,
        actual_finish=None,
        percent_complete=0,
        status="not_started",
        assignee_id=None,
        notes=None,
        sort_order=0,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return _make_row(**base)


# =============================================================================
# Tests
# =============================================================================


async def test_create_schedule_returns_201_with_envelope(client, patch_session):
    row = _schedule_row(name="Tower A — master")
    patch_session.queue(_result_returning(row))

    resp = await client.post(
        "/api/v1/schedule/schedules",
        json={"project_id": str(PROJECT_ID), "name": "Tower A — master"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["data"]["name"] == "Tower A — master"
    assert body["data"]["status"] == "draft"
    assert body["data"]["activity_count"] == 0
    assert body["data"]["percent_complete"] == 0.0


async def test_list_schedules_returns_paginated_envelope(client, patch_session):
    s1 = _schedule_row(
        name="Phase 1",
        activity_count=3,
        behind_schedule_count=1,
        avg_pct=33.3,
    )
    s2 = _schedule_row(
        name="Phase 2",
        activity_count=0,
        behind_schedule_count=0,
        avg_pct=0,
    )
    # 1: COUNT(*) → 2; 2: SELECT s.*, ... → list of two rows.
    patch_session.queue(_scalar_result(2))
    patch_session.queue(_result_returning(rows=[s1, s2]))

    resp = await client.get("/api/v1/schedule/schedules")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"]["total"] == 2
    names = [s["name"] for s in body["data"]]
    assert names == ["Phase 1", "Phase 2"]
    assert body["data"][0]["activity_count"] == 3
    assert body["data"][0]["behind_schedule_count"] == 1


async def test_get_schedule_404_when_missing(client, patch_session):
    patch_session.queue(_result_returning(None))  # SELECT * returns nothing

    resp = await client.get(f"/api/v1/schedule/schedules/{uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["errors"][0]["message"] == "Schedule not found"


async def test_baseline_endpoint_flips_status_and_returns_baselined(client, patch_session):
    sid = uuid4()
    # 1: existence check; 2: UPDATE activities (no rows in router); 3: UPDATE schedule
    patch_session.queue(_result_returning(_make_row(id=sid)))
    patch_session.queue(_result_returning(None))  # bulk UPDATE doesn't fetch
    patch_session.queue(_result_returning(_schedule_row(id=sid, status="baselined")))

    resp = await client.post(
        f"/api/v1/schedule/schedules/{sid}/baseline",
        json={"note": "Locking after sponsor sign-off"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "baselined"


async def test_create_dependency_rejects_self_loop(client, patch_session):
    aid = str(uuid4())
    resp = await client.post(
        "/api/v1/schedule/dependencies",
        json={
            "predecessor_id": aid,
            "successor_id": aid,
            "relationship_type": "fs",
            "lag_days": 0,
        },
    )
    assert resp.status_code == 400
    assert "differ" in resp.json()["errors"][0]["message"]


async def test_create_dependency_rejects_cycle(client, patch_session):
    pred, succ = uuid4(), uuid4()
    # _would_create_cycle's recursive CTE: returns a row when a path back exists.
    patch_session.queue(_result_returning(_make_row(exists=1)))

    resp = await client.post(
        "/api/v1/schedule/dependencies",
        json={
            "predecessor_id": str(pred),
            "successor_id": str(succ),
            "relationship_type": "fs",
            "lag_days": 0,
        },
    )
    assert resp.status_code == 400
    assert "cycle" in resp.json()["errors"][0]["message"].lower()


async def test_run_risk_assessment_invokes_pipeline_and_persists(client, patch_session, patch_pipeline):
    sid = uuid4()
    a1, a2, a3 = _activity_row(code="A"), _activity_row(code="B"), _activity_row(code="C")
    sched = _schedule_row(id=sid, data_date=date(2026, 4, 25))
    # 1: SELECT * FROM schedules; 2: SELECT activities; 3: SELECT deps;
    # 4: INSERT ... RETURNING
    patch_session.queue(_result_returning(sched))
    patch_session.queue(_result_returning(rows=[a1, a2, a3]))
    patch_session.queue(_result_returning(rows=[]))
    patch_session.queue(
        _result_returning(
            _make_row(
                id=uuid4(),
                organization_id=ORG_ID,
                schedule_id=sid,
                generated_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
                model_version="schedulepilot/test",
                data_date_used=date(2026, 4, 25),
                overall_slip_days=5,
                confidence_pct=70,
                critical_path_codes=["A", "B", "C"],
                top_risks=[
                    {
                        "activity_id": "00000000-0000-0000-0000-000000000002",
                        "code": "B",
                        "name": "Walls",
                        "expected_slip_days": 7,
                        "reason": "behind",
                        "mitigation": "second crew",
                    }
                ],
                input_summary={"activity_count": 3},
                notes="test",
            )
        )
    )

    resp = await client.post(
        f"/api/v1/schedule/schedules/{sid}/risk-assessment",
        json={"force": True},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["data"]["overall_slip_days"] == 5
    assert body["data"]["critical_path_codes"] == ["A", "B", "C"]
    assert len(body["data"]["top_risks"]) == 1
    patch_pipeline.run_risk_assessment.assert_awaited_once()
