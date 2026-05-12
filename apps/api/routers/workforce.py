"""WORKFORCE router — VN labor records endpoints.

Anchors:
  Bộ luật Lao động 2019 · Luật ATVSLĐ 84/2015 + NĐ 44/2016 ·
  Luật BHXH 58/2014 · NĐ 152/2020 (foreign workers).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.workforce import (
    Assignment,
    AssignmentCreate,
    ForeignPermit,
    InsuranceEnrollment,
    InsuranceEnrollmentCreate,
    PermitCreate,
    SafetyTraining,
    SafetyTrainingCreate,
    Worker,
    WorkerCreate,
    WorkerDetail,
    WorkerListFilters,
    WorkerStatus,
    WorkerSummary,
    WorkerUpdate,
    WorkforceAlert,
    compute_monthly_contribution,
    default_valid_until,
)

router = APIRouter(prefix="/api/v1/workforce", tags=["workforce"])


# ---------- Workers ----------


@router.post("/workers", status_code=status.HTTP_201_CREATED)
async def create_worker(
    payload: WorkerCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    worker_id = uuid4()
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO workers
                      (id, organization_id, full_name, dob, gender, id_no,
                       id_issued_date, id_issued_place, phone, address, trade,
                       employment_type, employer_org_name, nationality, status,
                       hire_date, notes, created_by, created_at, updated_at)
                    VALUES
                      (:id, :org, :full_name, :dob, :gender, :id_no,
                       :id_issued_date, :id_issued_place, :phone, :address, :trade,
                       :employment_type, :employer_org_name, :nationality, 'active',
                       :hire_date, :notes, :created_by, NOW(), NOW())
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(worker_id),
                        "org": str(auth.organization_id),
                        "full_name": payload.full_name,
                        "dob": payload.dob,
                        "gender": payload.gender,
                        "id_no": payload.id_no,
                        "id_issued_date": payload.id_issued_date,
                        "id_issued_place": payload.id_issued_place,
                        "phone": payload.phone,
                        "address": payload.address,
                        "trade": payload.trade,
                        "employment_type": payload.employment_type.value,
                        "employer_org_name": payload.employer_org_name,
                        "nationality": payload.nationality,
                        "hire_date": payload.hire_date,
                        "notes": payload.notes,
                        "created_by": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(Worker.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/workers")
async def list_workers(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    trade: str | None = None,
    worker_status: WorkerStatus | None = Query(None, alias="status"),
    nationality: str | None = None,
    q: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = WorkerListFilters(
        project_id=project_id,
        trade=trade,
        status=worker_status,
        nationality=nationality,
        q=q,
        limit=limit,
        offset=offset,
    )
    where, params = _worker_where(filters, auth.organization_id)

    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT w.*,
                      EXISTS (
                        SELECT 1 FROM worker_safety_trainings t
                        WHERE t.worker_id = w.id
                          AND t.status = 'valid'
                          AND t.valid_until >= CURRENT_DATE
                      ) AS has_valid_safety_training,
                      EXISTS (
                        SELECT 1 FROM worker_insurance_enrollments i
                        WHERE i.worker_id = w.id
                          AND i.status = 'enrolled'
                      ) AS has_active_insurance,
                      EXISTS (
                        SELECT 1 FROM foreign_worker_permits p
                        WHERE p.worker_id = w.id
                          AND p.status = 'approved'
                          AND (p.expiry_date IS NULL OR p.expiry_date >= CURRENT_DATE)
                      ) AS has_active_permit,
                      (
                        SELECT COUNT(*) FROM project_worker_assignments a
                        WHERE a.worker_id = w.id AND a.status = 'active'
                      )::int AS active_assignment_count
                    FROM workers w
                    WHERE {where}
                    ORDER BY w.full_name ASC
                    LIMIT :limit OFFSET :offset
                    """
                    ),
                    {**params, "limit": limit, "offset": offset},
                )
            )
            .mappings()
            .all()
        )
        total = (await session.execute(text(f"SELECT COUNT(*) FROM workers w WHERE {where}"), params)).scalar_one()

    items = [WorkerSummary.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.get("/workers/{worker_id}")
async def get_worker(
    worker_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        worker = (
            (
                await session.execute(
                    text("SELECT * FROM workers WHERE id = :id AND organization_id = :org"),
                    {"id": str(worker_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if worker is None:
            raise HTTPException(status_code=404, detail="worker_not_found")

        trainings = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM worker_safety_trainings
                    WHERE worker_id = :id
                    ORDER BY training_date DESC
                    """
                    ),
                    {"id": str(worker_id)},
                )
            )
            .mappings()
            .all()
        )
        insurance = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM worker_insurance_enrollments
                    WHERE worker_id = :id
                    ORDER BY created_at DESC
                    """
                    ),
                    {"id": str(worker_id)},
                )
            )
            .mappings()
            .all()
        )
        permits = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM foreign_worker_permits
                    WHERE worker_id = :id
                    ORDER BY created_at DESC
                    """
                    ),
                    {"id": str(worker_id)},
                )
            )
            .mappings()
            .all()
        )
        assignments = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM project_worker_assignments
                    WHERE worker_id = :id
                    ORDER BY start_date DESC
                    """
                    ),
                    {"id": str(worker_id)},
                )
            )
            .mappings()
            .all()
        )

    detail = WorkerDetail.model_validate(
        {
            **dict(worker),
            "safety_trainings": [SafetyTraining.model_validate(dict(t)) for t in trainings],
            "insurance_enrollments": [InsuranceEnrollment.model_validate(dict(i)) for i in insurance],
            "foreign_permits": [ForeignPermit.model_validate(dict(p)) for p in permits],
            "assignments": [Assignment.model_validate(dict(a)) for a in assignments],
        }
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/workers/{worker_id}")
async def update_worker(
    worker_id: UUID,
    payload: WorkerUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(worker_id), "org": str(auth.organization_id)}
    for col, val in (
        ("full_name", payload.full_name),
        ("phone", payload.phone),
        ("address", payload.address),
        ("trade", payload.trade),
        ("employer_org_name", payload.employer_org_name),
        ("termination_date", payload.termination_date),
        ("notes", payload.notes),
    ):
        if val is None:
            continue
        assigns.append(f"{col} = :{col}")
        params[col] = val
    if payload.employment_type is not None:
        assigns.append("employment_type = :employment_type")
        params["employment_type"] = payload.employment_type.value
    if payload.status is not None:
        assigns.append("status = :status")
        params["status"] = payload.status.value
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE workers SET {", ".join(assigns)}
                    WHERE id = :id AND organization_id = :org
                    RETURNING *
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise HTTPException(status_code=404, detail="worker_not_found")
    return ok(Worker.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Safety training ----------


@router.post("/workers/{worker_id}/training", status_code=status.HTTP_201_CREATED)
async def record_training(
    worker_id: UUID,
    payload: SafetyTrainingCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Record an ATLD training session. `valid_until` defaults per NĐ
    44/2016 cycle (2y for groups 1/2/5/6; 3y for 3/4)."""
    valid_until = payload.valid_until or default_valid_until(payload.group, payload.training_date)

    async with TenantAwareSession(auth.organization_id) as session:
        worker = (
            await session.execute(
                text("SELECT id FROM workers WHERE id = :id AND organization_id = :org"),
                {"id": str(worker_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if worker is None:
            raise HTTPException(status_code=404, detail="worker_not_found")

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO worker_safety_trainings
                      (id, organization_id, worker_id, "group", training_org,
                       training_date, valid_until, certificate_no, certificate_file_id,
                       status, notes)
                    VALUES
                      (:id, :org, :worker_id, :group, :training_org,
                       :training_date, :valid_until, :certificate_no, :certificate_file_id,
                       'valid', :notes)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "worker_id": str(worker_id),
                        "group": payload.group.value,
                        "training_org": payload.training_org,
                        "training_date": payload.training_date,
                        "valid_until": valid_until,
                        "certificate_no": payload.certificate_no,
                        "certificate_file_id": str(payload.certificate_file_id)
                        if payload.certificate_file_id
                        else None,
                        "notes": payload.notes,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(SafetyTraining.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Insurance ----------


@router.post("/workers/{worker_id}/insurance", status_code=status.HTTP_201_CREATED)
async def enroll_insurance(
    worker_id: UUID,
    payload: InsuranceEnrollmentCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Enroll a worker in BHXH/BHYT/BHTN.

    Idempotent-ish: existing active enrollment is marked `superseded`
    with `superseded_by_id` pointing at the new row, preserving the
    audit trail of salary changes.
    """
    new_id = uuid4()
    async with TenantAwareSession(auth.organization_id) as session:
        worker = (
            await session.execute(
                text("SELECT id FROM workers WHERE id = :id AND organization_id = :org"),
                {"id": str(worker_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if worker is None:
            raise HTTPException(status_code=404, detail="worker_not_found")

        new_row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO worker_insurance_enrollments
                      (id, organization_id, worker_id, basic_salary_vnd,
                       bhxh_enrolled, bhyt_enrolled, bhtn_enrolled, bhxh_no,
                       enrolled_at, status, notes)
                    VALUES
                      (:id, :org, :worker_id, :salary,
                       :bhxh, :bhyt, :bhtn, :bhxh_no,
                       :enrolled_at, 'enrolled', :notes)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(new_id),
                        "org": str(auth.organization_id),
                        "worker_id": str(worker_id),
                        "salary": payload.basic_salary_vnd,
                        "bhxh": payload.bhxh_enrolled,
                        "bhyt": payload.bhyt_enrolled,
                        "bhtn": payload.bhtn_enrolled,
                        "bhxh_no": payload.bhxh_no,
                        "enrolled_at": payload.enrolled_at,
                        "notes": payload.notes,
                    },
                )
            )
            .mappings()
            .one()
        )
        # Supersede any prior `enrolled` row.
        await session.execute(
            text(
                """
            UPDATE worker_insurance_enrollments SET
              status = 'superseded',
              superseded_by_id = :new_id
            WHERE worker_id = :worker_id
              AND id <> :new_id
              AND status = 'enrolled'
            """
            ),
            {"new_id": str(new_id), "worker_id": str(worker_id)},
        )
    return ok(InsuranceEnrollment.model_validate(dict(new_row)).model_dump(mode="json"))


@router.get("/workers/{worker_id}/insurance/contribution")
async def compute_contribution(
    worker_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Read the active enrollment + return monthly contribution math.

    Pure-Python — no DB write. Surfaces the breakdown the payroll team
    expects each month: BHXH/BHYT/BHTN per side + KPCĐ + totals.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT basic_salary_vnd, bhxh_enrolled, bhyt_enrolled, bhtn_enrolled
                    FROM worker_insurance_enrollments
                    WHERE worker_id = :id
                      AND organization_id = :org
                      AND status = 'enrolled'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                    ),
                    {"id": str(worker_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="no_active_enrollment")
    breakdown = compute_monthly_contribution(
        int(row["basic_salary_vnd"]),
        bhxh=bool(row["bhxh_enrolled"]),
        bhyt=bool(row["bhyt_enrolled"]),
        bhtn=bool(row["bhtn_enrolled"]),
    )
    return ok(breakdown)


# ---------- Foreign permit ----------


@router.post("/workers/{worker_id}/permit", status_code=status.HTTP_201_CREATED)
async def create_permit(
    worker_id: UUID,
    payload: PermitCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        worker = (
            (
                await session.execute(
                    text("SELECT id, nationality FROM workers WHERE id = :id AND organization_id = :org"),
                    {"id": str(worker_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if worker is None:
            raise HTTPException(status_code=404, detail="worker_not_found")
        if worker["nationality"] == "VN":
            raise HTTPException(
                status_code=422,
                detail="permit_only_for_foreign_workers",
            )

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO foreign_worker_permits
                      (id, organization_id, worker_id, nationality, passport_no,
                       job_position, permit_no, issue_date, expiry_date,
                       exemption_type, status, notes, created_at, updated_at)
                    VALUES
                      (:id, :org, :worker_id, :nationality, :passport_no,
                       :job_position, :permit_no, :issue_date, :expiry_date,
                       :exemption_type, 'pending', :notes, NOW(), NOW())
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "worker_id": str(worker_id),
                        "nationality": payload.nationality,
                        "passport_no": payload.passport_no,
                        "job_position": payload.job_position,
                        "permit_no": payload.permit_no,
                        "issue_date": payload.issue_date,
                        "expiry_date": payload.expiry_date,
                        "exemption_type": payload.exemption_type.value,
                        "notes": payload.notes,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(ForeignPermit.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Assignments ----------


@router.post("/workers/{worker_id}/assign", status_code=status.HTTP_201_CREATED)
async def assign_to_project(
    worker_id: UUID,
    payload: AssignmentCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        worker = (
            await session.execute(
                text("SELECT id FROM workers WHERE id = :id AND organization_id = :org"),
                {"id": str(worker_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if worker is None:
            raise HTTPException(status_code=404, detail="worker_not_found")

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO project_worker_assignments
                      (id, organization_id, worker_id, project_id, role_on_project,
                       start_date, end_date, status, notes)
                    VALUES
                      (:id, :org, :worker_id, :project_id, :role,
                       :start_date, :end_date, 'active', :notes)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "worker_id": str(worker_id),
                        "project_id": str(payload.project_id),
                        "role": payload.role_on_project,
                        "start_date": payload.start_date,
                        "end_date": payload.end_date,
                        "notes": payload.notes,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(Assignment.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/projects/{project_id}/manifest")
async def project_manifest(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """All workers currently assigned to a project, with compliance flags."""
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT w.*,
                      a.start_date AS assignment_start,
                      a.end_date AS assignment_end,
                      a.role_on_project,
                      EXISTS (
                        SELECT 1 FROM worker_safety_trainings t
                        WHERE t.worker_id = w.id
                          AND t.status = 'valid'
                          AND t.valid_until >= CURRENT_DATE
                      ) AS has_valid_safety_training,
                      EXISTS (
                        SELECT 1 FROM worker_insurance_enrollments i
                        WHERE i.worker_id = w.id AND i.status = 'enrolled'
                      ) AS has_active_insurance
                    FROM workers w
                    JOIN project_worker_assignments a ON a.worker_id = w.id
                    WHERE a.project_id = :project_id
                      AND w.organization_id = :org
                      AND a.status = 'active'
                    ORDER BY w.full_name
                    """
                    ),
                    {"project_id": str(project_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .all()
        )
    return ok([dict(r) for r in rows])


# ---------- Alerts ----------


@router.get("/alerts")
async def workforce_alerts(
    auth: Annotated[AuthContext, Depends(require_auth)],
    expiring_within_days: int = Query(60, ge=1, le=365),
):
    """Surface expiring trainings + permits + missing-insurance workers."""
    today = date.today()
    horizon = today + timedelta(days=expiring_within_days)
    params: dict[str, Any] = {
        "org": str(auth.organization_id),
        "today": today,
        "horizon": horizon,
    }

    async with TenantAwareSession(auth.organization_id) as session:
        training_alerts = (
            (
                await session.execute(
                    text(
                        """
                    SELECT t.id AS training_id, t.worker_id, t.valid_until,
                           (t.valid_until - :today) AS days_until
                    FROM worker_safety_trainings t
                    WHERE t.organization_id = :org
                      AND t.status = 'valid'
                      AND t.valid_until BETWEEN :today AND :horizon
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        permit_alerts = (
            (
                await session.execute(
                    text(
                        """
                    SELECT p.id AS permit_id, p.worker_id, p.expiry_date,
                           (p.expiry_date - :today) AS days_until
                    FROM foreign_worker_permits p
                    WHERE p.organization_id = :org
                      AND p.status = 'approved'
                      AND p.expiry_date IS NOT NULL
                      AND p.expiry_date BETWEEN :today AND :horizon
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        missing_insurance = (
            (
                await session.execute(
                    text(
                        """
                    SELECT w.id AS worker_id, w.full_name
                    FROM workers w
                    WHERE w.organization_id = :org
                      AND w.status = 'active'
                      AND w.employment_type IN ('direct', 'foreign')
                      AND NOT EXISTS (
                        SELECT 1 FROM worker_insurance_enrollments i
                        WHERE i.worker_id = w.id AND i.status = 'enrolled'
                      )
                    """
                    ),
                    {"org": str(auth.organization_id)},
                )
            )
            .mappings()
            .all()
        )

    alerts: list[WorkforceAlert] = []
    for r in training_alerts:
        days = int(r["days_until"])
        alerts.append(
            WorkforceAlert(
                worker_id=r["worker_id"],
                code="safety_training_expiring",
                severity="critical" if days <= 14 else "warning" if days <= 30 else "info",
                message=f"ATLD training expires in {days} day(s)",
                related_id=r["training_id"],
                days_until=days,
                expiry_date=r["valid_until"],
            )
        )
    for r in permit_alerts:
        days = int(r["days_until"])
        alerts.append(
            WorkforceAlert(
                worker_id=r["worker_id"],
                code="permit_expiring",
                severity="critical" if days <= 30 else "warning",
                message=f"Foreign work permit expires in {days} day(s)",
                related_id=r["permit_id"],
                days_until=days,
                expiry_date=r["expiry_date"],
            )
        )
    for r in missing_insurance:
        alerts.append(
            WorkforceAlert(
                worker_id=r["worker_id"],
                code="missing_insurance",
                severity="warning",
                message=f"{r['full_name']} chưa được đăng ký BHXH/BHYT/BHTN",
            )
        )

    return ok([a.model_dump(mode="json") for a in alerts])


# ---------- Helpers ----------


def _worker_where(f: WorkerListFilters, org_id: UUID) -> tuple[str, dict[str, Any]]:
    clauses = ["w.organization_id = :org"]
    params: dict[str, Any] = {"org": str(org_id)}
    if f.project_id:
        clauses.append(
            "EXISTS (SELECT 1 FROM project_worker_assignments a "
            "WHERE a.worker_id = w.id AND a.project_id = :project_id "
            "AND a.status = 'active')"
        )
        params["project_id"] = str(f.project_id)
    if f.trade:
        clauses.append("w.trade = :trade")
        params["trade"] = f.trade
    if f.status:
        clauses.append("w.status = :status")
        params["status"] = f.status.value
    if f.employment_type:
        clauses.append("w.employment_type = :employment_type")
        params["employment_type"] = f.employment_type.value
    if f.nationality:
        clauses.append("w.nationality = :nationality")
        params["nationality"] = f.nationality
    if f.q:
        clauses.append("(w.full_name ILIKE :q_like OR w.id_no = :q)")
        params["q_like"] = f"%{f.q}%"
        params["q"] = f.q
    return " AND ".join(clauses), params


__all__ = ["router"]


_ = datetime, UTC  # silence unused-import if helpers stop referencing
