"""Router tests for the cross-module /api/v1/projects hub.

Follows the costpulse/bidradar pattern: builds an isolated FastAPI app with
only the projects router mounted, overrides `require_auth` + `get_db`, and
programs a sequence of execute() results that mirror the queries the router
fires in order.

The detail endpoint fans out to every module, so each test programs the
exact stack of mocks it needs and asserts on what the router rolled up.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
OTHER_ORG_ID = UUID("99999999-9999-9999-9999-999999999999")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
    """Queued-result async session stub mirroring the costpulse pattern."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.executed_stmts: list[Any] = []
        self._execute_results: list[Any] = []

    def push_execute(self, result: Any) -> None:
        self._execute_results.append(result)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
    async def refresh(self, obj: Any) -> None: ...

    async def execute(self, stmt: Any = None, *_a: Any, **_k: Any) -> Any:
        self.executed_stmts.append(stmt)
        if self._execute_results:
            return self._execute_results.pop(0)
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.scalar_one.return_value = 0
        r.scalars.return_value.all.return_value = []
        r.one_or_none.return_value = None
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
    from routers import projects as projects_router

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="tester@example.com",
    )

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(projects_router.router)

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


# ---------- Helpers ----------


def _project_row(**overrides: Any):
    base = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        name="Tower A",
        type="commercial",
        status="active",
        address={"province": "Hanoi"},
        area_sqm=Decimal("5000"),
        floors=10,
        budget_vnd=1_000_000_000,
        start_date=date(2026, 1, 1),
        end_date=None,
        metadata_={},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    base.update(overrides)
    # Project.metadata_ maps to DB column "metadata" — schema reads that via
    # `from_attributes`, so we expose it as `metadata_` here.
    ns = SimpleNamespace(**base)
    # Pydantic's `from_attributes` looks up `metadata`; mirror the attr.
    ns.metadata = base["metadata_"]
    return ns


# ---------- List endpoint ----------


async def test_list_projects_returns_per_project_counters(client, fake_db):
    project = _project_row()
    count_q = MagicMock()
    count_q.scalar_one.return_value = 1
    rows_q = MagicMock()
    rows_q.scalars.return_value.all.return_value = [project]
    # Three aggregate queries: open tasks, open COs, document counts.
    tasks_q = MagicMock()
    tasks_q.all.return_value = [SimpleNamespace(project_id=project.id, open_tasks=7)]
    cos_q = MagicMock()
    cos_q.all.return_value = [SimpleNamespace(project_id=project.id, open_cos=2)]
    docs_q = MagicMock()
    docs_q.all.return_value = [SimpleNamespace(project_id=project.id, doc_count=45)]

    for r in (count_q, rows_q, tasks_q, cos_q, docs_q):
        fake_db.push_execute(r)

    res = await client.get("/api/v1/projects")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["meta"]["total"] == 1
    card = body["data"][0]
    assert card["name"] == "Tower A"
    assert card["open_tasks"] == 7
    assert card["open_change_orders"] == 2
    assert card["document_count"] == 45


async def test_list_projects_empty_result_skips_aggregate_queries(client, fake_db):
    """No projects → don't fire 3 aggregate queries for an empty id list."""
    count_q = MagicMock()
    count_q.scalar_one.return_value = 0
    rows_q = MagicMock()
    rows_q.scalars.return_value.all.return_value = []
    fake_db.push_execute(count_q)
    fake_db.push_execute(rows_q)

    res = await client.get("/api/v1/projects")

    assert res.status_code == 200
    assert res.json()["data"] == []
    # Only 2 executes ran — the list stmt + count — no per-project aggregates.
    assert len(fake_db.executed_stmts) == 2


async def test_list_projects_scopes_to_caller_org(client, fake_db):
    count_q = MagicMock()
    count_q.scalar_one.return_value = 0
    rows_q = MagicMock()
    rows_q.scalars.return_value.all.return_value = []
    fake_db.push_execute(count_q)
    fake_db.push_execute(rows_q)

    await client.get("/api/v1/projects")

    # The list stmt (second executed) should compile with caller's org hex.
    compiled = str(fake_db.executed_stmts[1].compile(compile_kwargs={"literal_binds": True}))
    assert ORG_ID.hex in compiled
    assert OTHER_ORG_ID.hex not in compiled


# ---------- Detail endpoint ----------


async def test_get_project_detail_404_when_missing(client, fake_db):
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    fake_db.push_execute(not_found)

    res = await client.get(f"/api/v1/projects/{uuid4()}")
    assert res.status_code == 404


async def test_get_project_detail_rolls_up_all_modules(client, fake_db):
    """End-to-end roll-up: one mock per query the router fires, in order."""
    project = _project_row()
    proposal = SimpleNamespace(
        id=uuid4(),
        project_id=project.id,
        status="won",
        total_fee_vnd=Decimal("550000000"),
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
    )

    # Query order mirrors routers/projects.py:
    #  1. SELECT project
    #  2. Winwork: latest proposal
    #  3. Costpulse: estimate count row (total, approved)
    #  4. Costpulse: latest estimate id + total
    #  5. Pulse: task counts (todo, in_progress, done)
    #  6. Pulse: open change orders (scalar)
    #  7. Pulse: upcoming milestones (scalar)
    #  8. Drawbridge: document count
    #  9. Drawbridge: open rfis
    # 10. Drawbridge: unresolved conflicts
    # 11. Handover: packages
    # 12. Handover: open defects
    # 13. Handover: warranty counts (active, expiring)
    # 14. Siteeye: site visits
    # 15. Siteeye: open safety incidents
    # 16. Codeguard: compliance checks
    # 17. Codeguard: permit checklists
    latest_est_id = uuid4()

    def _one(**attrs):
        m = MagicMock()
        m.one.return_value = SimpleNamespace(**attrs)
        return m

    def _one_or_none(ns):
        m = MagicMock()
        m.one_or_none.return_value = ns
        return m

    def _scalar(v):
        m = MagicMock()
        m.scalar_one.return_value = v
        return m

    def _scalar_or_none(v):
        m = MagicMock()
        m.scalar_one_or_none.return_value = v
        return m

    for r in [
        _scalar_or_none(project),  # 1 project
        _scalar_or_none(proposal),  # 2 winwork proposal
        _one(total=3, approved=2),  # 3 estimate counts
        _one_or_none(
            SimpleNamespace(  # 4 latest estimate
                id=latest_est_id, total_vnd=1_200_000_000
            )
        ),
        _one(todo=5, in_progress=3, done=12),  # 5 task counts
        _scalar(4),  # 6 open change orders
        _scalar(2),  # 7 upcoming milestones
        _scalar(45),  # 8 documents
        _scalar(1),  # 9 open rfis
        _scalar(0),  # 10 unresolved conflicts
        _scalar(1),  # 11 handover packages
        _scalar(6),  # 12 open defects
        _one(active=8, expiring=2),  # 13 warranty counts
        _scalar(14),  # 14 site visits
        _scalar(1),  # 15 open safety incidents
        _scalar(3),  # 16 compliance checks
        _scalar(2),  # 17 permit checklists
    ]:
        fake_db.push_execute(r)

    res = await client.get(f"/api/v1/projects/{project.id}")

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["name"] == "Tower A"

    assert data["winwork"]["proposal_id"] == str(proposal.id)
    assert data["winwork"]["proposal_status"] == "won"
    assert data["winwork"]["total_fee_vnd"] == 550_000_000

    assert data["costpulse"]["estimate_count"] == 3
    assert data["costpulse"]["approved_count"] == 2
    assert data["costpulse"]["latest_estimate_id"] == str(latest_est_id)
    assert data["costpulse"]["latest_total_vnd"] == 1_200_000_000

    assert data["pulse"]["tasks_todo"] == 5
    assert data["pulse"]["tasks_in_progress"] == 3
    assert data["pulse"]["tasks_done"] == 12
    assert data["pulse"]["open_change_orders"] == 4
    assert data["pulse"]["upcoming_milestones"] == 2

    assert data["drawbridge"]["document_count"] == 45
    assert data["drawbridge"]["open_rfi_count"] == 1
    assert data["drawbridge"]["unresolved_conflict_count"] == 0

    assert data["handover"]["package_count"] == 1
    assert data["handover"]["open_defect_count"] == 6
    assert data["handover"]["warranty_active_count"] == 8
    assert data["handover"]["warranty_expiring_count"] == 2

    assert data["siteeye"]["visit_count"] == 14
    assert data["siteeye"]["open_safety_incident_count"] == 1

    assert data["codeguard"]["compliance_check_count"] == 3
    assert data["codeguard"]["permit_checklist_count"] == 2


async def test_get_project_detail_handles_empty_modules(client, fake_db):
    """Project with no module data — every roll-up should return zeros /
    nones without choking on empty results."""
    project = _project_row()

    def _scalar_or_none(v):
        m = MagicMock()
        m.scalar_one_or_none.return_value = v
        return m

    def _scalar(v):
        m = MagicMock()
        m.scalar_one.return_value = v
        return m

    def _one(**attrs):
        m = MagicMock()
        m.one.return_value = SimpleNamespace(**attrs)
        return m

    def _one_or_none(ns):
        m = MagicMock()
        m.one_or_none.return_value = ns
        return m

    for r in [
        _scalar_or_none(project),
        _scalar_or_none(None),  # no winwork proposal
        _one(total=0, approved=0),
        _one_or_none(None),  # no latest estimate
        _one(todo=0, in_progress=0, done=0),
        _scalar(0),
        _scalar(0),
        _scalar(0),
        _scalar(0),
        _scalar(0),
        _scalar(0),
        _scalar(0),
        _one(active=0, expiring=0),
        _scalar(0),
        _scalar(0),
        _scalar(0),
        _scalar(0),
    ]:
        fake_db.push_execute(r)

    res = await client.get(f"/api/v1/projects/{project.id}")

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["winwork"]["proposal_id"] is None
    assert data["costpulse"]["estimate_count"] == 0
    assert data["costpulse"]["latest_estimate_id"] is None
    assert data["pulse"]["tasks_todo"] == 0
    assert data["handover"]["warranty_active_count"] == 0
