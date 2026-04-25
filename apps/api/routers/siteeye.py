"""SiteEye FastAPI router — construction site intelligence endpoints."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok, paginated, Meta
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.siteeye import (
    AcknowledgeIncidentRequest,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    PhotoAIAnalysis,
    PhotoBatchUploadRequest,
    PhotoBatchUploadResponse,
    PhotoListFilters,
    ProgressSnapshot,
    ProgressTimeline,
    SafetyIncident,
    SafetyIncidentFilters,
    SafetyStatus,
    SendReportRequest,
    SitePhoto,
    SiteVisit,
    SiteVisitCreate,
    VisitListFilters,
    WeeklyReport,
    WeeklyReportGenerateRequest,
    WeeklyReportListFilters,
)

router = APIRouter(prefix="/api/v1/siteeye", tags=["siteeye"])


# ---------- Session helper ----------

async def _session(auth: AuthContext) -> AsyncSession:
    return await TenantAwareSession(auth.organization_id).__aenter__()


# ---------- Visits ----------

@router.post("/visits", status_code=status.HTTP_201_CREATED)
async def create_visit(
    payload: SiteVisitCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            pg_insert_site_visit(
                organization_id=auth.organization_id,
                project_id=payload.project_id,
                visit_date=payload.visit_date,
                location=payload.location.model_dump() if payload.location else None,
                reported_by=auth.user_id,
                weather=payload.weather,
                workers_count=payload.workers_count,
                notes=payload.notes,
            )
        )
        row = result.mappings().one()
    visit = SiteVisit.model_validate({**dict(row), "photo_count": 0})
    return ok(visit.model_dump(mode="json"))


@router.get("/visits")
async def list_visits(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = VisitListFilters(
        project_id=project_id, date_from=date_from, date_to=date_to, limit=limit, offset=offset
    )
    async with TenantAwareSession(auth.organization_id) as session:
        from sqlalchemy import text
        where, params = _visit_where(filters, auth.organization_id)
        base_sql = f"""
            SELECT v.*, COALESCE(p.cnt, 0) AS photo_count
            FROM site_visits v
            LEFT JOIN (
                SELECT site_visit_id, COUNT(*)::int AS cnt
                FROM site_photos GROUP BY site_visit_id
            ) p ON p.site_visit_id = v.id
            WHERE {where}
            ORDER BY v.visit_date DESC, v.created_at DESC
            LIMIT :limit OFFSET :offset
        """
        count_sql = f"SELECT COUNT(*) FROM site_visits v WHERE {where}"
        rows = (await session.execute(text(base_sql), {**params, "limit": limit, "offset": offset})).mappings().all()
        total = (await session.execute(text(count_sql), params)).scalar_one()
    items = [SiteVisit.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


# ---------- Photos ----------

@router.post("/photos/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_photos(
    payload: PhotoBatchUploadRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    from workers.queue import enqueue_photo_analysis

    photo_ids: list[UUID] = []
    async with TenantAwareSession(auth.organization_id) as session:
        from sqlalchemy import text
        for item in payload.photos:
            new_id = uuid4()
            photo_ids.append(new_id)
            await session.execute(
                text(
                    """
                    INSERT INTO site_photos
                      (id, organization_id, project_id, site_visit_id, file_id,
                       thumbnail_url, taken_at, location, tags, safety_status)
                    VALUES
                      (:id, :org, :project_id, :visit_id, :file_id,
                       :thumb, :taken_at, :location, :tags, 'clear')
                    """
                ),
                {
                    "id": str(new_id),
                    "org": str(auth.organization_id),
                    "project_id": str(payload.project_id),
                    "visit_id": str(payload.site_visit_id) if payload.site_visit_id else None,
                    "file_id": str(item.file_id),
                    "thumb": item.thumbnail_url,
                    "taken_at": item.taken_at,
                    "location": item.location.model_dump_json() if item.location else None,
                    "tags": [],
                },
            )

    job_id = await enqueue_photo_analysis(
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        photo_ids=photo_ids,
    )
    return ok(
        PhotoBatchUploadResponse(accepted=len(photo_ids), photo_ids=photo_ids, job_id=job_id).model_dump(mode="json")
    )


@router.get("/photos")
async def list_photos(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    site_visit_id: UUID | None = None,
    tags: list[str] | None = Query(None),
    safety_status: SafetyStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = PhotoListFilters(
        project_id=project_id,
        site_visit_id=site_visit_id,
        tags=tags,
        safety_status=safety_status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    async with TenantAwareSession(auth.organization_id) as session:
        from sqlalchemy import text
        where, params = _photo_where(filters, auth.organization_id)
        list_sql = f"""
            SELECT * FROM site_photos
            WHERE {where}
            ORDER BY taken_at DESC NULLS LAST, created_at DESC
            LIMIT :limit OFFSET :offset
        """
        rows = (await session.execute(text(list_sql), {**params, "limit": limit, "offset": offset})).mappings().all()
        total = (await session.execute(text(f"SELECT COUNT(*) FROM site_photos WHERE {where}"), params)).scalar_one()

    items = [_row_to_photo(r).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


# ---------- Progress ----------

@router.get("/progress")
async def progress_timeline(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID,
    date_from: date | None = None,
    date_to: date | None = None,
):
    async with TenantAwareSession(auth.organization_id) as session:
        from sqlalchemy import text
        params: dict = {"org": str(auth.organization_id), "project_id": str(project_id)}
        date_filter = ""
        if date_from:
            date_filter += " AND snapshot_date >= :date_from"
            params["date_from"] = date_from
        if date_to:
            date_filter += " AND snapshot_date <= :date_to"
            params["date_to"] = date_to
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT * FROM progress_snapshots
                    WHERE organization_id = :org AND project_id = :project_id {date_filter}
                    ORDER BY snapshot_date ASC
                    """
                ),
                params,
            )
        ).mappings().all()

    snapshots = [ProgressSnapshot.model_validate(dict(r)) for r in rows]
    timeline = ProgressTimeline(
        project_id=project_id,
        snapshots=snapshots,
        schedule_status=_infer_schedule_status(snapshots),
    )
    return ok(timeline.model_dump(mode="json"))


# ---------- Safety ----------

@router.get("/safety-incidents")
async def list_safety_incidents(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    status_: IncidentStatus | None = Query(None, alias="status"),
    severity: IncidentSeverity | None = None,
    incident_type: IncidentType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = SafetyIncidentFilters(
        project_id=project_id,
        status=status_,
        severity=severity,
        incident_type=incident_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    async with TenantAwareSession(auth.organization_id) as session:
        from sqlalchemy import text
        where, params = _incident_where(filters, auth.organization_id)
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT * FROM safety_incidents
                    WHERE {where}
                    ORDER BY detected_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {**params, "limit": limit, "offset": offset},
            )
        ).mappings().all()
        total = (
            await session.execute(text(f"SELECT COUNT(*) FROM safety_incidents WHERE {where}"), params)
        ).scalar_one()

    items = [SafetyIncident.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.patch("/safety-incidents/{incident_id}/ack")
async def acknowledge_incident(
    incident_id: UUID,
    payload: AcknowledgeIncidentRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    now = datetime.now(timezone.utc)
    new_status = IncidentStatus.resolved if payload.resolve else IncidentStatus.acknowledged
    async with TenantAwareSession(auth.organization_id) as session:
        from sqlalchemy import text
        row = (
            await session.execute(
                text(
                    """
                    UPDATE safety_incidents
                    SET status = :status,
                        acknowledged_by = :user_id,
                        resolved_at = CASE WHEN :resolve THEN :now ELSE resolved_at END
                    WHERE id = :id AND organization_id = :org
                    RETURNING *
                    """
                ),
                {
                    "status": new_status.value,
                    "user_id": str(auth.user_id),
                    "resolve": payload.resolve,
                    "now": now,
                    "id": str(incident_id),
                    "org": str(auth.organization_id),
                },
            )
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="incident_not_found")
    return ok(SafetyIncident.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Reports ----------

@router.post("/reports/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_report(
    payload: WeeklyReportGenerateRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    if payload.week_end < payload.week_start:
        raise HTTPException(status_code=400, detail="week_end must be on or after week_start")

    from ml.pipelines.siteeye import generate_weekly_report

    report = await generate_weekly_report(
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        week_start=payload.week_start,
        week_end=payload.week_end,
    )
    return ok(report.model_dump(mode="json"))


@router.get("/reports")
async def list_reports(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = WeeklyReportListFilters(project_id=project_id, limit=limit, offset=offset)
    async with TenantAwareSession(auth.organization_id) as session:
        from sqlalchemy import text
        where = "organization_id = :org"
        params: dict = {"org": str(auth.organization_id)}
        if filters.project_id:
            where += " AND project_id = :project_id"
            params["project_id"] = str(filters.project_id)
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT * FROM weekly_reports
                    WHERE {where}
                    ORDER BY week_start DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {**params, "limit": limit, "offset": offset},
            )
        ).mappings().all()
        total = (
            await session.execute(text(f"SELECT COUNT(*) FROM weekly_reports WHERE {where}"), params)
        ).scalar_one()
    items = [WeeklyReport.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.post("/reports/{report_id}/send")
async def send_report(
    report_id: UUID,
    payload: SendReportRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    from ml.pipelines.siteeye import email_weekly_report

    sent = await email_weekly_report(
        organization_id=auth.organization_id,
        report_id=report_id,
        recipients=payload.recipients,
        subject=payload.subject,
        message=payload.message,
    )
    if not sent:
        raise HTTPException(status_code=404, detail="report_not_found")
    return ok({"report_id": str(report_id), "sent_to": payload.recipients, "sent_at": datetime.now(timezone.utc).isoformat()})


# ---------- Helpers ----------

def _visit_where(f: VisitListFilters, org_id: UUID) -> tuple[str, dict]:
    clauses = ["v.organization_id = :org"]
    params: dict = {"org": str(org_id)}
    if f.project_id:
        clauses.append("v.project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.date_from:
        clauses.append("v.visit_date >= :date_from")
        params["date_from"] = f.date_from
    if f.date_to:
        clauses.append("v.visit_date <= :date_to")
        params["date_to"] = f.date_to
    return " AND ".join(clauses), params


def _photo_where(f: PhotoListFilters, org_id: UUID) -> tuple[str, dict]:
    clauses = ["organization_id = :org"]
    params: dict = {"org": str(org_id)}
    if f.project_id:
        clauses.append("project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.site_visit_id:
        clauses.append("site_visit_id = :visit_id")
        params["visit_id"] = str(f.site_visit_id)
    if f.safety_status:
        clauses.append("safety_status = :safety_status")
        params["safety_status"] = f.safety_status.value
    if f.tags:
        clauses.append("tags && :tags")
        params["tags"] = f.tags
    if f.date_from:
        clauses.append("taken_at >= :date_from")
        params["date_from"] = f.date_from
    if f.date_to:
        clauses.append("taken_at < (CAST(:date_to AS date) + INTERVAL '1 day')")
        params["date_to"] = f.date_to
    return " AND ".join(clauses), params


def _incident_where(f: SafetyIncidentFilters, org_id: UUID) -> tuple[str, dict]:
    clauses = ["organization_id = :org"]
    params: dict = {"org": str(org_id)}
    if f.project_id:
        clauses.append("project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.status:
        clauses.append("status = :status")
        params["status"] = f.status.value
    if f.severity:
        clauses.append("severity = :severity")
        params["severity"] = f.severity.value
    if f.incident_type:
        clauses.append("incident_type = :incident_type")
        params["incident_type"] = f.incident_type.value
    if f.date_from:
        clauses.append("detected_at >= :date_from")
        params["date_from"] = f.date_from
    if f.date_to:
        clauses.append("detected_at < (CAST(:date_to AS date) + INTERVAL '1 day')")
        params["date_to"] = f.date_to
    return " AND ".join(clauses), params


def _row_to_photo(row: dict) -> SitePhoto:
    data = dict(row)
    ai = data.get("ai_analysis")
    if ai and isinstance(ai, dict):
        data["ai_analysis"] = PhotoAIAnalysis.model_validate(ai)
    data["tags"] = data.get("tags") or []
    return SitePhoto.model_validate(data)


def pg_insert_site_visit(**values):
    from sqlalchemy import text
    return text(
        """
        INSERT INTO site_visits
          (organization_id, project_id, visit_date, location, reported_by,
           weather, workers_count, notes)
        VALUES
          (:organization_id, :project_id, :visit_date, CAST(:location AS jsonb),
           :reported_by, :weather, :workers_count, :notes)
        RETURNING *
        """
    ).bindparams(
        **{
            k: (v if k != "location" else (__import__("json").dumps(v) if v else None))
            for k, v in values.items()
        }
    )


def _infer_schedule_status(snapshots: list[ProgressSnapshot]) -> str:
    if len(snapshots) < 2:
        return "unknown"
    last = snapshots[-1].overall_progress_pct
    prev = snapshots[-2].overall_progress_pct
    delta = last - prev
    if delta >= 3:
        return "ahead"
    if delta >= 1:
        return "on_track"
    return "behind"
