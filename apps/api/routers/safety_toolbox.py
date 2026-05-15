"""SafetyToolboxTalks — Báo cáo họp an toàn đầu ca.

Endpoints:
  * POST   /api/v1/safety-toolbox/projects/{project_id}/talks
  * GET    /api/v1/safety-toolbox/projects/{project_id}/talks
  * GET    /api/v1/safety-toolbox/talks/{talk_id}
  * POST   /api/v1/safety-toolbox/talks/{talk_id}/attendance — bulk add workers
  * DELETE /api/v1/safety-toolbox/talks/{talk_id}
  * GET    /api/v1/safety-toolbox/projects/{project_id}/compliance — KPI

The compliance endpoint is the load-bearing one for Sở Xây dựng audits:
returns "% of working days in last N days that had a recorded
toolbox talk" — the metric inspectors actually check.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from core.envelope import ok
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role

router = APIRouter(prefix="/api/v1/safety-toolbox", tags=["safety-toolbox"])


# ---------- Schemas ----------


class AttendeePayload(BaseModel):
    worker_name: str = Field(min_length=1, max_length=200)
    worker_phone: str | None = Field(default=None, max_length=20)
    worker_role: str | None = Field(default=None, max_length=100)
    subcontractor: str | None = Field(default=None, max_length=200)
    signed: bool = True


class ToolboxTalkCreate(BaseModel):
    held_on: date
    shift: Literal["morning", "afternoon", "night"] = "morning"
    topic: str = Field(min_length=2, max_length=500)
    content_notes: str | None = Field(default=None, max_length=5000)
    presenter_name: str = Field(min_length=1, max_length=200)
    presenter_role: str | None = Field(default=None, max_length=100)
    ppe_checks: dict[str, str] | None = None
    siteeye_visit_id: UUID | None = None
    signature_file_id: UUID | None = None
    attendees: list[AttendeePayload] = Field(default_factory=list)


class ToolboxTalkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    held_on: date
    shift: str
    topic: str
    content_notes: str | None
    presenter_name: str
    presenter_role: str | None
    ppe_checks: dict[str, Any] | None
    attendee_count: int
    signed_count: int
    siteeye_visit_id: UUID | None
    signature_file_id: UUID | None
    created_at: datetime


# ---------- Create ----------


@router.post(
    "/projects/{project_id}/talks",
    status_code=status.HTTP_201_CREATED,
)
async def create_talk(
    project_id: UUID,
    payload: ToolboxTalkCreate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.MEMBER))],
):
    """Record a safety briefing + its attendance ledger.

    Member-writable (the supervisor / HSE officer logging the briefing
    is rarely a platform owner). Server-side uniqueness on
    (project, date, shift) prevents accidental double-entry; the
    client's "Tải ảnh chữ ký" upload flow normally guarantees this,
    but the constraint is the load-bearing safety.
    """
    talk_id = uuid4()
    async with TenantAwareSession(auth.organization_id) as session:
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO safety_toolbox_talks
                        (id, organization_id, project_id, held_on, shift, topic,
                         content_notes, presenter_name, presenter_role,
                         ppe_checks, siteeye_visit_id, signature_file_id,
                         recorded_by)
                    VALUES (:id, :org, :pid, :date, :shift, :topic,
                            :notes, :pname, :prole,
                            CAST(:ppe AS jsonb), :visit, :sig,
                            :uid)
                    """
                ),
                {
                    "id": str(talk_id),
                    "org": str(auth.organization_id),
                    "pid": str(project_id),
                    "date": payload.held_on,
                    "shift": payload.shift,
                    "topic": payload.topic,
                    "notes": payload.content_notes,
                    "pname": payload.presenter_name,
                    "prole": payload.presenter_role,
                    "ppe": __import__("json").dumps(payload.ppe_checks)
                    if payload.ppe_checks
                    else None,
                    "visit": str(payload.siteeye_visit_id)
                    if payload.siteeye_visit_id
                    else None,
                    "sig": str(payload.signature_file_id)
                    if payload.signature_file_id
                    else None,
                    "uid": str(auth.user_id),
                },
            )
        except Exception as exc:
            # Unique constraint violation = duplicate briefing for the
            # same project+date+shift. Surface a recognisable error.
            msg = str(exc).lower()
            if "uq_safety_talk_project_date_shift" in msg or "duplicate key" in msg:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "talk_already_exists_for_project_date_shift",
                ) from exc
            raise

        for attendee in payload.attendees:
            await session.execute(
                text(
                    """
                    INSERT INTO safety_toolbox_attendance
                        (id, organization_id, talk_id, worker_name,
                         worker_phone, worker_role, subcontractor, signed)
                    VALUES (:id, :org, :talk, :name, :phone, :role, :sub, :signed)
                    """
                ),
                {
                    "id": str(uuid4()),
                    "org": str(auth.organization_id),
                    "talk": str(talk_id),
                    "name": attendee.worker_name,
                    "phone": attendee.worker_phone,
                    "role": attendee.worker_role,
                    "sub": attendee.subcontractor,
                    "signed": attendee.signed,
                },
            )

        await session.commit()

    return ok({"id": str(talk_id), "attendee_count": len(payload.attendees)})


# ---------- List + read ----------


@router.get("/projects/{project_id}/talks")
async def list_project_talks(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    since: Annotated[date | None, Query()] = None,
    until: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    """List briefings for a project. Default returns the last 100 records;
    a date range narrows it for compliance reports."""
    where = ["t.project_id = :pid"]
    params: dict[str, Any] = {"pid": str(project_id), "limit": limit}
    if since:
        where.append("t.held_on >= :since")
        params["since"] = since
    if until:
        where.append("t.held_on <= :until")
        params["until"] = until

    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT
                        t.id, t.held_on, t.shift, t.topic, t.content_notes,
                        t.presenter_name, t.presenter_role, t.ppe_checks,
                        t.siteeye_visit_id, t.signature_file_id, t.created_at,
                        COUNT(a.id)::int AS attendee_count,
                        COUNT(a.id) FILTER (WHERE a.signed)::int AS signed_count
                    FROM safety_toolbox_talks t
                    LEFT JOIN safety_toolbox_attendance a ON a.talk_id = t.id
                    WHERE {' AND '.join(where)}
                    GROUP BY t.id
                    ORDER BY t.held_on DESC, t.shift ASC
                    LIMIT :limit
                    """
                ),
                params,
            )
        ).mappings().all()

    return ok(
        {
            "talks": [
                {
                    "id": str(r["id"]),
                    "held_on": r["held_on"].isoformat(),
                    "shift": r["shift"],
                    "topic": r["topic"],
                    "content_notes": r["content_notes"],
                    "presenter_name": r["presenter_name"],
                    "presenter_role": r["presenter_role"],
                    "ppe_checks": r["ppe_checks"],
                    "attendee_count": r["attendee_count"],
                    "signed_count": r["signed_count"],
                    "siteeye_visit_id": str(r["siteeye_visit_id"])
                    if r["siteeye_visit_id"]
                    else None,
                    "signature_file_id": str(r["signature_file_id"])
                    if r["signature_file_id"]
                    else None,
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ]
        }
    )


@router.get("/talks/{talk_id}")
async def get_talk_detail(
    talk_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Talk metadata + full attendance ledger."""
    async with TenantAwareSession(auth.organization_id) as session:
        talk = (
            await session.execute(
                text(
                    """
                    SELECT id, held_on, shift, topic, content_notes,
                           presenter_name, presenter_role, ppe_checks,
                           siteeye_visit_id, signature_file_id, created_at
                    FROM safety_toolbox_talks
                    WHERE id = :id
                    """
                ),
                {"id": str(talk_id)},
            )
        ).mappings().one_or_none()
        if talk is None:
            raise HTTPException(404, "talk_not_found")

        attendees = (
            await session.execute(
                text(
                    """
                    SELECT id, worker_name, worker_phone, worker_role,
                           subcontractor, signed
                    FROM safety_toolbox_attendance
                    WHERE talk_id = :id
                    ORDER BY worker_name ASC
                    """
                ),
                {"id": str(talk_id)},
            )
        ).mappings().all()

    return ok(
        {
            "talk": {
                "id": str(talk["id"]),
                "held_on": talk["held_on"].isoformat(),
                "shift": talk["shift"],
                "topic": talk["topic"],
                "content_notes": talk["content_notes"],
                "presenter_name": talk["presenter_name"],
                "presenter_role": talk["presenter_role"],
                "ppe_checks": talk["ppe_checks"],
                "siteeye_visit_id": str(talk["siteeye_visit_id"])
                if talk["siteeye_visit_id"]
                else None,
                "signature_file_id": str(talk["signature_file_id"])
                if talk["signature_file_id"]
                else None,
                "created_at": talk["created_at"].isoformat(),
            },
            "attendees": [
                {
                    "id": str(a["id"]),
                    "worker_name": a["worker_name"],
                    "worker_phone": a["worker_phone"],
                    "worker_role": a["worker_role"],
                    "subcontractor": a["subcontractor"],
                    "signed": a["signed"],
                }
                for a in attendees
            ],
        }
    )


# ---------- Bulk add attendees ----------


@router.post(
    "/talks/{talk_id}/attendance",
    status_code=status.HTTP_201_CREATED,
)
async def add_attendees(
    talk_id: UUID,
    attendees: list[AttendeePayload],
    auth: Annotated[AuthContext, Depends(require_min_role(Role.MEMBER))],
):
    """Bulk-add workers to an existing talk's attendance.

    Used when the supervisor logs the talk first, then takes a few
    minutes collecting signatures. Each call APPENDS — duplicate names
    aren't deduped (workers may share a name).
    """
    async with TenantAwareSession(auth.organization_id) as session:
        # Verify the talk exists in the caller's org (RLS handles
        # cross-tenant guard but we need the explicit 404).
        exists = (
            await session.execute(
                text("SELECT 1 FROM safety_toolbox_talks WHERE id = :id"),
                {"id": str(talk_id)},
            )
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(404, "talk_not_found")

        for attendee in attendees:
            await session.execute(
                text(
                    """
                    INSERT INTO safety_toolbox_attendance
                        (id, organization_id, talk_id, worker_name,
                         worker_phone, worker_role, subcontractor, signed)
                    VALUES (:id, :org, :talk, :name, :phone, :role, :sub, :signed)
                    """
                ),
                {
                    "id": str(uuid4()),
                    "org": str(auth.organization_id),
                    "talk": str(talk_id),
                    "name": attendee.worker_name,
                    "phone": attendee.worker_phone,
                    "role": attendee.worker_role,
                    "sub": attendee.subcontractor,
                    "signed": attendee.signed,
                },
            )
        await session.commit()

    return ok({"added": len(attendees)})


# ---------- Delete (owner only) ----------


@router.delete(
    "/talks/{talk_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_talk(
    talk_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.OWNER))],
):
    """Owner-only. Compliance records are normally append-only; only
    delete when a duplicate was accidentally created and needs cleanup."""
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text("DELETE FROM safety_toolbox_talks WHERE id = :id"),
            {"id": str(talk_id)},
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "talk_not_found")


# ---------- Compliance KPI (the load-bearing audit endpoint) ----------


@router.get("/projects/{project_id}/compliance")
async def compliance_summary(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    days: Annotated[int, Query(ge=7, le=365)] = 30,
):
    """% of working days in the last N days that had a recorded
    toolbox talk.

    "Working days" = Mon-Sat (VN construction works 6-day weeks
    typically). Sunday is excluded. We don't model holidays; ops
    docs explain the optional manual adjustment for Tet.

    Returns:
      * coverage_pct       — % of working days with ≥1 talk
      * working_days       — denominator
      * days_with_talks    — numerator
      * missing_dates      — first 10 working days WITHOUT a talk
                             (auditor's "show me your gaps" view)
      * avg_attendees      — average head count per briefing
    """
    until = date.today()
    since = until - timedelta(days=days - 1)

    async with TenantAwareSession(auth.organization_id) as session:
        # Distinct dates with at least one talk
        held_dates = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT held_on
                    FROM safety_toolbox_talks
                    WHERE project_id = :pid
                      AND held_on >= :since
                      AND held_on <= :until
                    """
                ),
                {"pid": str(project_id), "since": since, "until": until},
            )
        ).scalars().all()

        # Average attendees per talk in window
        avg_row = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(AVG(c.attendee_count), 0)::numeric AS avg_count
                    FROM (
                        SELECT t.id, COUNT(a.id) AS attendee_count
                        FROM safety_toolbox_talks t
                        LEFT JOIN safety_toolbox_attendance a ON a.talk_id = t.id
                        WHERE t.project_id = :pid
                          AND t.held_on >= :since
                          AND t.held_on <= :until
                        GROUP BY t.id
                    ) c
                    """
                ),
                {"pid": str(project_id), "since": since, "until": until},
            )
        ).mappings().one()

    held_set = set(held_dates)
    working_days = 0
    missing: list[str] = []
    cursor = since
    while cursor <= until:
        # Mon=0 … Sun=6 — exclude Sunday only.
        if cursor.weekday() != 6:
            working_days += 1
            if cursor not in held_set:
                missing.append(cursor.isoformat())
        cursor += timedelta(days=1)

    days_with_talks = working_days - len(missing)
    coverage_pct = (
        round((days_with_talks / working_days) * 100, 1) if working_days else 0.0
    )

    return ok(
        {
            "window": {
                "since": since.isoformat(),
                "until": until.isoformat(),
                "days": days,
            },
            "working_days": working_days,
            "days_with_talks": days_with_talks,
            "coverage_pct": coverage_pct,
            "missing_dates": missing[:10],
            "missing_dates_total": len(missing),
            "avg_attendees": round(float(avg_row["avg_count"] or 0), 1),
        }
    )
