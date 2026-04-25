"""Router-level tests for /api/v1/drawbridge/*.

The ML/RAG pipelines are mocked at their public entry points so these
tests verify HTTP wiring, persistence intent (rows added to the fake
session), and auth/tenant boundaries — not the LLM output.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.asyncio


PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")


# Local app fixture — mounts only the drawbridge router so a failure in an
# unrelated router (winwork, etc.) doesn't block collection. Overrides the
# shared `app` fixture in conftest.py which mounts codeguard.
@pytest.fixture
def app(fake_auth, fake_db) -> Iterator[FastAPI]:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from middleware.auth import require_auth
    from routers import drawbridge as drawbridge_router

    async def _override_db() -> AsyncIterator[Any]:
        yield fake_db

    test_app = FastAPI()
    test_app.add_exception_handler(HTTPException, http_exception_handler)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)
    test_app.include_router(drawbridge_router.router)
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


# ---------- helpers ----------

_UNSET = object()


def _make_document(
    *,
    organization_id: UUID,
    id_: UUID | None = None,
    file_id: UUID | None | object = _UNSET,
    project_id: UUID | None = PROJECT_ID,
    **overrides: Any,
):
    # `datetime.utcnow()` is deprecated in 3.12+ — prefer the tz-aware
    # constructor. `datetime.now(UTC)` keeps the same wall-clock value but
    # produces an aware datetime, which is what SQLAlchemy wants for
    # `TIMESTAMP WITH TIME ZONE` columns anyway.
    from datetime import UTC, datetime

    from models.drawbridge import Document as DocumentModel

    # `file_id=None` must stay None (for "no file" tests); omit to auto-generate.
    resolved_file_id = uuid4() if file_id is _UNSET else file_id

    doc = DocumentModel(
        id=id_ or uuid4(),
        organization_id=organization_id,
        project_id=project_id,
        file_id=resolved_file_id,
        discipline="architectural",
        doc_type="drawing",
        processing_status="ready",
        extracted_data={},
        created_at=datetime.now(UTC),
    )
    for k, v in overrides.items():
        setattr(doc, k, v)
    return doc


def _make_conflict(
    *,
    organization_id: UUID,
    id_: UUID | None = None,
    project_id: UUID | None = PROJECT_ID,
    status_: str = "open",
    **overrides: Any,
):
    from datetime import UTC, datetime

    from models.drawbridge import Conflict as ConflictModel

    c = ConflictModel(
        id=id_ or uuid4(),
        organization_id=organization_id,
        project_id=project_id,
        status=status_,
        severity="major",
        conflict_type="dimension",
        description="Floor thickness disagreement",
        detected_at=datetime.now(UTC),
    )
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


# ============================================================
# Q&A
# ============================================================

async def test_query_returns_answer_with_source_documents(
    client, fake_db, fake_auth, monkeypatch
):
    from schemas.drawbridge import QueryResponse, SourceDocument

    response = QueryResponse(
        answer="Độ dày sàn tầng 3 là 200mm.",
        confidence=0.87,
        source_documents=[
            SourceDocument(
                document_id=uuid4(),
                drawing_number="S-301",
                title="Structural Floor Plan L3",
                discipline="structural",
                page=2,
                excerpt="Slab thickness 200mm typ.",
                bbox={"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.05},
            )
        ],
        related_questions=["Chiều dày sàn tầng 2?"],
    )
    mock = AsyncMock(return_value=response)
    monkeypatch.setattr("ml.pipelines.drawbridge.answer_document_query", mock)

    res = await client.post(
        "/api/v1/drawbridge/query",
        json={
            "project_id": str(PROJECT_ID),
            "question": "Độ dày sàn tầng 3 là bao nhiêu?",
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["errors"] is None
    assert body["data"]["answer"].startswith("Độ dày")
    assert body["data"]["confidence"] == pytest.approx(0.87)
    assert len(body["data"]["source_documents"]) == 1
    src = body["data"]["source_documents"][0]
    assert src["drawing_number"] == "S-301"
    assert src["discipline"] == "structural"

    mock.assert_awaited_once()
    kwargs = mock.await_args.kwargs
    assert kwargs["organization_id"] == fake_auth.organization_id
    assert kwargs["project_id"] == PROJECT_ID
    assert kwargs["question"].startswith("Độ dày")


async def test_query_rejects_short_question(client):
    res = await client.post(
        "/api/v1/drawbridge/query",
        json={"project_id": str(PROJECT_ID), "question": "hi"},
    )
    assert res.status_code == 422


async def test_query_surfaces_pipeline_failure_as_502(client, monkeypatch):
    mock = AsyncMock(side_effect=RuntimeError("LLM timeout"))
    monkeypatch.setattr("ml.pipelines.drawbridge.answer_document_query", mock)

    res = await client.post(
        "/api/v1/drawbridge/query",
        json={
            "project_id": str(PROJECT_ID),
            "question": "What is the slab thickness on L3?",
        },
    )
    assert res.status_code == 502
    assert res.json()["errors"][0]["message"].startswith("Q&A pipeline failed")


# ============================================================
# Conflict scan
# ============================================================

async def test_conflict_scan_delegates_to_pipeline(
    client, fake_db, fake_auth, monkeypatch
):
    from schemas.drawbridge import ConflictScanResponse

    pipeline_result = ConflictScanResponse(
        project_id=PROJECT_ID,
        scanned_documents=4,
        candidates_evaluated=12,
        conflicts_found=2,
        conflicts=[],
    )
    mock = AsyncMock(return_value=pipeline_result)
    monkeypatch.setattr("ml.pipelines.drawbridge.run_conflict_scan", mock)

    res = await client.post(
        "/api/v1/drawbridge/conflict-scan",
        json={"project_id": str(PROJECT_ID)},
    )

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["scanned_documents"] == 4
    assert body["conflicts_found"] == 2

    mock.assert_awaited_once()
    kwargs = mock.await_args.kwargs
    assert kwargs["organization_id"] == fake_auth.organization_id
    assert kwargs["project_id"] == PROJECT_ID
    assert kwargs["raised_by"] == fake_auth.user_id


async def test_conflict_scan_pipeline_error_returns_502(client, monkeypatch):
    mock = AsyncMock(side_effect=RuntimeError("embedding provider down"))
    monkeypatch.setattr("ml.pipelines.drawbridge.run_conflict_scan", mock)

    res = await client.post(
        "/api/v1/drawbridge/conflict-scan",
        json={"project_id": str(PROJECT_ID)},
    )
    assert res.status_code == 502
    assert "Conflict scan failed" in res.json()["errors"][0]["message"]


# ============================================================
# Conflict update
# ============================================================

async def test_update_conflict_sets_resolved_fields(client, fake_db, fake_auth):
    conflict = _make_conflict(organization_id=fake_auth.organization_id)
    from models.drawbridge import Conflict as ConflictModel

    fake_db.set_get(ConflictModel, conflict.id, conflict)

    res = await client.patch(
        f"/api/v1/drawbridge/conflicts/{conflict.id}",
        json={"status": "resolved", "resolution_notes": "Updated per RFI-0001"},
    )
    assert res.status_code == 200
    assert conflict.status == "resolved"
    assert conflict.resolution_notes == "Updated per RFI-0001"
    assert conflict.resolved_by == fake_auth.user_id


async def test_update_conflict_cross_tenant_is_404(client, fake_db, fake_auth):
    other_org = UUID("99999999-9999-9999-9999-999999999999")
    assert other_org != fake_auth.organization_id
    conflict = _make_conflict(organization_id=other_org)
    from models.drawbridge import Conflict as ConflictModel

    fake_db.set_get(ConflictModel, conflict.id, conflict)

    res = await client.patch(
        f"/api/v1/drawbridge/conflicts/{conflict.id}",
        json={"status": "dismissed"},
    )
    assert res.status_code == 404


# ============================================================
# Document file shortcut
# ============================================================

async def test_document_file_redirect_points_at_files_download(
    client, fake_db, fake_auth
):
    doc = _make_document(organization_id=fake_auth.organization_id)
    from models.drawbridge import Document as DocumentModel

    fake_db.set_get(DocumentModel, doc.id, doc)

    res = await client.get(
        f"/api/v1/drawbridge/documents/{doc.id}/file",
        follow_redirects=False,
    )
    assert res.status_code == 307
    assert res.headers["location"] == f"/api/v1/files/{doc.file_id}/download"


async def test_document_file_missing_file_id_returns_404(
    client, fake_db, fake_auth
):
    doc = _make_document(organization_id=fake_auth.organization_id, file_id=None)
    from models.drawbridge import Document as DocumentModel

    fake_db.set_get(DocumentModel, doc.id, doc)

    res = await client.get(
        f"/api/v1/drawbridge/documents/{doc.id}/file",
        follow_redirects=False,
    )
    assert res.status_code == 404


async def test_document_file_cross_tenant_is_404(client, fake_db, fake_auth):
    other_org = UUID("99999999-9999-9999-9999-999999999999")
    doc = _make_document(organization_id=other_org)
    from models.drawbridge import Document as DocumentModel

    fake_db.set_get(DocumentModel, doc.id, doc)

    res = await client.get(
        f"/api/v1/drawbridge/documents/{doc.id}/file",
        follow_redirects=False,
    )
    assert res.status_code == 404


# ============================================================
# Extraction
# ============================================================

async def test_extract_delegates_to_pipeline(
    client, fake_db, fake_auth, monkeypatch
):
    from schemas.drawbridge import ExtractedSchedule, ExtractResponse

    doc = _make_document(organization_id=fake_auth.organization_id)
    from models.drawbridge import Document as DocumentModel

    fake_db.set_get(DocumentModel, doc.id, doc)

    response = ExtractResponse(
        document_id=doc.id,
        schedules=[
            ExtractedSchedule(
                name="Door Schedule",
                page=5,
                columns=["Tag", "Width", "Height"],
                rows=[{"cells": {"Tag": "D01", "Width": 900, "Height": 2100}}],
            )
        ],
        dimensions=[],
        materials=[],
        title_block=None,
    )
    mock = AsyncMock(return_value=response)
    monkeypatch.setattr("ml.pipelines.drawbridge.extract_document_data", mock)

    res = await client.post(
        "/api/v1/drawbridge/extract",
        json={"document_id": str(doc.id), "target": "schedule"},
    )
    assert res.status_code == 200
    body = res.json()["data"]
    assert len(body["schedules"]) == 1
    assert body["schedules"][0]["name"] == "Door Schedule"


# ============================================================
# RFI generation from conflict
# ============================================================

async def test_generate_rfi_creates_rfi_row_from_draft(
    client, fake_db, fake_auth, monkeypatch
):
    from schemas.drawbridge import RfiDraft
    from models.drawbridge import Conflict as ConflictModel
    from models.drawbridge import Rfi as RfiModel

    conflict = _make_conflict(organization_id=fake_auth.organization_id)
    fake_db.set_get(ConflictModel, conflict.id, conflict)

    # `_next_rfi_number` runs a COUNT query; return 0 so numbering starts at 0001.
    from unittest.mock import MagicMock

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    fake_db.set_execute_result(count_result)

    draft = RfiDraft(
        subject="Clarify slab thickness at L3 grid A-B/3-5",
        description="A-301 shows 200mm; S-301 shows 250mm. Please confirm.",
        related_document_ids=[uuid4(), uuid4()],
    )
    mock = AsyncMock(return_value=draft)
    monkeypatch.setattr("ml.pipelines.drawbridge.draft_rfi_from_conflict", mock)

    res = await client.post(
        "/api/v1/drawbridge/rfis/generate",
        json={"conflict_id": str(conflict.id)},
    )

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["subject"].startswith("Clarify slab")
    assert body["priority"] == "high"

    rfis = [r for r in fake_db.added if isinstance(r, RfiModel)]
    assert len(rfis) == 1
    rfi = rfis[0]
    assert rfi.organization_id == fake_auth.organization_id
    assert rfi.project_id == conflict.project_id
    assert rfi.raised_by == fake_auth.user_id
    assert rfi.subject.startswith("Clarify slab")
    assert len(rfi.related_document_ids) == 2
    # _next_rfi_number formats as RFI-NNNN
    assert rfi.number.startswith("RFI-")


async def test_generate_rfi_cross_tenant_is_404(client, fake_db, fake_auth):
    from models.drawbridge import Conflict as ConflictModel

    other_org = UUID("99999999-9999-9999-9999-999999999999")
    conflict = _make_conflict(organization_id=other_org)
    fake_db.set_get(ConflictModel, conflict.id, conflict)

    res = await client.post(
        "/api/v1/drawbridge/rfis/generate",
        json={"conflict_id": str(conflict.id)},
    )
    assert res.status_code == 404
