"""FastAPI router for DRAWBRIDGE — document intelligence, conflict detection, RFIs."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import Envelope, Meta, ok, paginated
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from models.core import File as FileModel
from models.drawbridge import (
    Conflict as ConflictModel,
    Document as DocumentModel,
    DocumentChunk as DocumentChunkModel,
    DocumentSet as DocumentSetModel,
    Rfi as RfiModel,
)
from schemas.drawbridge import (
    Conflict,
    ConflictExcerpt,
    ConflictListFilters,
    ConflictScanRequest,
    ConflictScanResponse,
    ConflictStatus,
    ConflictUpdate,
    ConflictWithExcerpts,
    Discipline,
    Document,
    DocumentListFilters,
    DocumentSet,
    DocumentSetCreate,
    DocumentUpload,
    DocType,
    ExtractRequest,
    ExtractResponse,
    ProcessingStatus,
    QueryRequest,
    QueryResponse,
    Rfi,
    RfiAnswer,
    RfiCreate,
    RfiDraft,
    RfiGenerateFromConflictRequest,
    RfiListFilters,
    RfiPriority,
    RfiStatus,
    RfiUpdate,
)

router = APIRouter(prefix="/api/v1/drawbridge", tags=["drawbridge"])


# ============================================================
# Helpers
# ============================================================

def _dict(m: Any) -> dict[str, Any]:
    """Convert SQLAlchemy model to dict for pydantic validation."""
    return {c.name: getattr(m, c.name) for c in m.__table__.columns}


async def _storage_put(file_bytes: bytes, name: str, mime: str) -> str:
    """Upload to S3. Minimal implementation — swap for boto3 in production."""
    try:
        import boto3
        from core.config import get_settings

        settings = get_settings()
        key = f"drawbridge/{uuid4()}/{name}"
        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=file_bytes, ContentType=mime)
        return key
    except Exception:
        # Dev fallback: deterministic local key.
        digest = hashlib.sha256(file_bytes).hexdigest()[:16]
        return f"drawbridge/{digest}/{name}"


async def _load_conflict_excerpts(
    db: AsyncSession, conflict: ConflictModel
) -> tuple[ConflictExcerpt | None, ConflictExcerpt | None]:
    """Hydrate a conflict with side-by-side excerpts from both documents."""
    async def _one(doc_id: UUID | None, chunk_id: UUID | None) -> ConflictExcerpt | None:
        if doc_id is None:
            return None
        doc = await db.get(DocumentModel, doc_id)
        if doc is None:
            return None
        chunk = await db.get(DocumentChunkModel, chunk_id) if chunk_id else None
        return ConflictExcerpt(
            document_id=doc.id,
            drawing_number=doc.drawing_number,
            discipline=Discipline(doc.discipline) if doc.discipline else None,
            page=chunk.page_number if chunk else None,
            excerpt=(chunk.content if chunk else None) or (doc.title or ""),
            bbox=chunk.bbox if chunk else None,
        )

    a = await _one(conflict.document_a_id, conflict.chunk_a_id)
    b = await _one(conflict.document_b_id, conflict.chunk_b_id)
    return a, b


# ============================================================
# Documents
# ============================================================

@router.post("/documents/upload", response_model=Envelope[Document])
async def upload_document(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(...)],
    project_id: Annotated[UUID, Form(...)],
    document_set_id: Annotated[UUID | None, Form()] = None,
    doc_type: Annotated[DocType | None, Form()] = None,
    drawing_number: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    revision: Annotated[str | None, Form()] = None,
    discipline: Annotated[Discipline | None, Form()] = None,
    scale: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Upload a drawing/spec/report and trigger ingestion."""
    payload = DocumentUpload(
        project_id=project_id,
        document_set_id=document_set_id,
        doc_type=doc_type,
        drawing_number=drawing_number,
        title=title,
        revision=revision,
        discipline=discipline,
        scale=scale,
    )

    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")

    storage_key = await _storage_put(raw, file.filename or "document", file.content_type or "application/octet-stream")

    file_row = FileModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        name=file.filename or "document",
        storage_key=storage_key,
        mime_type=file.content_type,
        size_bytes=len(raw),
        source_module="drawbridge",
        processing_status="pending",
        created_by=auth.user_id,
    )
    db.add(file_row)
    await db.flush()

    doc = DocumentModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        document_set_id=payload.document_set_id,
        file_id=file_row.id,
        doc_type=payload.doc_type.value if payload.doc_type else None,
        drawing_number=payload.drawing_number,
        title=payload.title or (file.filename or None),
        revision=payload.revision,
        discipline=payload.discipline.value if payload.discipline else None,
        scale=payload.scale,
        processing_status=ProcessingStatus.pending.value,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Kick off ingestion asynchronously. In production: enqueue to Celery/RQ.
    try:
        from ml.pipelines.drawbridge import enqueue_ingest_document

        await enqueue_ingest_document(
            organization_id=auth.organization_id,
            document_id=doc.id,
            storage_key=storage_key,
            mime_type=file.content_type or "application/octet-stream",
        )
    except Exception:
        # Non-fatal: document row exists with status=pending, a worker can retry.
        pass

    return ok(Document.model_validate(doc).model_dump(mode="json"))


@router.get("/documents", response_model=Envelope[list[Document]])
async def list_documents(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID | None = None,
    document_set_id: UUID | None = None,
    discipline: Discipline | None = None,
    doc_type: DocType | None = None,
    processing_status: ProcessingStatus | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    stmt = select(DocumentModel).where(DocumentModel.organization_id == auth.organization_id)
    if project_id:
        stmt = stmt.where(DocumentModel.project_id == project_id)
    if document_set_id:
        stmt = stmt.where(DocumentModel.document_set_id == document_set_id)
    if discipline:
        stmt = stmt.where(DocumentModel.discipline == discipline.value)
    if doc_type:
        stmt = stmt.where(DocumentModel.doc_type == doc_type.value)
    if processing_status:
        stmt = stmt.where(DocumentModel.processing_status == processing_status.value)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                DocumentModel.title.ilike(like),
                DocumentModel.drawing_number.ilike(like),
            )
        )

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(DocumentModel.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return paginated(
        [Document.model_validate(r).model_dump(mode="json") for r in rows],
        page=offset // max(limit, 1),
        per_page=limit,
        total=total,
    )


@router.get("/documents/{document_id}", response_model=Envelope[Document])
async def get_document(
    document_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    doc = await db.get(DocumentModel, document_id)
    if doc is None or doc.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return ok(Document.model_validate(doc).model_dump(mode="json"))


@router.get("/documents/{document_id}/file")
async def get_document_file(
    document_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Redirect to the signed file URL for a document.

    Saves clients an extra round-trip: instead of `GET /documents/{id}` →
    read `file_id` → `GET /files/{file_id}/download`, they can hit this
    endpoint directly. Useful for the conflict detail PDF panes.
    """
    from fastapi.responses import RedirectResponse

    doc = await db.get(DocumentModel, document_id)
    if doc is None or doc.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if doc.file_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document has no file")
    # 307 preserves the GET verb and any auth headers the client forwards.
    return RedirectResponse(
        url=f"/api/v1/files/{doc.file_id}/download",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.get("/documents/{document_id}/file")
async def get_document_file(
    document_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    """Short-circuit to the shared `/api/v1/files/{file_id}/download` endpoint.

    UI components (PDFViewer, download buttons) render against a drawing record;
    this hop lets them use a stable drawbridge URL without knowing the file_id.
    """
    doc = await db.get(DocumentModel, document_id)
    if doc is None or doc.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if doc.file_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document has no file")
    return RedirectResponse(url=f"/api/v1/files/{doc.file_id}/download", status_code=307)


@router.delete("/documents/{document_id}", response_model=Envelope[dict])
async def delete_document(
    document_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    doc = await db.get(DocumentModel, document_id)
    if doc is None or doc.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    await db.delete(doc)
    await db.commit()
    return ok({"deleted": True})


# ---------- Document sets ----------

@router.post("/document-sets", response_model=Envelope[DocumentSet])
async def create_document_set(
    payload: DocumentSetCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    row = DocumentSetModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        name=payload.name,
        discipline=payload.discipline.value if payload.discipline else None,
        revision=payload.revision,
        issued_date=payload.issued_date,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(DocumentSet.model_validate(row).model_dump(mode="json"))


@router.get("/document-sets", response_model=Envelope[list[DocumentSet]])
async def list_document_sets(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID | None = None,
) -> dict[str, Any]:
    stmt = select(DocumentSetModel).where(DocumentSetModel.organization_id == auth.organization_id)
    if project_id:
        stmt = stmt.where(DocumentSetModel.project_id == project_id)
    rows = (await db.execute(stmt.order_by(DocumentSetModel.created_at.desc()))).scalars().all()
    return ok([DocumentSet.model_validate(r).model_dump(mode="json") for r in rows])


# ============================================================
# Q&A
# ============================================================

@router.post("/query", response_model=Envelope[QueryResponse])
async def drawbridge_query(
    payload: QueryRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Natural-language Q&A over project documents, with source highlights."""
    from ml.pipelines.drawbridge import answer_document_query

    try:
        response = await answer_document_query(
            db=db,
            organization_id=auth.organization_id,
            project_id=payload.project_id,
            question=payload.question,
            disciplines=payload.disciplines,
            document_ids=payload.document_ids,
            top_k=payload.top_k,
            language=payload.language,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Q&A pipeline failed: {exc}") from exc

    return ok(response.model_dump(mode="json"))


# ============================================================
# Conflict detection
# ============================================================

@router.post("/conflict-scan", response_model=Envelope[ConflictScanResponse])
async def conflict_scan(
    payload: ConflictScanRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Cross-discipline conflict scan. Persists detected conflicts."""
    from ml.pipelines.drawbridge import run_conflict_scan

    try:
        result = await run_conflict_scan(
            db=db,
            organization_id=auth.organization_id,
            project_id=payload.project_id,
            document_ids=payload.document_ids,
            severities=payload.severities,
            raised_by=auth.user_id,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Conflict scan failed: {exc}") from exc

    return ok(result.model_dump(mode="json"))


@router.get("/conflicts", response_model=Envelope[list[ConflictWithExcerpts]])
async def list_conflicts(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID = Query(...),
    status_filter: ConflictStatus | None = Query(default=None, alias="status"),
    severity: str | None = None,
    conflict_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    stmt = select(ConflictModel).where(
        and_(
            ConflictModel.organization_id == auth.organization_id,
            ConflictModel.project_id == project_id,
        )
    )
    if status_filter:
        stmt = stmt.where(ConflictModel.status == status_filter.value)
    if severity:
        stmt = stmt.where(ConflictModel.severity == severity)
    if conflict_type:
        stmt = stmt.where(ConflictModel.conflict_type == conflict_type)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(ConflictModel.detected_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()

    enriched = []
    for r in rows:
        a, b = await _load_conflict_excerpts(db, r)
        c = ConflictWithExcerpts.model_validate({**_dict(r), "document_a": a, "document_b": b})
        enriched.append(c.model_dump(mode="json"))

    return paginated(enriched, page=offset // max(limit, 1), per_page=limit, total=total)


@router.get("/conflicts/{conflict_id}", response_model=Envelope[ConflictWithExcerpts])
async def get_conflict(
    conflict_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    row = await db.get(ConflictModel, conflict_id)
    if row is None or row.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conflict not found")
    a, b = await _load_conflict_excerpts(db, row)
    return ok(
        ConflictWithExcerpts.model_validate({**_dict(row), "document_a": a, "document_b": b}).model_dump(mode="json")
    )


@router.patch("/conflicts/{conflict_id}", response_model=Envelope[Conflict])
async def update_conflict(
    conflict_id: UUID,
    payload: ConflictUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    row = await db.get(ConflictModel, conflict_id)
    if row is None or row.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conflict not found")

    if payload.status is not None:
        # `status` may arrive as an enum member or a raw string — normalise to str
        # so we can compare against the lifecycle states below and assign to the
        # `Text` column without surprises.
        status_value = payload.status.value if hasattr(payload.status, "value") else payload.status
        row.status = status_value
        if status_value in ("resolved", "dismissed"):
            row.resolved_at = datetime.now(timezone.utc)
            row.resolved_by = auth.user_id
        elif status_value == "open":
            row.resolved_at = None
            row.resolved_by = None
    if payload.resolution_notes is not None:
        row.resolution_notes = payload.resolution_notes

    await db.commit()
    await db.refresh(row)
    return ok(Conflict.model_validate(row).model_dump(mode="json"))


# ============================================================
# Extraction
# ============================================================

@router.post("/extract", response_model=Envelope[ExtractResponse])
async def extract_from_document(
    payload: ExtractRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Extract structured data (schedules, dimensions, materials, title block) from a drawing."""
    doc = await db.get(DocumentModel, payload.document_id)
    if doc is None or doc.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    from ml.pipelines.drawbridge import extract_document_data

    try:
        response = await extract_document_data(
            db=db,
            document_id=payload.document_id,
            target=payload.target,
            pages=payload.pages,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Extraction failed: {exc}") from exc

    # Persist into extracted_data for fast re-reads.
    doc.extracted_data = {
        **(doc.extracted_data or {}),
        "last_extract": response.model_dump(mode="json"),
    }
    await db.commit()
    return ok(response.model_dump(mode="json"))


# ============================================================
# RFIs
# ============================================================

@router.get("/rfis", response_model=Envelope[list[Rfi]])
async def list_rfis(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID = Query(...),
    status_filter: RfiStatus | None = Query(default=None, alias="status"),
    assigned_to: UUID | None = None,
    priority: RfiPriority | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    stmt = select(RfiModel).where(
        and_(
            RfiModel.organization_id == auth.organization_id,
            RfiModel.project_id == project_id,
        )
    )
    if status_filter:
        stmt = stmt.where(RfiModel.status == status_filter.value)
    if assigned_to:
        stmt = stmt.where(RfiModel.assigned_to == assigned_to)
    if priority:
        stmt = stmt.where(RfiModel.priority == priority.value)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(RfiModel.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return paginated(
        [Rfi.model_validate(r).model_dump(mode="json") for r in rows],
        page=offset // max(limit, 1),
        per_page=limit,
        total=total,
    )


@router.post("/rfis", response_model=Envelope[Rfi])
async def create_rfi(
    payload: RfiCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    number = payload.number or await _next_rfi_number(db, auth.organization_id, payload.project_id)
    row = RfiModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        number=number,
        subject=payload.subject,
        description=payload.description,
        status=RfiStatus.open.value,
        priority=payload.priority.value,
        related_document_ids=payload.related_document_ids,
        raised_by=auth.user_id,
        assigned_to=payload.assigned_to,
        due_date=payload.due_date,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(Rfi.model_validate(row).model_dump(mode="json"))


@router.patch("/rfis/{rfi_id}", response_model=Envelope[Rfi])
async def update_rfi(
    rfi_id: UUID,
    payload: RfiUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    row = await db.get(RfiModel, rfi_id)
    if row is None or row.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "RFI not found")

    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None:
        data["status"] = data["status"].value if hasattr(data["status"], "value") else data["status"]
    if "priority" in data and data["priority"] is not None:
        data["priority"] = data["priority"].value if hasattr(data["priority"], "value") else data["priority"]

    for k, v in data.items():
        setattr(row, k, v)

    await db.commit()
    await db.refresh(row)
    return ok(Rfi.model_validate(row).model_dump(mode="json"))


@router.post("/rfis/{rfi_id}/answer", response_model=Envelope[Rfi])
async def answer_rfi(
    rfi_id: UUID,
    payload: RfiAnswer,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    row = await db.get(RfiModel, rfi_id)
    if row is None or row.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "RFI not found")

    row.response = payload.response
    row.status = RfiStatus.closed.value if payload.close else RfiStatus.answered.value
    await db.commit()
    await db.refresh(row)
    return ok(Rfi.model_validate(row).model_dump(mode="json"))


@router.post("/rfis/generate", response_model=Envelope[Rfi])
async def generate_rfi_from_conflict(
    payload: RfiGenerateFromConflictRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """AI-generate an RFI draft from an existing conflict, then persist it."""
    conflict = await db.get(ConflictModel, payload.conflict_id)
    if conflict is None or conflict.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conflict not found")

    from ml.pipelines.drawbridge import draft_rfi_from_conflict

    try:
        draft: RfiDraft = await draft_rfi_from_conflict(db=db, conflict_id=payload.conflict_id)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"RFI draft failed: {exc}") from exc

    number = await _next_rfi_number(db, auth.organization_id, conflict.project_id)
    row = RfiModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=conflict.project_id,
        number=number,
        subject=draft.subject,
        description=draft.description,
        status=RfiStatus.open.value,
        priority=payload.priority.value,
        related_document_ids=draft.related_document_ids,
        raised_by=auth.user_id,
        assigned_to=payload.assigned_to,
        due_date=payload.due_date,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(Rfi.model_validate(row).model_dump(mode="json"))


async def _next_rfi_number(db: AsyncSession, org_id: UUID, project_id: UUID | None) -> str:
    """Monotonic per-project RFI number like RFI-0001."""
    stmt = select(func.count(RfiModel.id)).where(
        and_(RfiModel.organization_id == org_id, RfiModel.project_id == project_id)
    )
    current = (await db.execute(stmt)).scalar_one() or 0
    return f"RFI-{current + 1:04d}"
