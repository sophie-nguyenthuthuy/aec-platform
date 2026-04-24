"""Router-level tests for /api/v1/winwork/*.

All DB access in the router goes through `services.winwork.*`, so tests mock
that service module and assert HTTP wiring, auth, and envelope shape — not
SQL correctness. The service-layer SQL is covered separately (or left for
integration tests against a real Postgres).
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.asyncio


# ---------- Local app fixture (overrides codeguard-only app from conftest) ----------

@pytest.fixture
def app(fake_auth, fake_db) -> Iterator[FastAPI]:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from middleware.auth import require_auth
    from routers import winwork as winwork_router

    async def _override_db() -> AsyncIterator:
        yield fake_db

    test_app = FastAPI()
    test_app.add_exception_handler(HTTPException, http_exception_handler)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)
    test_app.include_router(winwork_router.router)
    test_app.dependency_overrides[require_auth] = lambda: fake_auth
    test_app.dependency_overrides[get_db] = _override_db
    try:
        yield test_app
    finally:
        test_app.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Helpers ----------

def _make_proposal(**overrides: Any):
    """Produce a Proposal schema instance. Router calls `model_validate` on the
    service's ORM row; this short-circuits that by handing back a dict-like
    shape the pydantic `from_attributes=True` config accepts."""
    from schemas.winwork import Proposal

    base = dict(
        id=uuid4(),
        title="Office fit-out — District 1",
        project_id=uuid4(),
        client_name="Acme Corp",
        client_email=None,
        scope_of_work=None,
        fee_breakdown=None,
        total_fee_vnd=500_000_000,
        total_fee_currency="VND",
        valid_until=None,
        notes=None,
        status="draft",
        ai_generated=False,
        ai_confidence=None,
        sent_at=None,
        responded_at=None,
        created_by=uuid4(),
        created_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return Proposal.model_validate(base)


# ============================================================
# Benchmarks + fee estimate
# ============================================================

async def test_list_benchmarks_returns_rows_from_service(client, monkeypatch):
    from schemas.winwork import FeeBenchmark

    bench = FeeBenchmark.model_validate(
        dict(
            id=uuid4(),
            discipline="architecture",
            project_type="residential_villa",
            country_code="VN",
            province="Hanoi",
            area_sqm_min=Decimal("100"),
            area_sqm_max=Decimal("500"),
            fee_percent_low=Decimal("4.5"),
            fee_percent_mid=Decimal("6.0"),
            fee_percent_high=Decimal("8.0"),
            source="VACE 2024",
            valid_from=date(2024, 1, 1),
            valid_to=None,
        )
    )
    mock = AsyncMock(return_value=[bench])
    monkeypatch.setattr("services.winwork.lookup_benchmarks", mock)

    r = await client.get("/api/v1/winwork/benchmarks", params={"discipline": "architecture"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"][0]["project_type"] == "residential_villa"
    assert body["data"][0]["source"] == "VACE 2024"
    # Filters are passed through as a BenchmarkFilters instance
    filters = mock.call_args.args[1]
    assert filters.discipline == "architecture"
    assert filters.country_code == "VN"


async def test_fee_estimate_returns_bands(client, monkeypatch):
    from schemas.winwork import FeeEstimateResponse

    mock = AsyncMock(
        return_value=FeeEstimateResponse(
            fee_low_vnd=100_000_000,
            fee_mid_vnd=150_000_000,
            fee_high_vnd=200_000_000,
            fee_percent_low=5.0,
            fee_percent_mid=7.5,
            fee_percent_high=10.0,
            basis="VACE 2024",
            confidence=0.75,
        )
    )
    monkeypatch.setattr("services.winwork.estimate_fee", mock)

    r = await client.post(
        "/api/v1/winwork/fee-estimate",
        json={
            "discipline": "architecture",
            "project_type": "residential_villa",
            "area_sqm": 250,
            "country_code": "VN",
            "province": "Hanoi",
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["fee_mid_vnd"] == 150_000_000
    assert body["data"]["confidence"] == 0.75


async def test_fee_estimate_rejects_zero_area(client):
    r = await client.post(
        "/api/v1/winwork/fee-estimate",
        json={
            "discipline": "architecture",
            "project_type": "residential_villa",
            "area_sqm": 0,
            "country_code": "VN",
        },
    )
    assert r.status_code == 422


# ============================================================
# Proposals CRUD
# ============================================================

async def test_list_proposals_paginates(client, monkeypatch):
    rows = [_make_proposal(title=f"Prop {i}") for i in range(3)]
    monkeypatch.setattr(
        "services.winwork.list_proposals", AsyncMock(return_value=(rows, 42))
    )

    r = await client.get("/api/v1/winwork/proposals", params={"page": 2, "per_page": 3})

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["data"]) == 3
    # `paginated()` envelope surfaces total on meta
    assert body["meta"]["total"] == 42
    assert body["meta"]["page"] == 2
    assert body["meta"]["per_page"] == 3


async def test_get_proposal_returns_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(
        "services.winwork.get_proposal", AsyncMock(return_value=None)
    )
    r = await client.get(f"/api/v1/winwork/proposals/{uuid4()}")
    assert r.status_code == 404


async def test_get_proposal_returns_envelope(client, monkeypatch):
    proposal = _make_proposal()
    monkeypatch.setattr(
        "services.winwork.get_proposal", AsyncMock(return_value=proposal)
    )
    r = await client.get(f"/api/v1/winwork/proposals/{proposal.id}")
    assert r.status_code == 200
    assert r.json()["data"]["id"] == str(proposal.id)


async def test_create_proposal_passes_org_and_user_context(client, monkeypatch, fake_auth):
    proposal = _make_proposal()
    create_mock = AsyncMock(return_value=proposal)
    monkeypatch.setattr("services.winwork.create_proposal", create_mock)

    r = await client.post(
        "/api/v1/winwork/proposals",
        json={"title": "New proposal", "status": "draft"},
    )

    # `create_proposal_route` is declared with `status_code=201`
    assert r.status_code == 201
    # service called with (session, org_id, user_id, payload)
    args = create_mock.call_args.args
    assert args[1] == fake_auth.organization_id
    assert args[2] == fake_auth.user_id
    assert args[3].title == "New proposal"


async def test_update_proposal_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(
        "services.winwork.update_proposal", AsyncMock(return_value=None)
    )
    r = await client.patch(
        f"/api/v1/winwork/proposals/{uuid4()}",
        json={"title": "rename"},
    )
    assert r.status_code == 404


async def test_mark_outcome_returns_updated_proposal(client, monkeypatch):
    won = _make_proposal(status="won")
    monkeypatch.setattr(
        "services.winwork.mark_outcome", AsyncMock(return_value=won)
    )
    r = await client.patch(
        f"/api/v1/winwork/proposals/{won.id}/outcome",
        json={"status": "won", "actual_fee_vnd": 500_000_000},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "won"


async def test_send_proposal_surfaces_value_error_as_400(client, monkeypatch):
    proposal = _make_proposal()
    monkeypatch.setattr(
        "services.winwork.get_proposal", AsyncMock(return_value=proposal)
    )
    monkeypatch.setattr(
        "services.winwork.send_proposal_email",
        AsyncMock(side_effect=ValueError("missing_client_email")),
    )

    r = await client.post(
        f"/api/v1/winwork/proposals/{proposal.id}/send",
        json={"subject": "Please review"},
    )
    assert r.status_code == 400
    assert "missing_client_email" in r.text


async def test_send_proposal_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(
        "services.winwork.get_proposal", AsyncMock(return_value=None)
    )
    r = await client.post(
        f"/api/v1/winwork/proposals/{uuid4()}/send",
        json={},
    )
    assert r.status_code == 404


# ============================================================
# AI generation
# ============================================================

async def test_generate_proposal_delegates_to_pipeline(client, monkeypatch, fake_auth):
    import sys
    from types import ModuleType
    from unittest.mock import AsyncMock as _AM

    # Stub `pipelines.winwork` — imported lazily inside the handler. We only
    # need `run_proposal_pipeline`.
    ai_job_id = uuid4()
    fake_mod = ModuleType("pipelines.winwork")
    fake_mod.run_proposal_pipeline = _AM(
        return_value={
            "ai_job_id": ai_job_id,
            "title": "AI drafted",
            "scope": {"items": []},
            "fees": {"lines": [], "subtotal_vnd": 0, "vat_vnd": 0, "total_vnd": 0},
            "ai_confidence": 0.8,
        }
    )
    # Make sure the parent package exists so `from pipelines.winwork import ...`
    # resolves. Keep any existing `pipelines` module intact if the tree has it.
    if "pipelines" not in sys.modules:
        monkeypatch.setitem(sys.modules, "pipelines", ModuleType("pipelines"))
    monkeypatch.setitem(sys.modules, "pipelines.winwork", fake_mod)

    proposal = _make_proposal(ai_generated=True)
    persist_mock = AsyncMock(return_value=proposal)
    monkeypatch.setattr("services.winwork.persist_generated_proposal", persist_mock)

    payload = {
        "project_type": "commercial_office",
        "area_sqm": 800,
        "floors": 3,
        "location": "Ho Chi Minh",
        "scope_items": ["schematic design", "permit drawings"],
        "client_brief": "Fit-out for a fintech HQ needing flexible open floors.",
        "discipline": "architecture",
    }
    r = await client.post("/api/v1/winwork/proposals/generate", json=payload)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["ai_job_id"] == str(ai_job_id)
    assert body["data"]["proposal"]["ai_generated"] is True
    # Pipeline was called with org_id + request payload
    call = fake_mod.run_proposal_pipeline.call_args
    assert call.kwargs["org_id"] == fake_auth.organization_id
    assert call.kwargs["request"].project_type == "commercial_office"


async def test_generate_proposal_rejects_short_brief(client):
    # client_brief has min_length=10
    r = await client.post(
        "/api/v1/winwork/proposals/generate",
        json={
            "project_type": "commercial_office",
            "area_sqm": 800,
            "floors": 3,
            "location": "Ho Chi Minh",
            "scope_items": ["schematic"],
            "client_brief": "too short",
            "discipline": "architecture",
        },
    )
    assert r.status_code == 422


# ============================================================
# Analytics
# ============================================================

async def test_win_rate_analytics_returns_envelope(client, monkeypatch):
    from schemas.winwork import WinRateAnalytics

    analytics = WinRateAnalytics(
        total=10, won=6, lost=3, pending=1,
        win_rate=0.6, avg_fee_vnd=300_000_000,
        by_project_type=[], by_month=[],
    )
    monkeypatch.setattr(
        "services.winwork.win_rate_analytics", AsyncMock(return_value=analytics)
    )
    r = await client.get("/api/v1/winwork/analytics/win-rate")
    assert r.status_code == 200
    assert r.json()["data"]["win_rate"] == 0.6
    assert r.json()["data"]["total"] == 10
