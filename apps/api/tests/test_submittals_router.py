"""Router tests for /api/v1/submittals/* and the RFI AI endpoints.

Same pattern as the schedulepilot tests: TenantAwareSession is replaced
with a queued-result session, and `ml.pipelines.rfi` is stubbed at the
sys.modules level so we don't need openai/langchain installed.
"""
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


def _scalar(value: Any) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = value
    r.scalar_one_or_none.return_value = value
    return r


class _ProgrammableSession:
    def __init__(self) -> None:
        self._queue: list[Any] = []

    def queue(self, result: Any) -> _ProgrammableSession:
        self._queue.append(result)
        return self

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        if self._queue:
            return self._queue.pop(0)
        # Default: empty result so unprogrammed paths don't blow up.
        r = MagicMock()
        r.one.side_effect = AssertionError("unprogrammed .one()")
        r.one_or_none.return_value = None
        r.all.return_value = []
        r.scalar_one.return_value = 0
        r.scalar_one_or_none.return_value = None
        r.rowcount = 0
        return r

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


@pytest.fixture
def patch_session(monkeypatch):
    s = _ProgrammableSession()

    class _Fake:
        def __init__(self, _org_id: Any) -> None: ...
        async def __aenter__(self):
            return s

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr("routers.submittals.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def patch_pipeline(monkeypatch):
    mod = ModuleType("ml.pipelines.rfi")
    mod.upsert_rfi_embedding = AsyncMock(return_value="openai/text-embedding-3-large")
    mod.find_similar_rfis = AsyncMock(return_value=[])
    mod.draft_rfi_response = AsyncMock(
        return_value={
            "draft_text": "Vui lòng tham khảo bản vẽ A-101.",
            "citations": [
                {
                    "chunk_id": str(uuid4()),
                    "document_id": str(uuid4()),
                    "page_number": 1,
                    "snippet": "Door schedule, Type D-12...",
                    "drawing_number": "A-101",
                    "discipline": "architectural",
                }
            ],
            "model_version": "rfi-draft/test",
        }
    )
    for parent in ("ml", "ml.pipelines"):
        if parent not in sys.modules:
            monkeypatch.setitem(sys.modules, parent, ModuleType(parent))
    monkeypatch.setitem(sys.modules, "ml.pipelines.rfi", mod)
    return mod


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import submittals as router_mod

    auth = AuthContext(
        user_id=USER_ID, organization_id=ORG_ID, role="admin", email="t@example.com"
    )
    a = FastAPI()
    a.add_exception_handler(HTTPException, http_exception_handler)
    a.add_exception_handler(Exception, unhandled_exception_handler)
    a.include_router(router_mod.router)
    a.dependency_overrides[require_auth] = lambda: auth
    return a


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def _submittal_row(**overrides: Any) -> SimpleNamespace:
    base = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        package_number="S-001",
        title="Concrete mix design",
        description="3000psi mix",
        submittal_type="shop_drawing",
        spec_section="03 30 00",
        csi_division="03",
        status="pending_review",
        current_revision=1,
        ball_in_court="designer",
        contractor_id=None,
        submitted_by=USER_ID,
        due_date=None,
        submitted_at=None,
        closed_at=None,
        notes=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return _make_row(**base)


# =============================================================================
# Submittals
# =============================================================================


async def test_create_submittal_auto_assigns_number_and_seeds_revision(
    client, patch_session
):
    # 1: SELECT for next package_number → 1; 2: INSERT submittal RETURNING; 3: INSERT first revision
    patch_session.queue(_scalar(1))
    patch_session.queue(_result(_submittal_row(package_number="S-001")))
    patch_session.queue(_result(None))  # rev INSERT — no RETURNING used

    resp = await client.post(
        "/api/v1/submittals",
        json={
            "project_id": str(PROJECT_ID),
            "title": "Concrete mix design",
            "submittal_type": "shop_drawing",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["package_number"] == "S-001"
    assert resp.json()["data"]["current_revision"] == 1


async def test_get_submittal_404_when_missing(client, patch_session):
    patch_session.queue(_result(None))

    resp = await client.get(f"/api/v1/submittals/{uuid4()}")
    assert resp.status_code == 404


async def test_review_revision_propagates_to_parent_state(client, patch_session):
    sid = uuid4()
    rev_id = uuid4()
    rev = _make_row(
        id=rev_id,
        organization_id=ORG_ID,
        submittal_id=sid,
        revision_number=1,
        file_id=None,
        review_status="approved_as_noted",
        reviewer_id=USER_ID,
        reviewed_at=datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
        reviewer_notes="Subject to as-noted comments",
        annotations=[],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    patch_session.queue(_result(rev))    # UPDATE rev RETURNING
    patch_session.queue(_result(None))   # UPDATE submittal

    resp = await client.post(
        f"/api/v1/submittals/revisions/{rev_id}/review",
        json={
            "review_status": "approved_as_noted",
            "reviewer_notes": "Subject to as-noted comments",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["review_status"] == "approved_as_noted"


# =============================================================================
# RFI AI
# =============================================================================


async def test_similar_rfis_requires_existing_embedding(client, patch_session):
    rid = uuid4()
    # 1: SELECT rfi → exists; 2: SELECT rfi_embedding → None
    patch_session.queue(_result(_make_row(id=rid, project_id=PROJECT_ID)))
    patch_session.queue(_result(None))

    resp = await client.post(
        f"/api/v1/submittals/rfis/{rid}/similar",
        json={"limit": 5},
    )
    assert resp.status_code == 422
    assert "embedded" in resp.json()["errors"][0]["message"].lower()


async def test_similar_rfis_returns_pipeline_results(
    client, patch_session, patch_pipeline
):
    rid = uuid4()
    other = uuid4()
    patch_pipeline.find_similar_rfis.return_value = [
        {
            "rfi_id": other,
            "number": "RFI-042",
            "subject": "Door schedule clarification",
            "status": "answered",
            "distance": 0.21,
            "created_at": datetime(2026, 2, 1, tzinfo=UTC),
        }
    ]
    patch_session.queue(_result(_make_row(id=rid, project_id=PROJECT_ID)))
    patch_session.queue(
        _result(_make_row(model_version="openai/text-embedding-3-large"))
    )

    resp = await client.post(
        f"/api/v1/submittals/rfis/{rid}/similar",
        json={"limit": 5, "max_distance": 0.5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["embedding_model"] == "openai/text-embedding-3-large"
    assert len(body["results"]) == 1
    assert body["results"][0]["number"] == "RFI-042"
    assert body["results"][0]["distance"] == pytest.approx(0.21)


async def test_draft_rfi_response_persists_draft_with_citations(
    client, patch_session, patch_pipeline
):
    rid = uuid4()
    # cache_minutes=0 so the cache-lookup branch is skipped:
    # 1: SELECT rfi; 2: INSERT draft RETURNING
    patch_session.queue(
        _result(
            _make_row(
                id=rid,
                project_id=PROJECT_ID,
                subject="Wall finish at lobby",
                description="Spec calls for two finishes — which to use?",
                response=None,
            )
        )
    )
    patch_session.queue(
        _result(
            _make_row(
                id=uuid4(),
                organization_id=ORG_ID,
                rfi_id=rid,
                draft_text="Vui lòng tham khảo bản vẽ A-101.",
                citations=[{"chunk_id": str(uuid4()), "document_id": str(uuid4()),
                            "page_number": 1, "snippet": "Door schedule",
                            "drawing_number": "A-101", "discipline": "architectural"}],
                model_version="rfi-draft/test",
                generated_at=datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
                accepted_at=None,
                accepted_by=None,
                notes=None,
            )
        )
    )

    resp = await client.post(
        f"/api/v1/submittals/rfis/{rid}/draft", json={"cache_minutes": 0}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert "A-101" in body["draft_text"]
    assert body["citations"][0]["drawing_number"] == "A-101"
    patch_pipeline.draft_rfi_response.assert_awaited_once()


async def test_draft_uses_cache_when_recent(
    client, patch_session, patch_pipeline
):
    rid = uuid4()
    # Cache hit on the first execute — no LLM, no insert.
    cached = _make_row(
        id=uuid4(),
        organization_id=ORG_ID,
        rfi_id=rid,
        draft_text="cached",
        citations=[],
        model_version="rfi-draft/cached",
        generated_at=datetime(2026, 4, 26, 11, 30, tzinfo=UTC),
        accepted_at=None,
        accepted_by=None,
        notes=None,
    )
    patch_session.queue(_result(cached))

    resp = await client.post(
        f"/api/v1/submittals/rfis/{rid}/draft", json={"cache_minutes": 60}
    )
    # Endpoint is declared with status_code=201; FastAPI uses that even on
    # cache hit (the body still contains the cached draft).
    assert resp.status_code == 201
    assert resp.json()["data"]["draft_text"] == "cached"
    patch_pipeline.draft_rfi_response.assert_not_awaited()


async def test_accept_draft_promotes_text_to_rfi(client, patch_session):
    did = uuid4()
    rid = uuid4()
    draft = _make_row(
        id=did,
        organization_id=ORG_ID,
        rfi_id=rid,
        draft_text="Use Type D-12 doors per spec.",
        citations=[],
        model_version="x",
        generated_at=datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
        accepted_at=datetime(2026, 4, 26, 12, 30, tzinfo=UTC),
        accepted_by=USER_ID,
        notes="LGTM",
    )
    patch_session.queue(_result(draft))   # UPDATE draft RETURNING
    patch_session.queue(_result(None))    # UPDATE rfis

    resp = await client.post(
        f"/api/v1/submittals/drafts/{did}/accept",
        json={"notes": "LGTM"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["accepted_by"] == str(USER_ID)
