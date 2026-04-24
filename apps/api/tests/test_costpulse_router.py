"""Router tests for CostPulse endpoints.

Follows the bidradar pattern: builds a minimal FastAPI app with only the
costpulse router mounted, overrides `require_auth` + `get_db`, and stubs the
AI pipeline + arq enqueue so no external services are touched.

RLS isolation is covered by asserting that every list/get endpoint scopes
its `WHERE` clause by `organization_id`. End-to-end RLS against Postgres
lives in `test_costpulse_rls.py` (skipped unless DATABASE_URL points at a
live DB).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
OTHER_ORG_ID = UUID("99999999-9999-9999-9999-999999999999")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
    """Records adds; returns programmable execute() results."""

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

    async def refresh(self, obj: Any) -> None:
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime.now(timezone.utc)

    async def execute(self, stmt: Any = None, *_a: Any, **_k: Any) -> Any:
        self.executed_stmts.append(stmt)
        if self._execute_results:
            return self._execute_results.pop(0)
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.scalar_one.return_value = 0
        r.scalars.return_value.all.return_value = []
        r.first.return_value = None
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture
def app(fake_db) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from fastapi import HTTPException
    from middleware.auth import AuthContext, require_auth
    from routers import costpulse as costpulse_router

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="tester@example.com",
    )

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(costpulse_router.router)

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


# ---------- Helpers to build model rows ----------

def _material_price_row(**overrides: Any):
    base = dict(
        id=uuid4(),
        material_code="CONC_C30",
        name="Bê tông M300",
        category="concrete",
        unit="m3",
        price_vnd=Decimal("1580000"),
        price_usd=None,
        province="Hanoi",
        source="government",
        effective_date=date(2026, 4, 1),
        expires_date=None,
        supplier_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _supplier_row(**overrides: Any):
    base = dict(
        id=uuid4(),
        organization_id=None,
        name="Hòa Phát",
        categories=["steel"],
        provinces=["Hanoi"],
        contact={"email": "sales@hoaphat.example.vn"},
        verified=True,
        rating=Decimal("4.5"),
        created_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------- Prices ----------

async def test_lookup_prices_returns_paginated_rows(client, fake_db):
    row = _material_price_row()
    count_q = MagicMock()
    count_q.scalar_one.return_value = 1
    rows_q = MagicMock()
    rows_q.scalars.return_value.all.return_value = [row]
    fake_db.push_execute(count_q)
    fake_db.push_execute(rows_q)

    res = await client.get("/api/v1/costpulse/prices", params={"q": "bê"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["data"][0]["material_code"] == "CONC_C30"
    assert body["meta"]["total"] == 1


async def test_price_history_returns_points_and_deltas(client, fake_db):
    older = _material_price_row(
        effective_date=date(2025, 4, 1), price_vnd=Decimal("1400000")
    )
    newer = _material_price_row(
        effective_date=date(2026, 4, 1), price_vnd=Decimal("1580000")
    )
    q = MagicMock()
    q.scalars.return_value.all.return_value = [older, newer]
    fake_db.push_execute(q)

    res = await client.get("/api/v1/costpulse/prices/history/CONC_C30")

    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data["points"]) == 2
    assert data["pct_change_1y"] is not None
    assert data["pct_change_1y"] > 0


async def test_price_history_404_when_no_rows(client, fake_db):
    q = MagicMock()
    q.scalars.return_value.all.return_value = []
    fake_db.push_execute(q)

    res = await client.get("/api/v1/costpulse/prices/history/UNKNOWN_CODE")
    assert res.status_code == 404


async def test_price_override_is_captured_as_crowdsource(client, fake_db):
    from models.costpulse import MaterialPrice

    existing = _material_price_row(name="Bê tông M300", unit="m3", category="concrete")
    existing_q = MagicMock()
    existing_q.scalar_one_or_none.return_value = existing
    fake_db.push_execute(existing_q)

    res = await client.post(
        "/api/v1/costpulse/prices/override",
        params={
            "material_code": "CONC_C30",
            "price_vnd": 1600000,
            "province": "Hanoi",
        },
    )

    assert res.status_code == 200, res.text
    added = [o for o in fake_db.added if isinstance(o, MaterialPrice)]
    assert len(added) == 1
    assert added[0].source == "crowdsource"
    assert added[0].material_code == "CONC_C30"
    assert added[0].price_vnd == Decimal("1600000")


# ---------- Suppliers ----------

async def test_list_suppliers_paginates(client, fake_db):
    count_q = MagicMock()
    count_q.scalar_one.return_value = 2
    rows_q = MagicMock()
    rows_q.scalars.return_value.all.return_value = [
        _supplier_row(name="Hòa Phát"),
        _supplier_row(name="Viglacera", categories=["finishing"]),
    ]
    fake_db.push_execute(count_q)
    fake_db.push_execute(rows_q)

    res = await client.get("/api/v1/costpulse/suppliers", params={"verified_only": True})

    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["total"] == 2
    assert {s["name"] for s in body["data"]} == {"Hòa Phát", "Viglacera"}


async def test_create_supplier_scopes_to_caller_org(client, fake_db):
    from models.costpulse import Supplier

    res = await client.post(
        "/api/v1/costpulse/suppliers",
        json={
            "name": "New Vendor",
            "categories": ["concrete"],
            "provinces": ["HCM"],
            "contact": {"email": "vendor@example.com"},
        },
    )

    assert res.status_code == 201, res.text
    added = [o for o in fake_db.added if isinstance(o, Supplier)]
    assert len(added) == 1
    assert added[0].organization_id == ORG_ID
    assert added[0].verified is False  # never trust self-assertion


# ---------- RFQ ----------

async def test_create_rfq_enqueues_dispatch_job(client, fake_db, monkeypatch):
    from models.costpulse import Rfq

    enqueue_mock = AsyncMock(return_value="job-123")
    monkeypatch.setattr("workers.queue.enqueue_rfq_dispatch", enqueue_mock)

    supplier_id = uuid4()
    res = await client.post(
        "/api/v1/costpulse/rfq",
        json={
            "supplier_ids": [str(supplier_id)],
            "deadline": "2026-05-15",
        },
    )

    assert res.status_code == 201, res.text
    added = [o for o in fake_db.added if isinstance(o, Rfq)]
    assert len(added) == 1
    assert added[0].organization_id == ORG_ID
    assert added[0].status == "draft"
    assert enqueue_mock.await_count == 1
    kwargs = enqueue_mock.await_args.kwargs
    assert kwargs["organization_id"] == ORG_ID
    assert kwargs["rfq_id"] == added[0].id


async def test_list_rfq_filters_by_caller_org(client, fake_db):
    rfq_row = SimpleNamespace(
        id=uuid4(),
        project_id=None,
        estimate_id=None,
        status="sent",
        sent_to=[],
        responses=[],
        deadline=None,
        created_at=datetime.now(timezone.utc),
    )
    q = MagicMock()
    q.scalars.return_value.all.return_value = [rfq_row]
    fake_db.push_execute(q)

    res = await client.get("/api/v1/costpulse/rfq")
    assert res.status_code == 200
    body = res.json()
    assert len(body["data"]) == 1

    # Validate the query used the caller's org id — guards against a regression
    # where RfQ listing leaks rows from other tenants.
    # SQLAlchemy literal-binds UUIDs without dashes, so compare by .hex.
    stmt = fake_db.executed_stmts[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert ORG_ID.hex in compiled
    assert OTHER_ORG_ID.hex not in compiled


# ---------- Estimates (RLS-style scoping at query level) ----------

async def test_get_estimate_scopes_query_to_caller_org(client, fake_db):
    q = MagicMock()
    q.scalar_one_or_none.return_value = None
    fake_db.push_execute(q)

    estimate_id = uuid4()
    res = await client.get(f"/api/v1/costpulse/estimates/{estimate_id}")

    assert res.status_code == 404
    stmt = fake_db.executed_stmts[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # Both filters should be present — org AND id.
    assert ORG_ID.hex in compiled
    assert estimate_id.hex in compiled


async def test_approve_estimate_404_for_missing_or_other_org(client, fake_db):
    q = MagicMock()
    q.scalar_one_or_none.return_value = None  # as if belongs to another org
    fake_db.push_execute(q)

    res = await client.post(f"/api/v1/costpulse/estimates/{uuid4()}/approve")
    assert res.status_code == 404


# ---------- AI estimate (router wiring; pipeline mocked) ----------

async def test_estimate_from_brief_delegates_to_pipeline(client, fake_db, monkeypatch):
    from schemas.costpulse import AiEstimateResult, BoqItemOut, EstimateConfidence

    estimate_id = uuid4()
    item = BoqItemOut(
        id=uuid4(),
        estimate_id=estimate_id,
        parent_id=None,
        sort_order=0,
        code="1.1",
        description="Concrete",
        unit="m3",
        quantity=Decimal("100"),
        unit_price_vnd=Decimal("1580000"),
        total_price_vnd=Decimal("158000000"),
        material_code="CONC_C30",
        source="ai_extracted",
        notes=None,
    )
    fake_result = AiEstimateResult(
        estimate_id=estimate_id,
        total_vnd=158_000_000,
        confidence=EstimateConfidence.rough_order,
        items=[item],
        warnings=[],
        missing_price_codes=[],
    )
    mock = AsyncMock(return_value=fake_result)
    monkeypatch.setattr("apps.ml.pipelines.costpulse.estimate_from_brief", mock)

    res = await client.post(
        "/api/v1/costpulse/estimate/from-brief",
        json={
            "name": "Tower A rough",
            "project_type": "commercial",
            "area_sqm": 5000,
            "floors": 10,
            "province": "Hanoi",
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["estimate_id"] == str(estimate_id)
    assert body["total_vnd"] == 158_000_000
    assert mock.await_count == 1
    pipeline_kwargs = mock.await_args.kwargs
    assert pipeline_kwargs["organization_id"] == ORG_ID
    assert pipeline_kwargs["created_by"] == USER_ID
