"""FastAPI router for CODEGUARD endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import Envelope, ok, paginated
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from models.codeguard import (
    ComplianceCheck as ComplianceCheckModel,
)
from models.codeguard import (
    PermitChecklist as PermitChecklistModel,
)
from models.codeguard import (
    Regulation as RegulationModel,
)
from models.codeguard import (
    RegulationChunk as RegulationChunkModel,
)
from schemas.codeguard import (
    ChecklistItemStatus,
    CheckStatus,
    CheckType,
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
        created_at=datetime.now(UTC),
    )
    db.add(check)
    await db.flush()
    await db.refresh(check)

    result.check_id = check.id
    return ok(result)


@router.post("/query/stream")
async def codeguard_query_stream(
    payload: QueryRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """SSE-streamed Q&A.

    Wire format (matches the standard `text/event-stream` SSE shape):

        event: token
        data: {"delta": "<incremental text>"}

        event: done
        data: {"answer": "...", "confidence": 0.88, "citations": [...],
               "related_questions": [...], "check_id": "<uuid>"}

        event: error
        data: {"message": "..."}

    The frontend should treat `done` as terminal — the `check_id` is
    only available there because it's set after the ComplianceCheck row
    is persisted, which can't happen until the LLM has emitted the full
    grounded response. `error` is also terminal; it does NOT preempt
    `done` — once an error fires, no further events follow.

    The non-streaming `/query` endpoint stays in place for clients that
    don't want SSE complexity (and for the existing router-level mock
    tests). Both code paths share `_hyde_expand`, `_hybrid_search`,
    `_rerank`, `_ground_citations`, and `_abstain_response` — anything
    you change in those flows for free into both surfaces.
    """
    from ml.pipelines.codeguard import answer_regulation_query_stream

    async def sse_stream():
        try:
            response: QueryResponse | None = None
            async for event_name, event_payload in answer_regulation_query_stream(
                db=db,
                question=payload.question,
                language=payload.language,
                jurisdiction=payload.jurisdiction,
                categories=payload.categories,
                top_k=payload.top_k,
            ):
                if event_name == "token":
                    # `delta` is plain text; json.dumps escapes any
                    # newlines or quotes that would otherwise break the
                    # SSE framing (which is line-delimited).
                    yield f"event: token\ndata: {json.dumps({'delta': event_payload})}\n\n"
                elif event_name == "done":
                    response = event_payload
                elif event_name == "error":
                    yield (f"event: error\ndata: {json.dumps({'message': str(event_payload)})}\n\n")
                    return

            if response is None:
                # Helper exited without emitting `done` or `error` —
                # shouldn't happen, but defend rather than leaving the
                # client hanging waiting for a terminal event.
                yield ('event: error\ndata: {"message": "pipeline produced no terminal event"}\n\n')
                return

            # Persist the ComplianceCheck row before the terminal `done`
            # event so the check_id we surface is committed audit state,
            # not a hypothetical UUID. Same shape as the non-streaming
            # /query endpoint — the audit trail is identical.
            check = ComplianceCheckModel(
                id=uuid4(),
                organization_id=auth.organization_id,
                project_id=payload.project_id,
                check_type=CheckType.manual_query.value,
                status=CheckStatus.completed.value,
                input=payload.model_dump(mode="json"),
                findings=response.model_dump(mode="json"),
                regulations_referenced=[c.regulation_id for c in response.citations],
                created_by=auth.user_id,
                created_at=datetime.now(UTC),
            )
            db.add(check)
            await db.flush()
            await db.refresh(check)
            response.check_id = check.id

            yield f"event: done\ndata: {response.model_dump_json()}\n\n"
        except Exception as exc:  # pragma: no cover — defensive catch
            yield (f"event: error\ndata: {json.dumps({'message': f'Q&A pipeline failed: {exc}'})}\n\n")

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            # Prevent intermediate proxies from buffering the stream —
            # nginx in particular needs `X-Accel-Buffering: no` to flush
            # each chunk immediately. Without it the client gets the
            # whole response in one go and the streaming UX collapses.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
        created_at=datetime.now(UTC),
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


@router.post("/scan/stream")
async def codeguard_scan_stream(
    payload: ScanRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """SSE-streamed compliance scan.

    Wire format:

        event: category_start
        data: {"category": "fire_safety"}

        event: category_done
        data: {"category": "fire_safety",
               "findings": [{status, severity, ..., citation}, ...]}

        event: done
        data: {"check_id": "<uuid>", "total": N,
               "pass_count": ..., "warn_count": ..., "fail_count": ...}

        event: error
        data: {"message": "..."}

    Per-category events let the frontend render findings as each
    category finishes — for the slowest endpoint in the module
    (5 sequential LLM calls), that's the difference between "stare at
    a spinner for 30s" and "watch findings populate live."

    `done` is terminal and only fires on success. `error` is also
    terminal. `reg_ids` is rolled into the persisted ComplianceCheck
    row but NOT echoed in `done` (the frontend doesn't need it).
    """
    from ml.pipelines.codeguard import auto_scan_project_stream

    async def sse_stream():
        try:
            all_findings: list = []
            all_reg_ids: list = []

            async for event_name, event_payload in auto_scan_project_stream(
                db=db,
                parameters=payload.parameters,
                categories=payload.categories,
            ):
                if event_name == "category_start":
                    yield (f"event: category_start\ndata: {json.dumps({'category': event_payload.value})}\n\n")
                elif event_name == "category_done":
                    cat = event_payload["category"]
                    findings = event_payload["findings"]
                    all_findings.extend(findings)
                    all_reg_ids.extend(event_payload["reg_ids"])
                    body = {
                        "category": cat.value,
                        "findings": [f.model_dump(mode="json") for f in findings],
                    }
                    yield f"event: category_done\ndata: {json.dumps(body)}\n\n"
                elif event_name == "error":
                    yield (f"event: error\ndata: {json.dumps({'message': str(event_payload)})}\n\n")
                    return

            # All categories done — persist the ComplianceCheck row
            # before emitting the terminal `done`. Mirrors the
            # non-streaming /scan persistence shape exactly so audit
            # consumers (history page, /checks endpoint) treat both
            # paths identically.
            pass_count = sum(1 for f in all_findings if f.status == "PASS")
            warn_count = sum(1 for f in all_findings if f.status == "WARN")
            fail_count = sum(1 for f in all_findings if f.status == "FAIL")

            check = ComplianceCheckModel(
                id=uuid4(),
                organization_id=auth.organization_id,
                project_id=payload.project_id,
                check_type=CheckType.auto_scan.value,
                status=CheckStatus.completed.value,
                input=payload.model_dump(mode="json"),
                findings=[f.model_dump(mode="json") for f in all_findings],
                regulations_referenced=list({rid for rid in all_reg_ids}),
                created_by=auth.user_id,
                created_at=datetime.now(UTC),
            )
            db.add(check)
            await db.flush()
            await db.refresh(check)

            done_body = {
                "check_id": str(check.id),
                "total": len(all_findings),
                "pass_count": pass_count,
                "warn_count": warn_count,
                "fail_count": fail_count,
            }
            yield f"event: done\ndata: {json.dumps(done_body)}\n\n"
        except Exception as exc:  # pragma: no cover — defensive
            yield (f"event: error\ndata: {json.dumps({'message': f'Auto-scan failed: {exc}'})}\n\n")

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Checklist generation failed: {exc}") from exc

    record = PermitChecklistModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        jurisdiction=payload.jurisdiction,
        project_type=payload.project_type,
        items=[i.model_dump(mode="json") for i in items],
        generated_at=datetime.now(UTC),
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
    now_iso = datetime.now(UTC).isoformat()
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
        i.get("status") in (ChecklistItemStatus.done.value, ChecklistItemStatus.not_applicable.value) for i in items
    ):
        checklist.completed_at = datetime.now(UTC)

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
        stmt = stmt.where(or_(RegulationModel.code_name.ilike(like), RegulationModel.raw_text.ilike(like)))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
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
    sections = [RegulationSection(section_ref=c.section_ref or "", content=c.content) for c in chunks]

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
