"""PCCC router — fire-safety certification endpoints.

State machine:

  planning → submitted → inspection_scheduled → rfi  ⇄  submitted
                                              → approved (+expiry)
                                              → conditional
                                              → rejected
  approved → expired (cron-driven once expiry_date < today)

Acceptance certs get a 5-year `expiry_date` defaulted at approval if
the caller doesn't supply one (NĐ 136/2020). Design appraisals don't
expire and `expiry_date` stays NULL.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.pccc import (
    CertAlert,
    CertDetail,
    CertListFilters,
    CertStatus,
    CertSummary,
    CertType,
    ChecklistItem,
    ChecklistItemCreate,
    ChecklistItemStatus,
    ChecklistItemUpdate,
    FireCert,
    FireCertCreate,
    FireCertTransition,
    FireCertUpdate,
    FireInspection,
    InspectionCreate,
    SeedChecklistRequest,
    default_legal_basis,
)

router = APIRouter(prefix="/api/v1/pccc", tags=["pccc"])


_TRANSITIONS: dict[CertStatus, set[CertStatus]] = {
    CertStatus.planning: {CertStatus.submitted},
    CertStatus.submitted: {CertStatus.inspection_scheduled, CertStatus.rfi, CertStatus.rejected},
    CertStatus.inspection_scheduled: {
        CertStatus.rfi,
        CertStatus.approved,
        CertStatus.conditional,
        CertStatus.rejected,
    },
    CertStatus.rfi: {CertStatus.submitted, CertStatus.rejected},
    CertStatus.conditional: {CertStatus.approved, CertStatus.rejected},
    # Terminal lanes.
    CertStatus.approved: set(),
    CertStatus.rejected: {CertStatus.planning},
    CertStatus.expired: {CertStatus.planning},
}


# Default checklist seed by (hazard_category, building_class). Keep
# small here — production wires a YAML-driven seed via the import
# job, but a minimal default lets a fresh tenant get value on day 1.
_DEFAULT_CHECKLIST: list[dict[str, str]] = [
    {
        "clause_ref": "QCVN 06:2022 §3",
        "category": "Phân loại nguy hiểm cháy",
        "description": "Phân loại nhóm nguy hiểm cháy nổ của các khu vực sản xuất / kho.",
    },
    {
        "clause_ref": "QCVN 06:2022 §4.2",
        "category": "Bậc chịu lửa",
        "description": "Bậc chịu lửa của công trình phù hợp với chiều cao và diện tích sàn.",
    },
    {
        "clause_ref": "QCVN 06:2022 §5",
        "category": "Khoảng cách an toàn",
        "description": "Khoảng cách giữa các công trình và đến ranh giới khu đất đáp ứng yêu cầu.",
    },
    {
        "clause_ref": "QCVN 06:2022 §A.1",
        "category": "Lối thoát nạn",
        "description": "Số lượng và chiều rộng lối thoát nạn phù hợp với số người sử dụng.",
    },
    {
        "clause_ref": "QCVN 06:2022 §D",
        "category": "Hệ thống chữa cháy",
        "description": "Bố trí hệ thống sprinkler / vòi chữa cháy theo nhóm nguy hiểm.",
    },
    {
        "clause_ref": "QCVN 06:2022 §H",
        "category": "Báo cháy tự động",
        "description": "Hệ thống báo cháy tự động bao phủ toàn bộ các khu vực bắt buộc.",
    },
    {
        "clause_ref": "QCVN 06:2022 §F",
        "category": "Chống khói",
        "description": "Hệ thống tăng áp / hút khói cho cầu thang thoát nạn và hành lang.",
    },
    {
        "clause_ref": "NĐ 136/2020 Điều 13",
        "category": "Phương tiện chữa cháy ban đầu",
        "description": "Bố trí bình chữa cháy xách tay và hệ thống chữa cháy ban đầu.",
    },
]


# ---------- Certs ----------


@router.post("/certs", status_code=status.HTTP_201_CREATED)
async def create_cert(
    payload: FireCertCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    cert_id = uuid4()
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO fire_certs
                      (id, organization_id, project_id, cert_type, reference_no,
                       hazard_category, building_class, height_m, floors_above,
                       floors_below, area_sqm, occupant_load, pc07_unit, status,
                       notes, legal_basis, created_by, created_at, updated_at)
                    VALUES
                      (:id, :org, :project_id, :cert_type, :reference_no,
                       :hazard, :building_class, :height_m, :floors_above,
                       :floors_below, :area_sqm, :occupant_load, :pc07, 'planning',
                       :notes, CAST(:legal AS text[]), :created_by, NOW(), NOW())
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(cert_id),
                        "org": str(auth.organization_id),
                        "project_id": str(payload.project_id),
                        "cert_type": payload.cert_type.value,
                        "reference_no": payload.reference_no,
                        "hazard": payload.hazard_category.value,
                        "building_class": payload.building_class.value,
                        "height_m": payload.height_m,
                        "floors_above": payload.floors_above,
                        "floors_below": payload.floors_below,
                        "area_sqm": payload.area_sqm,
                        "occupant_load": payload.occupant_load,
                        "pc07": payload.pc07_unit,
                        "notes": payload.notes,
                        "legal": default_legal_basis(payload.cert_type),
                        "created_by": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(FireCert.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/certs")
async def list_certs(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    cert_type: CertType | None = None,
    cert_status: CertStatus | None = Query(None, alias="status"),
    expiring_within_days: int | None = Query(None, ge=0, le=3650),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = CertListFilters(
        project_id=project_id,
        cert_type=cert_type,
        status=cert_status,
        expiring_within_days=expiring_within_days,
        limit=limit,
        offset=offset,
    )
    where, params = _cert_where(filters, auth.organization_id)

    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT c.*,
                      COALESCE(ck.total, 0)::int AS checklist_total,
                      COALESCE(ck.compliant, 0)::int AS checklist_compliant,
                      COALESCE(ck.non_compliant, 0)::int AS checklist_non_compliant,
                      COALESCE(ins.cnt, 0)::int AS inspection_count
                    FROM fire_certs c
                    LEFT JOIN (
                      SELECT cert_id,
                             COUNT(*) AS total,
                             COUNT(*) FILTER (WHERE status = 'compliant') AS compliant,
                             COUNT(*) FILTER (WHERE status = 'non_compliant') AS non_compliant
                      FROM fire_checklist_items GROUP BY cert_id
                    ) ck ON ck.cert_id = c.id
                    LEFT JOIN (
                      SELECT cert_id, COUNT(*) AS cnt
                      FROM fire_inspections GROUP BY cert_id
                    ) ins ON ins.cert_id = c.id
                    WHERE {where}
                    ORDER BY c.created_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                    ),
                    {**params, "limit": limit, "offset": offset},
                )
            )
            .mappings()
            .all()
        )
        total = (
            await session.execute(text(f"SELECT COUNT(*) FROM fire_certs c WHERE {where}"), params)
        ).scalar_one()

    items = [CertSummary.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.get("/certs/{cert_id}")
async def get_cert(
    cert_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        cert = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM fire_certs
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(cert_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if cert is None:
            raise HTTPException(status_code=404, detail="cert_not_found")

        inspections = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM fire_inspections
                    WHERE cert_id = :id
                    ORDER BY round_number ASC
                    """
                    ),
                    {"id": str(cert_id)},
                )
            )
            .mappings()
            .all()
        )
        checklist = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM fire_checklist_items
                    WHERE cert_id = :id
                    ORDER BY sort_order ASC, created_at ASC
                    """
                    ),
                    {"id": str(cert_id)},
                )
            )
            .mappings()
            .all()
        )

    detail = CertDetail.model_validate(
        {
            **dict(cert),
            "inspections": [FireInspection.model_validate(dict(r)) for r in inspections],
            "checklist": [ChecklistItem.model_validate(dict(r)) for r in checklist],
        }
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/certs/{cert_id}")
async def update_cert(
    cert_id: UUID,
    payload: FireCertUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(cert_id), "org": str(auth.organization_id)}
    for field, col in [
        ("hazard_category", "hazard_category"),
        ("building_class", "building_class"),
        ("height_m", "height_m"),
        ("floors_above", "floors_above"),
        ("floors_below", "floors_below"),
        ("area_sqm", "area_sqm"),
        ("occupant_load", "occupant_load"),
        ("pc07_unit", "pc07_unit"),
        ("submitted_date", "submitted_date"),
        ("inspection_date", "inspection_date"),
        ("decision_date", "decision_date"),
        ("decision_number", "decision_number"),
        ("expiry_date", "expiry_date"),
        ("notes", "notes"),
    ]:
        v = getattr(payload, field)
        if v is None:
            continue
        if hasattr(v, "value"):
            v = v.value
        assigns.append(f"{col} = :{col}")
        params[col] = v
    if payload.decision_file_id is not None:
        assigns.append("decision_file_id = :decision_file_id")
        params["decision_file_id"] = str(payload.decision_file_id)
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE fire_certs SET {", ".join(assigns)}
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
        raise HTTPException(status_code=404, detail="cert_not_found")
    return ok(FireCert.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/certs/{cert_id}/transition")
async def transition_cert(
    cert_id: UUID,
    payload: FireCertTransition,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Status change with side effects.

    Approving an `acceptance` cert defaults `expiry_date` to +5 years
    from `decision_date` per NĐ 136/2020 if the caller omits it.
    `expired` is cron-driven — manual transition rejected with 422.
    """
    if payload.to_status == CertStatus.expired:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "manual_expire_not_allowed",
                "message": "Status 'expired' is set by the alerts cron, not by user action.",
            },
        )

    async with TenantAwareSession(auth.organization_id) as session:
        current = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM fire_certs
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(cert_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if current is None:
            raise HTTPException(status_code=404, detail="cert_not_found")

        cur_status = CertStatus(current["status"])
        allowed = _TRANSITIONS.get(cur_status, set())
        if payload.to_status not in allowed:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_transition",
                    "message": (
                        f"Cannot transition cert from '{cur_status.value}' to "
                        f"'{payload.to_status.value}'."
                    ),
                    "allowed": [s.value for s in sorted(allowed, key=lambda x: x.value)],
                },
            )

        expiry_date = payload.expiry_date
        cert_type = CertType(current["cert_type"])
        if (
            payload.to_status == CertStatus.approved
            and expiry_date is None
            and payload.decision_date is not None
            and cert_type in (CertType.acceptance, CertType.recert)
        ):
            # NĐ 136/2020 — acceptance cert valid 5 years.
            expiry_date = payload.decision_date + timedelta(days=365 * 5)

        assigns = ["status = :status", "updated_at = NOW()"]
        params: dict[str, Any] = {"id": str(cert_id), "status": payload.to_status.value}
        if payload.decision_date is not None:
            assigns.append("decision_date = :decision_date")
            params["decision_date"] = payload.decision_date
        if payload.decision_number is not None:
            assigns.append("decision_number = :decision_number")
            params["decision_number"] = payload.decision_number
        if payload.decision_file_id is not None:
            assigns.append("decision_file_id = :decision_file_id")
            params["decision_file_id"] = str(payload.decision_file_id)
        if expiry_date is not None:
            assigns.append("expiry_date = :expiry_date")
            params["expiry_date"] = expiry_date
        if payload.to_status == CertStatus.submitted:
            assigns.append("submitted_date = COALESCE(submitted_date, CURRENT_DATE)")
        if payload.to_status == CertStatus.rejected and payload.rejection_reason:
            assigns.append(
                "notes = COALESCE(notes || E'\\n', '') || :rejection_reason"
            )
            params["rejection_reason"] = (
                f"[{payload.decision_date or 'no-date'}] Rejected: {payload.rejection_reason}"
            )

        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE fire_certs SET {", ".join(assigns)}
                    WHERE id = :id
                    RETURNING *
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .one()
        )
    return ok(FireCert.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Inspections ----------


@router.post("/certs/{cert_id}/inspections", status_code=status.HTTP_201_CREATED)
async def log_inspection(
    cert_id: UUID,
    payload: InspectionCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Log an inspection round + auto-bump cert status based on result.

    Side effects:
      * round_number = max + 1
      * `pass` → cert flips to `approved` if not already approved.
      * `conditional_pass` → cert flips to `conditional`.
      * `fail` → cert flips to `rfi` (PCCC fail is recoverable through
        an RFI loop, unlike outright `rejected`).
    """
    async with TenantAwareSession(auth.organization_id) as session:
        cert = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, status, cert_type, decision_date
                    FROM fire_certs WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(cert_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if cert is None:
            raise HTTPException(status_code=404, detail="cert_not_found")

        max_round = (
            await session.execute(
                text("SELECT COALESCE(MAX(round_number), 0) FROM fire_inspections WHERE cert_id = :id"),
                {"id": str(cert_id)},
            )
        ).scalar_one()

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO fire_inspections
                      (id, organization_id, cert_id, round_number, inspection_date,
                       inspector_name, inspector_org, overall_result, findings,
                       summary, next_steps, report_file_id)
                    VALUES
                      (:id, :org, :cert_id, :round, :inspection_date,
                       :inspector_name, :inspector_org, :result, CAST(:findings AS jsonb),
                       :summary, :next_steps, :report_file_id)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "cert_id": str(cert_id),
                        "round": int(max_round) + 1,
                        "inspection_date": payload.inspection_date,
                        "inspector_name": payload.inspector_name,
                        "inspector_org": payload.inspector_org,
                        "result": payload.overall_result.value,
                        "findings": _json([f.model_dump(mode="json") for f in payload.findings]),
                        "summary": payload.summary,
                        "next_steps": payload.next_steps,
                        "report_file_id": str(payload.report_file_id)
                        if payload.report_file_id
                        else None,
                    },
                )
            )
            .mappings()
            .one()
        )

        # Cascade the inspection result onto cert status.
        cascade_map = {
            "pass": CertStatus.approved,
            "conditional_pass": CertStatus.conditional,
            "fail": CertStatus.rfi,
        }
        next_status = cascade_map.get(payload.overall_result.value)
        if next_status is not None and CertStatus(cert["status"]) != next_status:
            await session.execute(
                text(
                    """
                UPDATE fire_certs SET status = :status, updated_at = NOW()
                WHERE id = :id
                """
                ),
                {"status": next_status.value, "id": str(cert_id)},
            )

    return ok(FireInspection.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Checklist ----------


@router.post("/certs/{cert_id}/checklist/seed", status_code=status.HTTP_201_CREATED)
async def seed_checklist(
    cert_id: UUID,
    payload: SeedChecklistRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Seed the default QCVN 06:2022 checklist on a cert.

    Idempotent on the (cert_id, clause_ref) pair: re-seeding skips rows
    that already exist so callers can safely retry.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        cert = (
            await session.execute(
                text("SELECT id FROM fire_certs WHERE id = :id AND organization_id = :org"),
                {"id": str(cert_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if cert is None:
            raise HTTPException(status_code=404, detail="cert_not_found")

        existing = (
            (
                await session.execute(
                    text(
                        """
                    SELECT clause_ref FROM fire_checklist_items
                    WHERE cert_id = :id
                    """
                    ),
                    {"id": str(cert_id)},
                )
            )
            .scalars()
            .all()
        )
        existing_set = set(existing)

        seeded = 0
        for idx, item in enumerate(_DEFAULT_CHECKLIST):
            if item["clause_ref"] in existing_set:
                continue
            await session.execute(
                text(
                    """
                INSERT INTO fire_checklist_items
                  (id, organization_id, cert_id, clause_ref, category, description,
                   sort_order)
                VALUES
                  (:id, :org, :cert_id, :clause_ref, :category, :description,
                   :sort_order)
                """
                ),
                {
                    "id": str(uuid4()),
                    "org": str(auth.organization_id),
                    "cert_id": str(cert_id),
                    "clause_ref": item["clause_ref"],
                    "category": item["category"],
                    "description": item["description"],
                    "sort_order": idx,
                },
            )
            seeded += 1

    return ok(
        {
            "cert_id": str(cert_id),
            "template_version": payload.template_version,
            "seeded": seeded,
            "already_present": len(existing_set),
        }
    )


@router.post("/certs/{cert_id}/checklist", status_code=status.HTTP_201_CREATED)
async def add_checklist_item(
    cert_id: UUID,
    payload: ChecklistItemCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        cert = (
            await session.execute(
                text("SELECT id FROM fire_certs WHERE id = :id AND organization_id = :org"),
                {"id": str(cert_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if cert is None:
            raise HTTPException(status_code=404, detail="cert_not_found")

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO fire_checklist_items
                      (id, organization_id, cert_id, clause_ref, category, description,
                       severity, drawing_refs, sort_order)
                    VALUES
                      (:id, :org, :cert_id, :clause_ref, :category, :description,
                       :severity, CAST(:drawing_refs AS text[]), :sort_order)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "cert_id": str(cert_id),
                        "clause_ref": payload.clause_ref,
                        "category": payload.category,
                        "description": payload.description,
                        "severity": payload.severity.value,
                        "drawing_refs": payload.drawing_refs,
                        "sort_order": payload.sort_order,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(ChecklistItem.model_validate(dict(row)).model_dump(mode="json"))


@router.patch("/checklist/{item_id}")
async def update_checklist_item(
    item_id: UUID,
    payload: ChecklistItemUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(item_id), "org": str(auth.organization_id)}
    if payload.status is not None:
        assigns.append("status = :status")
        params["status"] = payload.status.value
        assigns.append("reviewed_at = NOW()")
        assigns.append("reviewer_user_id = :reviewer_user_id")
        params["reviewer_user_id"] = str(auth.user_id)
    if payload.reviewer_note is not None:
        assigns.append("reviewer_note = :reviewer_note")
        params["reviewer_note"] = payload.reviewer_note
    if payload.evidence_file_ids is not None:
        assigns.append("evidence_file_ids = CAST(:evidence AS uuid[])")
        params["evidence"] = [str(f) for f in payload.evidence_file_ids]
    if payload.drawing_refs is not None:
        assigns.append("drawing_refs = CAST(:drawing_refs AS text[])")
        params["drawing_refs"] = payload.drawing_refs
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE fire_checklist_items SET {", ".join(assigns)}
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
        raise HTTPException(status_code=404, detail="checklist_item_not_found")
    return ok(ChecklistItem.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Alerts ----------


@router.get("/alerts")
async def list_alerts(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    expiring_within_days: int = Query(90, ge=1, le=730),
):
    """Three alert kinds:

      * `expiring_soon` — acceptance certs with expiry within window
      * `non_compliances_open` — certs with ≥1 `non_compliant` checklist
      * `inspection_overdue` — certs `submitted` > 45 days with no
        inspection logged
    """
    params: dict[str, Any] = {
        "org": str(auth.organization_id),
        "horizon": date.today() + timedelta(days=expiring_within_days),
        "today": date.today(),
        "stall_cutoff": date.today() - timedelta(days=45),
    }
    project_clause = ""
    if project_id is not None:
        project_clause = " AND c.project_id = :project_id"
        params["project_id"] = str(project_id)

    async with TenantAwareSession(auth.organization_id) as session:
        expiring = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT c.id AS cert_id, c.project_id, c.expiry_date,
                           (c.expiry_date - :today) AS days_until
                    FROM fire_certs c
                    WHERE c.organization_id = :org
                      AND c.status = 'approved'
                      AND c.expiry_date IS NOT NULL
                      AND c.expiry_date <= :horizon
                      AND c.expiry_date >= :today
                      {project_clause}
                    ORDER BY c.expiry_date ASC
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

        non_comp = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT c.id AS cert_id, c.project_id,
                           COUNT(ci.id) AS cnt
                    FROM fire_certs c
                    JOIN fire_checklist_items ci ON ci.cert_id = c.id
                    WHERE c.organization_id = :org
                      AND ci.status = 'non_compliant'
                      {project_clause}
                    GROUP BY c.id, c.project_id
                    ORDER BY cnt DESC
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

        stalled = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT c.id AS cert_id, c.project_id, c.submitted_date,
                           (:today - c.submitted_date) AS days_since
                    FROM fire_certs c
                    LEFT JOIN fire_inspections i ON i.cert_id = c.id
                    WHERE c.organization_id = :org
                      AND c.status = 'submitted'
                      AND c.submitted_date IS NOT NULL
                      AND c.submitted_date <= :stall_cutoff
                      AND i.id IS NULL
                      {project_clause}
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

    alerts: list[CertAlert] = []
    for r in expiring:
        days = int(r["days_until"])
        severity = "critical" if days <= 30 else "warning" if days <= 90 else "info"
        alerts.append(
            CertAlert(
                cert_id=r["cert_id"],
                project_id=r["project_id"],
                code="expiring_soon",
                severity=severity,
                message=f"PCCC cert expires in {days} day(s)",
                expiry_date=r["expiry_date"],
                days_until=days,
            )
        )
    for r in non_comp:
        cnt = int(r["cnt"])
        alerts.append(
            CertAlert(
                cert_id=r["cert_id"],
                project_id=r["project_id"],
                code="non_compliances_open",
                severity="warning" if cnt < 5 else "critical",
                message=f"{cnt} non-compliant checklist item(s) outstanding",
            )
        )
    for r in stalled:
        days = int(r["days_since"])
        alerts.append(
            CertAlert(
                cert_id=r["cert_id"],
                project_id=r["project_id"],
                code="inspection_overdue",
                severity="warning",
                message=f"Submitted {days} day(s) ago, no inspection logged",
                days_until=-days,
            )
        )

    return ok([a.model_dump(mode="json") for a in alerts])


# ---------- Helpers ----------


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=_default_serializer, ensure_ascii=False)


def _default_serializer(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"not serializable: {type(value)}")


def _cert_where(f: CertListFilters, org_id: UUID) -> tuple[str, dict[str, Any]]:
    clauses = ["c.organization_id = :org"]
    params: dict[str, Any] = {"org": str(org_id)}
    if f.project_id:
        clauses.append("c.project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.cert_type:
        clauses.append("c.cert_type = :cert_type")
        params["cert_type"] = f.cert_type.value
    if f.status:
        clauses.append("c.status = :status")
        params["status"] = f.status.value
    if f.expiring_within_days is not None:
        clauses.append("c.expiry_date IS NOT NULL AND c.expiry_date <= :cutoff")
        params["cutoff"] = date.today() + timedelta(days=f.expiring_within_days)
    return " AND ".join(clauses), params


__all__ = ["router"]
