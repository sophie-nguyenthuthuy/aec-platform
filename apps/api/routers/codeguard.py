"""FastAPI router for CODEGUARD endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import Envelope, Meta, ok, paginated
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from models.codeguard import (
    ComplianceCheck as ComplianceCheckModel,
    PermitChecklist as PermitChecklistModel,
    Regulation as RegulationModel,
    RegulationChunk as RegulationChunkModel,
)
from schemas.codeguard import (
    CheckStatus,
    CheckType,
    ChecklistItem,
    ChecklistItemStatus,
    ComplianceCheck,
    MarkItemRequest,
    PermitChecklist,
    PermitChecklistRequest,
    QueryRequest,
    QueryResponse,
    RegulationCategory,
    RegulationDetail,
    RegulationSection,
    RegulationSummary,
    ScanRequest,
    ScanResponse,
)


router = APIRouter(prefix="/api/v1/codeguard", tags=["codeguard"])


# ---------- Q&A ----------

@router.post("/query", response_model=Envelope[QueryResponse])
async def codeguard_query(
    payload: QueryRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from ml.pipelines.codeguard import answer_regulation_query

    try:
        result = await answer_regulation_query(
            db=db,
            question=payload.question,
            language=payload.language,
            jurisdiction=payload.jurisdiction,
            categories=payload.categories,
            top_k=payload.top_k,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Q&A pipeline failed: {exc}") from exc

    check = ComplianceCheckModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        check_type=CheckType.manual_query.value,
        status=CheckStatus.completed.value,
        input=payload.model_dump(mode="json"),
        findings=result.model_dump(mode="json"),
        regulations_referenced=[c.regulation_id for c in result.citations],
        created_by=auth.user_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(check)
    await db.flush()
    await db.refresh(check)

    result.check_id = check.id
    return ok(result)


# ---------- Auto-scan ----------

@router.post("/scan", response_model=Envelope[ScanResponse])
async def codeguard_scan(
    payload: ScanRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from ml.pipelines.codeguard import auto_scan_project

    check = ComplianceCheckModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        check_type=CheckType.auto_scan.value,
        status=CheckStatus.running.value,
        input=payload.model_dump(mode="json"),
        created_by=auth.user_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(check)
    await db.flush()

    try:
        findings, reg_ids = await auto_scan_project(
            db=db,
            parameters=payload.parameters,
            categories=payload.categories,
        )
    except Exception as exc:
        check.status = CheckStatus.failed.value
        await db.flush()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Auto-scan failed: {exc}") from exc

    pass_count = sum(1 for f in findings if f.status == "PASS")
    warn_count = sum(1 for f in findings if f.status == "WARN")
    fail_count = sum(1 for f in findings if f.status == "FAIL")

    check.status = CheckStatus.completed.value
    check.findings = [f.model_dump(mode="json") for f in findings]
    check.regulations_referenced = reg_ids
    await db.flush()
    await db.refresh(check)

    response = ScanResponse(
        check_id=check.id,
        status=CheckStatus.completed,
        total=len(findings),
        pass_count=pass_count,
        warn_count=warn_count,
        fail_count=fail_count,
        findings=findings,
    )
    return ok(response)


# ---------- Permit checklist ----------

@router.post("/permit-checklist", response_model=Envelope[PermitChecklist])
async def create_permit_checklist(
    payload: PermitChecklistRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from ml.pipelines.codeguard import generate_permit_checklist

    try:
        items = await generate_permit_checklist(
            db=db,
            jurisdiction=payload.jurisdiction,
            project_type=payload.project_type,
            parameters=payload.parameters,
        )
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Checklist generation failed: {exc}"
        ) from exc

    record = PermitChecklistModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        jurisdiction=payload.jurisdiction,
        project_type=payload.project_type,
        items=[i.model_dump(mode="json") for i in items],
        generated_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)

    return ok(PermitChecklist.model_validate(record))


@router.post("/checks/{check_id}/mark-item", response_model=Envelope[PermitChecklist])
async def mark_checklist_item(
    check_id: UUID,
    payload: MarkItemRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    checklist = await db.get(PermitChecklistModel, check_id)
    if checklist is None or checklist.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist not found")

    items = list(checklist.items or [])
    now_iso = datetime.now(timezone.utc).isoformat()
    updated = False
    for item in items:
        if item.get("id") == payload.item_id:
            item["status"] = payload.status.value
            if payload.notes is not None:
                item["notes"] = payload.notes
            if payload.assignee_id is not None:
                item["assignee_id"] = str(payload.assignee_id)
            item["updated_at"] = now_iso
            updated = True
            break

    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist item not found")

    checklist.items = items
    if all(
        i.get("status") in (ChecklistItemStatus.done.value, ChecklistItemStatus.not_applicable.value)
        for i in items
    ):
        checklist.completed_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(checklist)
    return ok(PermitChecklist.model_validate(checklist))


# ---------- Regulations ----------

@router.get("/regulations", response_model=Envelope[list[RegulationSummary]])
async def list_regulations(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    country_code: str | None = Query(default=None, max_length=2),
    jurisdiction: str | None = None,
    category: RegulationCategory | None = None,
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    stmt = select(RegulationModel)
    if country_code:
        stmt = stmt.where(RegulationModel.country_code == country_code.upper())
    if jurisdiction:
        stmt = stmt.where(RegulationModel.jurisdiction == jurisdiction)
    if category:
        stmt = stmt.where(RegulationModel.category == category.value)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(RegulationModel.code_name.ilike(like), RegulationModel.raw_text.ilike(like))
        )

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(RegulationModel.code_name).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()

    return paginated(
        [RegulationSummary.model_validate(r) for r in rows],
        page=offset // limit + 1,
        per_page=limit,
        total=int(total),
    )


@router.get("/regulations/{regulation_id}", response_model=Envelope[RegulationDetail])
async def get_regulation(
    regulation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    reg = await db.get(RegulationModel, regulation_id)
    if reg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regulation not found")

    chunks_stmt = (
        select(RegulationChunkModel)
        .where(RegulationChunkModel.regulation_id == regulation_id)
        .order_by(RegulationChunkModel.section_ref)
    )
    chunks = (await db.execute(chunks_stmt)).scalars().all()
    sections = [
        RegulationSection(section_ref=c.section_ref or "", content=c.content)
        for c in chunks
    ]

    detail = RegulationDetail.model_validate(
        {
            "id": reg.id,
            "country_code": reg.country_code,
            "jurisdiction": reg.jurisdiction,
            "code_name": reg.code_name,
            "category": reg.category,
            "effective_date": reg.effective_date,
            "expiry_date": reg.expiry_date,
            "source_url": reg.source_url,
            "language": reg.language,
            "content": reg.content,
            "sections": sections,
        }
    )
    return ok(detail)


# ---------- Check history ----------

@router.get("/checks/{project_id}", response_model=Envelope[list[ComplianceCheck]])
async def list_project_checks(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    check_type: CheckType | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    stmt = (
        select(ComplianceCheckModel)
        .where(
            and_(
                ComplianceCheckModel.project_id == project_id,
                ComplianceCheckModel.organization_id == auth.organization_id,
            )
        )
        .order_by(ComplianceCheckModel.created_at.desc())
        .limit(limit)
    )
    if check_type:
        stmt = stmt.where(ComplianceCheckModel.check_type == check_type.value)
    rows = (await db.execute(stmt)).scalars().all()
    return ok([ComplianceCheck.model_validate(r) for r in rows])
