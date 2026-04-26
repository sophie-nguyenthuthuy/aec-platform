"""Router tests for /api/v1/changeorder/*. Same pattern as schedulepilot."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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

    monkeypatch.setattr("routers.changeorder.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def patch_pipeline(monkeypatch):
    mod = ModuleType("ml.pipelines.changeorder")
    mod._EXTRACT_MODEL_VERSION = "co-extract/test"
    mod.extract_candidates = AsyncMock(
        return_value=[
            {
                "title": "Đổi vật liệu cửa",
                "description": "Substitute door type D-12 with D-15",
                "line_items": [
                    {
                        "description": "Cửa D-15",
                        "line_kind": "substitute",
                        "spec_section": "08 14 16",
                        "quantity": 12,
                        "unit": "ea",
                        "unit_cost_vnd": 1_500_000,
                        "cost_vnd": 18_000_000,
                        "schedule_impact_days": 3,
                    }
                ],
                "cost_impact_vnd_estimate": 18_000_000,
                "schedule_impact_days_estimate": 3,
                "confidence_pct": 75,
                "rationale": "Spec mismatch in RFI-042",
            }
        ]
    )
    mod.analyze_impact = AsyncMock(
        return_value={
            "cost_impact_vnd": 18_000_000,
            "schedule_impact_days": 3,
            "rollup_method": "sum_cost+max_days",
            "assumptions": ["No parallel execution"],
            "confidence_pct": 80,
            "summary": "Substituting doors adds 3 days.",
            "model_version": "co-analyze/test",
        }
    )
    for parent in ("ml", "ml.pipelines"):
        if parent not in sys.modules:
            monkeypatch.setitem(sys.modules, parent, ModuleType(parent))
    monkeypatch.setitem(sys.modules, "ml.pipelines.changeorder", mod)
    return mod


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import changeorder as router_mod

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


def _co_row(**overrides: Any) -> SimpleNamespace:
    base = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        number="CO-001",
        title="Door substitution",
        description="Owner-requested change",
        status="draft",
        initiator="Owner",
        cost_impact_vnd=18_000_000,
        schedule_impact_days=3,
        ai_analysis=None,
        submitted_at=None,
        approved_at=None,
        approved_by=None,
        created_at=datetime(2026, 4, 26, tzinfo=UTC),
    )
    base.update(overrides)
    return _make_row(**base)


# =============================================================================
# Tests
# =============================================================================


async def test_create_co_auto_assigns_number_and_seeds_draft_approval(client, patch_session):
    # 1: SELECT next number → 1; 2: INSERT CO RETURNING; 3: INSERT initial approval
    patch_session.queue(_scalar(1))
    patch_session.queue(_result(_co_row(number="CO-001")))
    patch_session.queue(_result(None))

    resp = await client.post(
        "/api/v1/changeorder/cos",
        json={
            "project_id": str(PROJECT_ID),
            "title": "Door substitution",
            "description": "Owner-requested change",
            "cost_impact_vnd": 18_000_000,
            "schedule_impact_days": 3,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["number"] == "CO-001"
    assert resp.json()["data"]["status"] == "draft"


async def test_record_approval_advances_status_and_logs(client, patch_session):
    cid = uuid4()
    # 1: SELECT current status; 2: INSERT approval RETURNING; 3: UPDATE CO status
    patch_session.queue(_result(_make_row(status="submitted")))
    patch_session.queue(
        _result(
            _make_row(
                id=uuid4(),
                organization_id=ORG_ID,
                change_order_id=cid,
                from_status="submitted",
                to_status="approved",
                actor_id=USER_ID,
                notes="LGTM after review",
                created_at=datetime(2026, 4, 26, 12, tzinfo=UTC),
            )
        )
    )
    patch_session.queue(_result(None))

    resp = await client.post(
        f"/api/v1/changeorder/cos/{cid}/approvals",
        json={"to_status": "approved", "notes": "LGTM after review"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["from_status"] == "submitted"
    assert resp.json()["data"]["to_status"] == "approved"


async def test_extract_requires_rfi_or_text(client, patch_session, patch_pipeline):
    resp = await client.post(
        "/api/v1/changeorder/extract",
        json={"project_id": str(PROJECT_ID)},
    )
    assert resp.status_code == 400
    patch_pipeline.extract_candidates.assert_not_awaited()


async def test_extract_persists_candidates_for_pasted_text(client, patch_session, patch_pipeline):
    cand_row = _make_row(
        id=uuid4(),
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        source_kind="manual_paste",
        source_rfi_id=None,
        source_text_snippet="Owner email about door substitution",
        proposal={
            "title": "Đổi vật liệu cửa",
            "description": "Substitute door type D-12 with D-15",
            "cost_impact_vnd_estimate": 18_000_000,
            "schedule_impact_days_estimate": 3,
            "confidence_pct": 75,
            "rationale": "Spec mismatch",
        },
        model_version="co-extract/test",
        accepted_co_id=None,
        accepted_at=None,
        rejected_at=None,
        rejected_reason=None,
        actor_id=USER_ID,
        created_at=datetime(2026, 4, 26, 12, tzinfo=UTC),
    )
    patch_session.queue(_result(cand_row))  # INSERT candidate RETURNING

    resp = await client.post(
        "/api/v1/changeorder/extract",
        json={
            "project_id": str(PROJECT_ID),
            "text": "Owner email about door substitution",
            "source_kind": "manual_paste",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["proposal"]["title"] == "Đổi vật liệu cửa"
    patch_pipeline.extract_candidates.assert_awaited_once()


async def test_accept_candidate_creates_co_and_links_back(client, patch_session, patch_pipeline):
    cand_id = uuid4()
    new_co_id = uuid4()
    cand_row = _make_row(
        id=cand_id,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        source_kind="rfi",
        source_rfi_id=uuid4(),
        source_text_snippet="snippet",
        proposal={
            "title": "Đổi cửa",
            "description": "desc",
            "line_items": [
                {
                    "description": "Cửa D-15",
                    "line_kind": "substitute",
                    "cost_vnd": 18_000_000,
                    "schedule_impact_days": 3,
                }
            ],
            "cost_impact_vnd_estimate": 18_000_000,
            "schedule_impact_days_estimate": 3,
        },
        model_version="x",
        accepted_co_id=None,
        accepted_at=None,
        rejected_at=None,
        rejected_reason=None,
        actor_id=USER_ID,
        created_at=datetime(2026, 4, 26, 12, tzinfo=UTC),
    )
    co_row = _co_row(id=new_co_id, number="CO-002")
    # 1: SELECT candidate; 2: SELECT next CO number → 2; 3: INSERT CO;
    # 4: INSERT line_item; 5: INSERT source backlink; 6: UPDATE candidate
    patch_session.queue(_result(cand_row))
    patch_session.queue(_scalar(2))
    patch_session.queue(_result(co_row))
    patch_session.queue(_result(None))
    patch_session.queue(_result(None))
    patch_session.queue(_result(None))

    resp = await client.post(f"/api/v1/changeorder/candidates/{cand_id}/accept", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["number"] == "CO-002"


async def test_analyze_impact_persists_and_returns_rollup(client, patch_session, patch_pipeline):
    cid = uuid4()
    co_row = _make_row(
        title="Door sub",
        description="x",
        cost_impact_vnd=None,
        schedule_impact_days=None,
        ai_analysis=None,
    )
    # 1: SELECT CO; 2: SELECT line items; 3: UPDATE CO with analysis
    patch_session.queue(_result(co_row))
    patch_session.queue(_result(rows=[]))
    patch_session.queue(_result(None))

    resp = await client.post(f"/api/v1/changeorder/cos/{cid}/analyze", json={"force": True})
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["cost_impact_vnd"] == 18_000_000
    assert body["schedule_impact_days"] == 3
    assert body["rollup_method"] == "sum_cost+max_days"
    patch_pipeline.analyze_impact.assert_awaited_once()
