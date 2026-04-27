"""FastAPI router for PROJECTPULSE endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.envelope import Envelope, ok, paginated
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role
from models.pulse import (
    ChangeOrder as ChangeOrderModel,
)
from models.pulse import (
    ClientReport as ClientReportModel,
)
from models.pulse import (
    MeetingNote as MeetingNoteModel,
)
from models.pulse import (
    Milestone as MilestoneModel,
)
from models.pulse import (
    Task as TaskModel,
)
from schemas.pulse import (
    RAG,
    ChangeOrder,
    ChangeOrderAIAnalysis,
    ChangeOrderApproval,
    ChangeOrderCreate,
    ChangeOrderStatus,
    ClientReport,
    ClientReportContent,
    MeetingNote,
    MeetingNoteCreate,
    MeetingStructured,
    MeetingStructureRequest,
    Milestone,
    Phase,
    ProjectDashboard,
    ReportGenerateRequest,
    ReportSendRequest,
    ReportStatus,
    Task,
    TaskBulkUpdate,
    TaskCountsByStatus,
    TaskCreate,
    TaskStatus,
    TaskUpdate,
)

router = APIRouter(prefix="/api/v1/pulse", tags=["pulse"])


# ---------- Dashboard ----------


@router.get("/projects/{project_id}/dashboard", response_model=Envelope[ProjectDashboard])
async def project_dashboard(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    today = date.today()

    counts_rows = (
        await db.execute(
            select(TaskModel.status, func.count()).where(TaskModel.project_id == project_id).group_by(TaskModel.status)
        )
    ).all()
    counts = TaskCountsByStatus()
    for s, n in counts_rows:
        if hasattr(counts, s):
            setattr(counts, s, int(n))

    total_tasks = sum([counts.todo, counts.in_progress, counts.review, counts.done, counts.blocked])
    progress_pct = (counts.done / total_tasks * 100.0) if total_tasks else 0.0

    overdue = (
        await db.execute(
            select(func.count()).where(
                TaskModel.project_id == project_id,
                TaskModel.due_date < today,
                TaskModel.status.not_in(["done"]),
            )
        )
    ).scalar_one()

    milestones_rows = (
        (
            await db.execute(
                select(MilestoneModel)
                .where(
                    MilestoneModel.project_id == project_id,
                    MilestoneModel.status == "upcoming",
                )
                .order_by(MilestoneModel.due_date.asc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    upcoming = [Milestone.model_validate(m) for m in milestones_rows]

    open_co_rows = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(ChangeOrderModel.cost_impact_vnd), 0)).where(
                ChangeOrderModel.project_id == project_id,
                ChangeOrderModel.status.in_(["draft", "submitted"]),
            )
        )
    ).one()
    open_co_count, open_cost_impact = int(open_co_rows[0] or 0), int(open_co_rows[1] or 0)

    last_report = (
        await db.execute(
            select(ClientReportModel.report_date)
            .where(ClientReportModel.project_id == project_id)
            .order_by(ClientReportModel.report_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    alerts: list[str] = []
    if overdue:
        alerts.append(f"{overdue} overdue task(s)")
    if counts.blocked:
        alerts.append(f"{counts.blocked} blocked task(s)")
    if open_co_count:
        alerts.append(f"{open_co_count} open change order(s)")

    if overdue >= 5 or counts.blocked >= 3:
        rag = RAG.red
    elif overdue or counts.blocked or open_co_count >= 3:
        rag = RAG.amber
    else:
        rag = RAG.green

    dashboard = ProjectDashboard(
        project_id=project_id,
        rag_status=rag,
        progress_pct=round(progress_pct, 1),
        task_counts=counts,
        overdue_tasks=int(overdue),
        upcoming_milestones=upcoming,
        open_change_orders=open_co_count,
        open_cost_impact_vnd=open_cost_impact,
        last_report_date=last_report,
        alerts=alerts,
    )
    return ok(dashboard)


# ---------- Tasks ----------


@router.get("/tasks", response_model=Envelope[list[Task]])
async def list_tasks(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID | None = None,
    assignee_id: UUID | None = None,
    phase: Phase | None = None,
    task_status: TaskStatus | None = Query(default=None, alias="status"),
    parent_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    stmt = select(TaskModel)
    if project_id:
        stmt = stmt.where(TaskModel.project_id == project_id)
    if assignee_id:
        stmt = stmt.where(TaskModel.assignee_id == assignee_id)
    if phase:
        stmt = stmt.where(TaskModel.phase == phase.value)
    if task_status:
        stmt = stmt.where(TaskModel.status == task_status.value)
    if parent_id:
        stmt = stmt.where(TaskModel.parent_id == parent_id)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(TaskModel.position.asc().nullslast(), TaskModel.created_at.asc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return paginated([Task.model_validate(r) for r in rows], page=offset // limit + 1, per_page=limit, total=int(total))


@router.post("/tasks", response_model=Envelope[Task], status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    task = TaskModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        parent_id=payload.parent_id,
        title=payload.title,
        description=payload.description,
        status=payload.status.value,
        priority=payload.priority.value,
        assignee_id=payload.assignee_id,
        phase=payload.phase.value if payload.phase else None,
        discipline=payload.discipline,
        start_date=payload.start_date,
        due_date=payload.due_date,
        position=payload.position,
        tags=list(payload.tags),
        created_by=auth.user_id,
        created_at=datetime.now(UTC),
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return ok(Task.model_validate(task))


@router.patch("/tasks/{task_id}", response_model=Envelope[Task])
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    task = await db.get(TaskModel, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")

    data = payload.model_dump(exclude_unset=True)
    for key in ("status", "priority", "phase"):
        if key in data and data[key] is not None:
            data[key] = data[key].value if hasattr(data[key], "value") else data[key]

    if data.get("status") == TaskStatus.done.value and task.completed_at is None:
        task.completed_at = datetime.now(UTC)
    elif "status" in data and data["status"] != TaskStatus.done.value:
        task.completed_at = None

    for key, value in data.items():
        setattr(task, key, value)

    await db.flush()
    await db.refresh(task)
    return ok(Task.model_validate(task))


@router.post("/tasks/bulk", response_model=Envelope[list[Task]])
async def bulk_update_tasks(
    payload: TaskBulkUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    ids = [i.id for i in payload.items]
    rows = (await db.execute(select(TaskModel).where(TaskModel.id.in_(ids)))).scalars().all()
    by_id = {t.id: t for t in rows}

    updated: list[TaskModel] = []
    for item in payload.items:
        task = by_id.get(item.id)
        if task is None:
            continue
        if item.status is not None:
            task.status = item.status.value
            task.completed_at = datetime.now(UTC) if item.status == TaskStatus.done else None
        if item.phase is not None:
            task.phase = item.phase.value
        if item.position is not None:
            task.position = item.position
        if item.assignee_id is not None:
            task.assignee_id = item.assignee_id
        updated.append(task)

    await db.flush()
    for task in updated:
        await db.refresh(task)
    return ok([Task.model_validate(t) for t in updated])


# ---------- Change orders ----------


@router.get("/change-orders", response_model=Envelope[list[ChangeOrder]])
async def list_change_orders(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID | None = None,
    co_status: ChangeOrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    stmt = select(ChangeOrderModel)
    if project_id:
        stmt = stmt.where(ChangeOrderModel.project_id == project_id)
    if co_status:
        stmt = stmt.where(ChangeOrderModel.status == co_status.value)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(ChangeOrderModel.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return paginated(
        [ChangeOrder.model_validate(r) for r in rows],
        page=offset // limit + 1,
        per_page=limit,
        total=int(total),
    )


@router.post("/change-orders", response_model=Envelope[ChangeOrder], status_code=status.HTTP_201_CREATED)
async def create_change_order(
    payload: ChangeOrderCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    co = ChangeOrderModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        number=payload.number,
        title=payload.title,
        description=payload.description,
        initiator=payload.initiator.value if payload.initiator else None,
        cost_impact_vnd=payload.cost_impact_vnd,
        schedule_impact_days=payload.schedule_impact_days,
        status=ChangeOrderStatus.draft.value,
        created_at=datetime.now(UTC),
    )
    db.add(co)
    await db.flush()
    await db.refresh(co)
    return ok(ChangeOrder.model_validate(co))


@router.post("/change-orders/{co_id}/analyze", response_model=Envelope[ChangeOrder])
async def analyze_change_order(
    co_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from ml.pipelines.pulse import analyze_change_order as ai_analyze

    co = await db.get(ChangeOrderModel, co_id)
    if co is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change order not found")

    project_context = await _project_context(db, co.project_id)
    try:
        analysis: ChangeOrderAIAnalysis = await ai_analyze(
            description=co.description or "",
            cost_impact_vnd=co.cost_impact_vnd,
            schedule_impact_days=co.schedule_impact_days,
            initiator=co.initiator,
            project_context=project_context,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"CO analysis failed: {exc}") from exc

    co.ai_analysis = analysis.model_dump(mode="json")
    if co.status == ChangeOrderStatus.draft.value:
        co.status = ChangeOrderStatus.submitted.value
        co.submitted_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(co)
    return ok(ChangeOrder.model_validate(co))


@router.patch("/change-orders/{co_id}/approve", response_model=Envelope[ChangeOrder])
async def approve_change_order(
    co_id: UUID,
    payload: ChangeOrderApproval,
    # Approving / rejecting a CO writes to the project budget — admin/owner.
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    co = await db.get(ChangeOrderModel, co_id)
    if co is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change order not found")

    if payload.decision == "approve":
        co.status = ChangeOrderStatus.approved.value
        co.approved_at = datetime.now(UTC)
        co.approved_by = auth.user_id
    else:
        co.status = ChangeOrderStatus.rejected.value

    await db.flush()
    await db.refresh(co)
    return ok(ChangeOrder.model_validate(co))


# ---------- Meeting notes ----------


@router.post("/meeting-notes", response_model=Envelope[MeetingNote], status_code=status.HTTP_201_CREATED)
async def create_meeting_note(
    payload: MeetingNoteCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    note = MeetingNoteModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        meeting_date=payload.meeting_date,
        attendees=list(payload.attendees),
        raw_notes=payload.raw_notes,
        created_by=auth.user_id,
        created_at=datetime.now(UTC),
    )
    db.add(note)
    await db.flush()
    await db.refresh(note)
    return ok(MeetingNote.model_validate(note))


@router.post("/meeting-notes/structure", response_model=Envelope[MeetingNote])
async def structure_meeting_notes(
    payload: MeetingStructureRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from ml.pipelines.pulse import structure_meeting_notes as ai_structure

    try:
        structured: MeetingStructured = await ai_structure(raw_notes=payload.raw_notes, language=payload.language)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Meeting structuring failed: {exc}") from exc

    if not payload.persist:
        return ok(
            MeetingNote(
                id=uuid4(),
                project_id=payload.project_id or uuid4(),
                organization_id=auth.organization_id,
                meeting_date=date.today(),
                attendees=[],
                raw_notes=payload.raw_notes,
                ai_structured=structured,
                created_by=auth.user_id,
                created_at=datetime.now(UTC),
            )
        )

    note: MeetingNoteModel | None
    if payload.meeting_note_id:
        note = await db.get(MeetingNoteModel, payload.meeting_note_id)
        if note is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting note not found")
        note.raw_notes = payload.raw_notes
    else:
        if payload.project_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "project_id required when persisting a new note")
        note = MeetingNoteModel(
            id=uuid4(),
            organization_id=auth.organization_id,
            project_id=payload.project_id,
            meeting_date=date.today(),
            attendees=[],
            raw_notes=payload.raw_notes,
            created_by=auth.user_id,
            created_at=datetime.now(UTC),
        )
        db.add(note)

    note.ai_structured = structured.model_dump(mode="json")
    await db.flush()
    await db.refresh(note)
    return ok(MeetingNote.model_validate(note))


# ---------- Client reports ----------


@router.post("/client-reports/generate", response_model=Envelope[ClientReport], status_code=status.HTTP_201_CREATED)
async def generate_client_report(
    payload: ReportGenerateRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from ml.pipelines.pulse import generate_client_report as ai_generate

    try:
        aggregated = await _aggregate_report_inputs(
            db,
            project_id=payload.project_id,
            date_from=payload.date_from,
            date_to=payload.date_to,
        )
        content: ClientReportContent = await ai_generate(
            project_id=payload.project_id,
            period=payload.period,
            language=payload.language,
            include_photos=payload.include_photos,
            include_financials=payload.include_financials,
            data=aggregated,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Report generation failed: {exc}") from exc

    from ml.pipelines.pulse import render_report_html

    rendered = await render_report_html(content, language=payload.language)

    report_id = uuid4()
    pdf_url = await _render_and_store_pdf(
        organization_id=auth.organization_id,
        report_id=report_id,
        html=rendered,
    )

    report = ClientReportModel(
        id=report_id,
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        report_date=date.today(),
        period=payload.period,
        content=content.model_dump(mode="json"),
        rendered_html=rendered,
        pdf_url=pdf_url,
        status=ReportStatus.draft.value,
        created_at=datetime.now(UTC),
    )
    db.add(report)
    await db.flush()
    await db.refresh(report)
    return ok(ClientReport.model_validate(report))


async def _render_and_store_pdf(
    *,
    organization_id: UUID,
    report_id: UUID,
    html: str,
) -> str | None:
    """Best-effort PDF render + upload. Returns the URL or None on any failure.

    Failures here never fail the whole /generate request — the HTML preview is
    still saved and the client can fall back to it. Worth logging loudly so ops
    notices if WeasyPrint or S3 is misconfigured, but not worth 5xx'ing the
    report (which the user just spent LLM tokens producing).
    """
    import logging

    from ml.pipelines.pulse import PDFRendererUnavailable, render_report_pdf

    from services.pdf_storage import upload_report_pdf

    logger = logging.getLogger(__name__)

    try:
        pdf_bytes = await render_report_pdf(html)
    except PDFRendererUnavailable:
        logger.warning(
            "weasyprint not available; report %s will be HTML-only",
            report_id,
        )
        return None
    except Exception:  # noqa: BLE001 — never block the HTML report on PDF issues
        logger.exception("PDF render failed for report %s", report_id)
        return None

    try:
        settings = get_settings()
        return await upload_report_pdf(
            settings,
            organization_id=organization_id,
            report_id=report_id,
            pdf_bytes=pdf_bytes,
        )
    except Exception:  # noqa: BLE001 — same rationale: fall back to HTML
        logger.exception("PDF upload failed for report %s", report_id)
        return None


@router.post("/client-reports/{report_id}/send", response_model=Envelope[ClientReport])
async def send_client_report(
    report_id: UUID,
    payload: ReportSendRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    report = await db.get(ClientReportModel, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")

    try:
        from services.email import send_report_email  # type: ignore[import-not-found]

        await send_report_email(
            to=payload.recipients,
            subject=payload.subject or "Project progress report",
            message=payload.message or "",
            html=report.rendered_html or "",
            pdf_url=report.pdf_url,
        )
    except ImportError:
        pass

    report.status = ReportStatus.sent.value
    report.sent_at = datetime.now(UTC)
    report.sent_to = list(payload.recipients)
    await db.flush()
    await db.refresh(report)
    return ok(ClientReport.model_validate(report))


# ---------- helpers ----------


async def _project_context(db: AsyncSession, project_id: UUID) -> dict:
    row = (
        await db.execute(
            select(
                func.count(ChangeOrderModel.id).filter(ChangeOrderModel.status.in_(["submitted", "approved"])),
                func.coalesce(func.sum(ChangeOrderModel.cost_impact_vnd), 0),
            ).where(ChangeOrderModel.project_id == project_id)
        )
    ).one()
    return {
        "project_id": str(project_id),
        "prior_co_count": int(row[0] or 0),
        "prior_cost_impact_vnd": int(row[1] or 0),
    }


async def _aggregate_report_inputs(
    db: AsyncSession,
    project_id: UUID,
    date_from: date | None,
    date_to: date | None,
) -> dict:
    """Collect the facts the LLM needs to write a client report.

    Pulse owns tasks/milestones/change-orders directly. Progress% and site
    photos come from SiteEye; budget comes from CostPulse. Cross-module reads
    are best-effort — if a sibling table is missing rows (or the module hasn't
    been seeded on this tenant yet), we return empty values rather than 5xx'ing
    the report. The LLM prompt is written to tolerate missing sections.
    """
    tasks_q = select(TaskModel).where(TaskModel.project_id == project_id)
    if date_from:
        tasks_q = tasks_q.where(TaskModel.completed_at >= date_from)
    if date_to:
        tasks_q = tasks_q.where(TaskModel.completed_at <= date_to)
    tasks_q = tasks_q.where(TaskModel.status == "done")
    completed_tasks = (await db.execute(tasks_q)).scalars().all()

    milestones = (
        (
            await db.execute(
                select(MilestoneModel)
                .where(MilestoneModel.project_id == project_id)
                .order_by(MilestoneModel.due_date.asc())
            )
        )
        .scalars()
        .all()
    )

    open_cos = (
        (
            await db.execute(
                select(ChangeOrderModel).where(
                    and_(
                        ChangeOrderModel.project_id == project_id,
                        ChangeOrderModel.status.in_(["submitted", "approved"]),
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    approved_co_cost = sum(
        int(c.cost_impact_vnd or 0) for c in open_cos if c.status == ChangeOrderStatus.approved.value
    )
    approved_co_schedule = sum(
        int(c.schedule_impact_days or 0) for c in open_cos if c.status == ChangeOrderStatus.approved.value
    )

    progress = await _latest_progress_snapshot(db, project_id, date_to)
    photos = await _recent_site_photos(db, project_id, date_from, date_to)
    budget = await _project_budget_summary(db, project_id, approved_co_cost)

    return {
        "completed_tasks": [
            {"id": str(t.id), "title": t.title, "completed_at": t.completed_at, "phase": t.phase}
            for t in completed_tasks
        ],
        "milestones": [{"name": m.name, "due_date": m.due_date, "status": m.status} for m in milestones],
        "change_orders": [
            {
                "number": c.number,
                "title": c.title,
                "cost_impact_vnd": c.cost_impact_vnd,
                "schedule_impact_days": c.schedule_impact_days,
                "status": c.status,
            }
            for c in open_cos
        ],
        "approved_change_order_totals": {
            "cost_impact_vnd": approved_co_cost,
            "schedule_impact_days": approved_co_schedule,
        },
        "progress": progress,
        "photos": photos,
        "budget": budget,
    }


async def _latest_progress_snapshot(db: AsyncSession, project_id: UUID, as_of: date | None) -> dict | None:
    """Pick the newest ProgressSnapshot at or before `as_of` (or overall).

    Best-effort: missing SiteEye tables or empty data → return None so the LLM
    just omits the progress section.
    """
    try:
        from models.siteeye import ProgressSnapshot  # lazy: module may be absent
    except ImportError:
        return None

    stmt = select(ProgressSnapshot).where(ProgressSnapshot.project_id == project_id)
    if as_of is not None:
        stmt = stmt.where(ProgressSnapshot.snapshot_date <= as_of)
    stmt = stmt.order_by(ProgressSnapshot.snapshot_date.desc()).limit(1)

    try:
        snap = (await db.execute(stmt)).scalar_one_or_none()
    except Exception:
        return None
    if snap is None:
        return None

    return {
        "snapshot_date": snap.snapshot_date,
        "overall_progress_pct": float(snap.overall_progress_pct) if snap.overall_progress_pct is not None else None,
        "phase_progress": snap.phase_progress or {},
        "ai_notes": snap.ai_notes,
    }


async def _recent_site_photos(
    db: AsyncSession,
    project_id: UUID,
    date_from: date | None,
    date_to: date | None,
    limit: int = 8,
) -> list[dict]:
    """Return up to `limit` recent site photos for the report period.

    Cap is tuned for client-report layout; the AI pipeline can pick a subset.
    """
    try:
        from models.siteeye import SitePhoto
    except ImportError:
        return []

    stmt = select(SitePhoto).where(SitePhoto.project_id == project_id)
    if date_from is not None:
        stmt = stmt.where(SitePhoto.taken_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(SitePhoto.taken_at <= date_to)
    stmt = stmt.order_by(SitePhoto.taken_at.desc().nullslast()).limit(limit)

    try:
        rows = (await db.execute(stmt)).scalars().all()
    except Exception:
        return []

    return [
        {
            "id": str(p.id),
            "thumbnail_url": p.thumbnail_url,
            "taken_at": p.taken_at,
            "tags": list(p.tags or []),
            "caption": (p.ai_analysis or {}).get("caption") if p.ai_analysis else None,
        }
        for p in rows
    ]


async def _project_budget_summary(db: AsyncSession, project_id: UUID, approved_co_cost_vnd: int) -> dict | None:
    """Budget snapshot: latest approved estimate + CO-adjusted projection.

    CostPulse doesn't yet model realised spend, so "actual" is proxied by
    approved change-order cost impact — the part of variance we actually have
    hard numbers for. The report section should phrase this as "projected
    final cost" not "actual spend". Returns None when there is no approved
    estimate on file (the LLM will omit the financials section entirely).
    """
    try:
        from models.costpulse import Estimate
    except ImportError:
        return None

    stmt = (
        select(Estimate)
        .where(
            Estimate.project_id == project_id,
            Estimate.status == "approved",
        )
        .order_by(Estimate.version.desc(), Estimate.created_at.desc())
        .limit(1)
    )
    try:
        est = (await db.execute(stmt)).scalar_one_or_none()
    except Exception:
        return None
    if est is None or est.total_vnd is None:
        return None

    budget = int(est.total_vnd)
    projected_final = budget + int(approved_co_cost_vnd or 0)
    variance = projected_final - budget
    return {
        "estimate_id": str(est.id),
        "estimate_name": est.name,
        "estimate_version": est.version,
        "budget_vnd": budget,
        "approved_co_cost_vnd": int(approved_co_cost_vnd or 0),
        "projected_final_vnd": projected_final,
        "variance_vnd": variance,
        "variance_pct": round((variance / budget) * 100.0, 2) if budget else 0.0,
    }
