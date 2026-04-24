"""Router tests for BIDRADAR scrape + score flow.

Builds a minimal FastAPI app with only the bidradar router mounted, then
overrides `require_auth` and `get_db` the same way the shared conftest does.
This avoids importing the full `main.py` (which pulls in unrelated modules).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
    """Records adds; returns programmable execute() results."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self._get_map: dict[tuple[type, Any], Any] = {}
        self._execute_results: list[Any] = []

    def set_get(self, model: type, id_: Any, obj: Any) -> None:
        self._get_map[(model, id_)] = obj

    def push_execute(self, result: Any) -> None:
        self._execute_results.append(result)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...

    async def refresh(self, obj: Any) -> None:
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = datetime.now(timezone.utc)

    async def get(self, model: type, id_: Any) -> Any:
        return self._get_map.get((model, id_))

    async def execute(self, *_a: Any, **_k: Any) -> Any:
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
    from db.deps import get_db
    from middleware.auth import AuthContext, require_auth
    from routers import bidradar as bidradar_router

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="tester@example.com",
    )

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from fastapi import HTTPException

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(bidradar_router.router)

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


def _make_ai_rec():
    from schemas.bidradar import AIRecommendation, CompetitionLevel

    return AIRecommendation(
        match_score=78.0,
        estimated_value_vnd=5_000_000_000,
        competition_level=CompetitionLevel.moderate,
        win_probability=0.55,
        recommended_bid=True,
        reasoning="Past civic wins + full disciplines.",
        strengths=["Civic experience"],
        risks=["Short deadline"],
        required_capabilities=["BIM"],
    )


async def test_scrape_creates_tenders_and_matches(client, fake_db, monkeypatch):
    from models.bidradar import FirmProfile as FirmProfileModel

    profile = FirmProfileModel(
        id=uuid4(),
        organization_id=ORG_ID,
        disciplines=["architecture"],
        project_types=["civic"],
        provinces=["HCMC"],
        min_budget_vnd=1_000_000_000,
        max_budget_vnd=20_000_000_000,
        team_size=30,
        active_capacity_pct=50.0,
        past_wins=[],
        keywords=[],
        updated_at=datetime.now(timezone.utc),
    )

    scraped_items = [
        {
            "external_id": "VN-TENDER-001",
            "title": "Cải tạo trụ sở UBND Quận 1",
            "issuer": "UBND Quận 1",
            "type": "design",
            "budget_vnd": 6_000_000_000,
            "currency": "VND",
            "country_code": "VN",
            "province": "HCMC",
            "disciplines": ["architecture"],
            "project_types": ["civic"],
            "submission_deadline": None,
            "published_at": None,
            "description": "HQ renovation",
            "raw_url": "https://muasamcong.mpi.gov.vn/tender/001",
            "raw_payload": {},
        }
    ]

    monkeypatch.setattr(
        "ml.pipelines.bidradar.scrape_source",
        AsyncMock(return_value=scraped_items),
    )
    monkeypatch.setattr(
        "routers.bidradar.scrape_source",
        AsyncMock(return_value=scraped_items),
    )
    monkeypatch.setattr(
        "routers.bidradar.score_tender_for_firm",
        AsyncMock(return_value=_make_ai_rec()),
    )

    inserted_tender_id = uuid4()
    insert_result = MagicMock()
    insert_result.first.return_value = (inserted_tender_id, datetime.now(timezone.utc))
    fake_db.push_execute(insert_result)

    profile_q = MagicMock()
    profile_q.scalar_one_or_none.return_value = profile
    fake_db.push_execute(profile_q)

    existing_q = MagicMock()
    existing_q.scalars.return_value.all.return_value = []
    fake_db.push_execute(existing_q)

    tenders_q = MagicMock()
    tenders_q.scalars.return_value.all.return_value = [
        SimpleNamespace(
            id=inserted_tender_id,
            title=scraped_items[0]["title"],
            description=scraped_items[0]["description"],
            issuer=scraped_items[0]["issuer"],
            type="design",
            budget_vnd=scraped_items[0]["budget_vnd"],
            province="HCMC",
            disciplines=["architecture"],
            project_types=["civic"],
        )
    ]
    fake_db.push_execute(tenders_q)

    res = await client.post(
        "/api/v1/bidradar/scrape",
        json={"source": "mua-sam-cong.gov.vn", "max_pages": 1},
    )

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["source"] == "mua-sam-cong.gov.vn"
    assert data["tenders_found"] == 1
    assert data["new_tenders"] == 1
    assert data["matches_created"] == 1

    from models.bidradar import TenderMatch

    matches = [m for m in fake_db.added if isinstance(m, TenderMatch)]
    assert len(matches) == 1
    assert matches[0].match_score == 78.0
    assert matches[0].recommended_bid is True
    assert matches[0].organization_id == ORG_ID


async def test_score_requires_firm_profile(client, fake_db):
    profile_q = MagicMock()
    profile_q.scalar_one_or_none.return_value = None
    fake_db.push_execute(profile_q)

    res = await client.post("/api/v1/bidradar/score", json={"rescore_existing": False})
    assert res.status_code == 400
    assert "Firm profile required" in res.json()["errors"][0]["message"]


async def test_update_match_status_sets_reviewer(client, fake_db):
    from models.bidradar import TenderMatch

    match = TenderMatch(
        id=uuid4(),
        organization_id=ORG_ID,
        tender_id=uuid4(),
        status="new",
        match_score=75.0,
    )

    q = MagicMock()
    q.scalar_one_or_none.return_value = match
    fake_db.push_execute(q)

    res = await client.patch(
        f"/api/v1/bidradar/matches/{match.id}/status",
        json={"status": "saved"},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["status"] == "saved"
    assert match.reviewed_by == USER_ID
    assert match.reviewed_at is not None


async def test_create_proposal_returns_winwork_url(client, fake_db):
    from models.bidradar import TenderMatch
    from models.winwork import Proposal as ProposalModel

    tender_id = uuid4()
    match = TenderMatch(
        id=uuid4(),
        organization_id=ORG_ID,
        tender_id=tender_id,
        status="new",
        proposal_id=None,
    )
    tender = SimpleNamespace(
        id=tender_id,
        title="Cải tạo trụ sở UBND Quận 1",
        issuer="UBND Quận 1",
        submission_deadline=datetime(2026, 6, 1, tzinfo=timezone.utc),
        raw_url="https://muasamcong.mpi.gov.vn/tender/001",
        description="HQ renovation scope.",
        budget_vnd=6_000_000_000,
        currency="VND",
    )

    q = MagicMock()
    q.first.return_value = (match, tender)
    fake_db.push_execute(q)

    res = await client.post(f"/api/v1/bidradar/matches/{match.id}/create-proposal")
    assert res.status_code == 200
    data = res.json()["data"]
    assert str(tender_id) in data["winwork_url"]
    assert data["proposal_id"]
    assert match.status == "pursuing"
    assert match.proposal_id is not None

    # The bidradar → winwork handoff now seeds a real proposals row so the
    # target URL renders instead of 404'ing.
    seeded = [p for p in fake_db.added if isinstance(p, ProposalModel)]
    assert len(seeded) == 1
    seed = seeded[0]
    assert seed.id == match.proposal_id
    assert seed.organization_id == ORG_ID
    assert seed.title.startswith("Proposal — ")
    assert seed.client_name == "UBND Quận 1"
    assert seed.total_fee_vnd == 6_000_000_000
    assert seed.notes and "HQ renovation scope." in seed.notes


async def test_create_proposal_is_idempotent_when_match_has_proposal(client, fake_db):
    """Re-clicking 'Create proposal' must not re-seed a new draft."""
    from models.bidradar import TenderMatch
    from models.winwork import Proposal as ProposalModel

    tender_id = uuid4()
    existing_proposal_id = uuid4()
    match = TenderMatch(
        id=uuid4(),
        organization_id=ORG_ID,
        tender_id=tender_id,
        status="pursuing",
        proposal_id=existing_proposal_id,
    )
    tender = SimpleNamespace(
        id=tender_id,
        title="Anything",
        issuer=None,
        submission_deadline=None,
        raw_url=None,
        description=None,
        budget_vnd=None,
        currency="VND",
    )

    q = MagicMock()
    q.first.return_value = (match, tender)
    fake_db.push_execute(q)

    res = await client.post(f"/api/v1/bidradar/matches/{match.id}/create-proposal")
    assert res.status_code == 200
    data = res.json()["data"]
    assert UUID(data["proposal_id"]) == existing_proposal_id
    seeded = [p for p in fake_db.added if isinstance(p, ProposalModel)]
    assert seeded == []
