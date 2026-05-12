"""NGHIEMTHU router — statutory acceptance forms (biên bản nghiệm thu).

Endpoints follow the lifecycle of a BBNT:

  draft → in_signoff → accepted | rejected
                       └─→ superseded (when a revision replaces it)

A record cannot finalize until every signatory marked `required` has
made a decision. If any required signatory rejects, the record flips
to `rejected` (NĐ 06/2021 Art. 9: any party's reject is a hard stop).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.nghiemthu import (
    MANDATORY_ROLES,
    AcceptanceDetail,
    AcceptanceEvidence,
    AcceptanceLevel,
    AcceptanceRecord,
    AcceptanceRecordCreate,
    AcceptanceRecordUpdate,
    AcceptanceSignatory,
    AcceptanceStatus,
    EvidenceCreate,
    FinalizeResult,
    RecordListFilters,
    RecordSummary,
    SignatoryCreate,
    SignatoryDecision,
    SignatoryRole,
    SignatorySign,
)

router = APIRouter(prefix="/api/v1/nghiemthu", tags=["nghiemthu"])


# ---------- Records ----------


@router.post("/records", status_code=status.HTTP_201_CREATED)
async def create_record(
    payload: AcceptanceRecordCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Create a BBNT in `draft`.

    Signatories + evidence are added separately so the create flow
    stays fast (the QA team writes the header first, then collects
    signatures over hours/days).
    """
    record_id = uuid4()
    quantities = [q.model_dump(mode="json") for q in payload.quantities]

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO acceptance_records
                      (id, organization_id, project_id, reference_no, acceptance_level,
                       title, status, acceptance_date, location, work_item_codes,
                       quantities, basis, conclusion, created_by, created_at, updated_at)
                    VALUES
                      (:id, :org, :project_id, :reference_no, :level,
                       :title, 'draft', :acceptance_date, :location,
                       CAST(:work_codes AS text[]), CAST(:quantities AS jsonb),
                       CAST(:basis AS jsonb), :conclusion, :created_by, NOW(), NOW())
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(record_id),
                        "org": str(auth.organization_id),
                        "project_id": str(payload.project_id),
                        "reference_no": payload.reference_no,
                        "level": payload.acceptance_level.value,
                        "title": payload.title,
                        "acceptance_date": payload.acceptance_date,
                        "location": payload.location,
                        "work_codes": payload.work_item_codes,
                        "quantities": _json(quantities),
                        "basis": _json(payload.basis),
                        "conclusion": payload.conclusion,
                        "created_by": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(AcceptanceRecord.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/records")
async def list_records(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    acceptance_level: AcceptanceLevel | None = Query(None, alias="level"),
    record_status: AcceptanceStatus | None = Query(None, alias="status"),
    work_item_code: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = RecordListFilters(
        project_id=project_id,
        acceptance_level=acceptance_level,
        status=record_status,
        work_item_code=work_item_code,
        limit=limit,
        offset=offset,
    )
    where, params = _record_where(filters, auth.organization_id)
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT
                      r.*,
                      COALESCE(sig.total, 0)::int AS signatories_total,
                      COALESCE(sig.signed, 0)::int AS signatories_signed,
                      COALESCE(sig.mandatory_pending, 0)::int AS mandatory_pending
                    FROM acceptance_records r
                    LEFT JOIN (
                      SELECT record_id,
                             COUNT(*) AS total,
                             COUNT(*) FILTER (WHERE decision <> 'pending') AS signed,
                             COUNT(*) FILTER (
                               WHERE required AND decision = 'pending'
                             ) AS mandatory_pending
                      FROM acceptance_signatories
                      GROUP BY record_id
                    ) sig ON sig.record_id = r.id
                    WHERE {where}
                    ORDER BY r.acceptance_date DESC, r.created_at DESC
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
            await session.execute(text(f"SELECT COUNT(*) FROM acceptance_records r WHERE {where}"), params)
        ).scalar_one()

    items = [RecordSummary.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.get("/records/{record_id}")
async def get_record(
    record_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        record = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM acceptance_records
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(record_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if record is None:
            raise HTTPException(status_code=404, detail="record_not_found")

        signatories = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM acceptance_signatories
                    WHERE record_id = :id
                    ORDER BY sort_order ASC, created_at ASC
                    """
                    ),
                    {"id": str(record_id)},
                )
            )
            .mappings()
            .all()
        )
        evidence = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM acceptance_evidence
                    WHERE record_id = :id
                    ORDER BY sort_order ASC, created_at ASC
                    """
                    ),
                    {"id": str(record_id)},
                )
            )
            .mappings()
            .all()
        )

    detail = AcceptanceDetail.model_validate(
        {
            **dict(record),
            "signatories": [AcceptanceSignatory.model_validate(dict(s)) for s in signatories],
            "evidence": [AcceptanceEvidence.model_validate(dict(e)) for e in evidence],
        }
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/records/{record_id}")
async def update_record(
    record_id: UUID,
    payload: AcceptanceRecordUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Edit a draft BBNT. After a signatory signs, the header is
    locked — return 409 if any non-pending decision exists.
    """
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(record_id), "org": str(auth.organization_id)}
    if payload.title is not None:
        assigns.append("title = :title")
        params["title"] = payload.title
    if payload.acceptance_date is not None:
        assigns.append("acceptance_date = :acceptance_date")
        params["acceptance_date"] = payload.acceptance_date
    if payload.location is not None:
        assigns.append("location = :location")
        params["location"] = payload.location
    if payload.work_item_codes is not None:
        assigns.append("work_item_codes = CAST(:work_codes AS text[])")
        params["work_codes"] = payload.work_item_codes
    if payload.quantities is not None:
        assigns.append("quantities = CAST(:quantities AS jsonb)")
        params["quantities"] = _json([q.model_dump(mode="json") for q in payload.quantities])
    if payload.basis is not None:
        assigns.append("basis = CAST(:basis AS jsonb)")
        params["basis"] = _json(payload.basis)
    if payload.conclusion is not None:
        assigns.append("conclusion = :conclusion")
        params["conclusion"] = payload.conclusion
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        locked = (
            await session.execute(
                text(
                    """
                SELECT COUNT(*) FROM acceptance_signatories
                WHERE record_id = :id AND decision <> 'pending'
                """
                ),
                {"id": str(record_id)},
            )
        ).scalar_one()
        if int(locked) > 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "record_locked_by_signature",
                    "message": (
                        "BBNT đã có chữ ký — không thể chỉnh sửa nội dung. "
                        "Tạo bản sửa đổi mới và đánh dấu superseded."
                    ),
                },
            )

        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE acceptance_records SET {", ".join(assigns)}
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
        raise HTTPException(status_code=404, detail="record_not_found")
    return ok(AcceptanceRecord.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Signatories ----------


@router.post("/records/{record_id}/signatories", status_code=status.HTTP_201_CREATED)
async def add_signatory(
    record_id: UUID,
    payload: SignatoryCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Add a party to a BBNT. Required parties stay required even if
    they sign with `comment_only` (the finalize step demands `approve`
    from every required role)."""
    async with TenantAwareSession(auth.organization_id) as session:
        record = (
            await session.execute(
                text(
                    """
                SELECT id FROM acceptance_records
                WHERE id = :id AND organization_id = :org
                """
                ),
                {"id": str(record_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="record_not_found")

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO acceptance_signatories
                      (id, organization_id, record_id, role, org_name, representative_name,
                       position, required, sort_order)
                    VALUES
                      (:id, :org, :record_id, :role, :org_name, :representative_name,
                       :position, :required, :sort_order)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "record_id": str(record_id),
                        "role": payload.role.value,
                        "org_name": payload.org_name,
                        "representative_name": payload.representative_name,
                        "position": payload.position,
                        "required": payload.required,
                        "sort_order": payload.sort_order,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(AcceptanceSignatory.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/signatories/{signatory_id}/sign")
async def sign_signatory(
    signatory_id: UUID,
    payload: SignatorySign,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Record a signing decision.

    Side effect: if the record is `draft`, flip it to `in_signoff` on
    the first non-pending decision. A `reject` from a required role
    flips the record to `rejected` immediately — no point pretending
    the BBNT is alive when the contractor has refused.
    """
    signed_at = payload.signed_at or datetime.now(UTC)

    async with TenantAwareSession(auth.organization_id) as session:
        existing = (
            (
                await session.execute(
                    text(
                        """
                    SELECT s.*, r.status AS record_status
                    FROM acceptance_signatories s
                    JOIN acceptance_records r ON r.id = s.record_id
                    WHERE s.id = :id AND s.organization_id = :org
                    """
                    ),
                    {"id": str(signatory_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="signatory_not_found")

        if existing["record_status"] in ("accepted", "rejected", "superseded"):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "record_already_final",
                    "message": (
                        "BBNT đã ở trạng thái cuối cùng — không nhận thêm chữ ký."
                    ),
                },
            )

        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE acceptance_signatories
                    SET decision = :decision,
                        comment = :comment,
                        signed_at = :signed_at,
                        signature_file_id = :signature_file_id,
                        signed_by_user_id = :user_id
                    WHERE id = :id
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(signatory_id),
                        "decision": payload.decision.value,
                        "comment": payload.comment,
                        "signed_at": signed_at,
                        "signature_file_id": str(payload.signature_file_id)
                        if payload.signature_file_id
                        else None,
                        "user_id": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )

        # Side-effect 1: lift the record into in_signoff once anyone signs.
        if existing["record_status"] == "draft":
            await session.execute(
                text(
                    """
                UPDATE acceptance_records SET status = 'in_signoff', updated_at = NOW()
                WHERE id = :id
                """
                ),
                {"id": str(existing["record_id"])},
            )

        # Side-effect 2: a required reject is a hard stop.
        if payload.decision == SignatoryDecision.reject and existing["required"]:
            await session.execute(
                text(
                    """
                UPDATE acceptance_records SET status = 'rejected', updated_at = NOW()
                WHERE id = :id
                """
                ),
                {"id": str(existing["record_id"])},
            )

    return ok(AcceptanceSignatory.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Evidence ----------


@router.post("/records/{record_id}/evidence", status_code=status.HTTP_201_CREATED)
async def add_evidence(
    record_id: UUID,
    payload: EvidenceCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    if payload.file_id is None and payload.external_ref is None:
        raise HTTPException(
            status_code=400,
            detail="evidence_requires_file_id_or_external_ref",
        )

    async with TenantAwareSession(auth.organization_id) as session:
        record = (
            await session.execute(
                text("SELECT id FROM acceptance_records WHERE id = :id AND organization_id = :org"),
                {"id": str(record_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="record_not_found")

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO acceptance_evidence
                      (id, organization_id, record_id, kind, file_id, external_ref,
                       caption, captured_at, sort_order)
                    VALUES
                      (:id, :org, :record_id, :kind, :file_id, :external_ref,
                       :caption, :captured_at, :sort_order)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "record_id": str(record_id),
                        "kind": payload.kind.value,
                        "file_id": str(payload.file_id) if payload.file_id else None,
                        "external_ref": payload.external_ref,
                        "caption": payload.caption,
                        "captured_at": payload.captured_at,
                        "sort_order": payload.sort_order,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(AcceptanceEvidence.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Finalize ----------


@router.post("/records/{record_id}/finalize")
async def finalize_record(
    record_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Move a BBNT to `accepted` once all required parties have approved.

    Returns 200 with a `FinalizeResult` describing the new status and,
    when not yet finalizable, which mandatory roles are still pending
    or who has rejected. Idempotent — calling finalize on an already-
    accepted record returns the same payload.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        record = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, status FROM acceptance_records
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(record_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if record is None:
            raise HTTPException(status_code=404, detail="record_not_found")

        if record["status"] in ("accepted", "rejected", "superseded"):
            return ok(
                FinalizeResult(
                    record_id=record_id,
                    status=AcceptanceStatus(record["status"]),
                    message=f"Record already in terminal state '{record['status']}'.",
                ).model_dump(mode="json")
            )

        signatories = (
            (
                await session.execute(
                    text(
                        """
                    SELECT role, decision, required FROM acceptance_signatories
                    WHERE record_id = :id
                    """
                    ),
                    {"id": str(record_id)},
                )
            )
            .mappings()
            .all()
        )

        # Gather missing mandatory roles. Two flavours:
        #   (a) a mandatory role isn't attached to the record at all
        #   (b) it's attached but its decision is still pending
        attached_roles = {SignatoryRole(s["role"]) for s in signatories if s["required"]}
        missing_roles = sorted(MANDATORY_ROLES - attached_roles, key=lambda r: r.value)
        pending_roles = sorted(
            {SignatoryRole(s["role"]) for s in signatories if s["required"] and s["decision"] == "pending"},
            key=lambda r: r.value,
        )
        rejected_roles = sorted(
            {SignatoryRole(s["role"]) for s in signatories if s["required"] and s["decision"] == "reject"},
            key=lambda r: r.value,
        )

        if rejected_roles:
            # Persist the terminal state so subsequent calls short-circuit.
            await session.execute(
                text(
                    """
                UPDATE acceptance_records SET status = 'rejected', updated_at = NOW()
                WHERE id = :id
                """
                ),
                {"id": str(record_id)},
            )
            return ok(
                FinalizeResult(
                    record_id=record_id,
                    status=AcceptanceStatus.rejected,
                    rejected_by_roles=rejected_roles,
                    message=(
                        "Có bên bắt buộc đã từ chối — BBNT bị reject. "
                        "Cần tạo bản sửa đổi để xử lý các tồn đọng."
                    ),
                ).model_dump(mode="json")
            )

        if missing_roles or pending_roles:
            return ok(
                FinalizeResult(
                    record_id=record_id,
                    status=AcceptanceStatus(record["status"]),
                    mandatory_pending_roles=sorted(
                        set(missing_roles) | set(pending_roles), key=lambda r: r.value
                    ),
                    message="Còn bên bắt buộc chưa ký — chưa thể finalize.",
                ).model_dump(mode="json")
            )

        # All required parties signed `approve` (or `comment_only`).
        # Move to `accepted`.
        await session.execute(
            text(
                """
            UPDATE acceptance_records
            SET status = 'accepted',
                finalized_at = NOW(),
                updated_at = NOW()
            WHERE id = :id
            """
            ),
            {"id": str(record_id)},
        )

    return ok(
        FinalizeResult(
            record_id=record_id,
            status=AcceptanceStatus.accepted,
            message="BBNT đã được ký đầy đủ và chuyển sang trạng thái accepted.",
        ).model_dump(mode="json")
    )


# ---------- Supersede ----------


@router.post("/records/{record_id}/supersede")
async def supersede_record(
    record_id: UUID,
    replacement_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Mark a record as superseded by a later revision.

    Useful when a discrepancy is found after sign-off: the original is
    preserved (audit trail) and a fresh BBNT is opened. The replacement
    must already exist; we validate it lives under the same project.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, project_id, status
                    FROM acceptance_records
                    WHERE id = ANY(CAST(:ids AS uuid[])) AND organization_id = :org
                    """
                    ),
                    {
                        "ids": [str(record_id), str(replacement_id)],
                        "org": str(auth.organization_id),
                    },
                )
            )
            .mappings()
            .all()
        )
        by_id = {r["id"]: r for r in rows}
        if record_id not in by_id:
            raise HTTPException(status_code=404, detail="record_not_found")
        if replacement_id not in by_id:
            raise HTTPException(status_code=404, detail="replacement_not_found")
        if by_id[record_id]["project_id"] != by_id[replacement_id]["project_id"]:
            raise HTTPException(
                status_code=422,
                detail="replacement_must_be_same_project",
            )

        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE acceptance_records
                    SET status = 'superseded',
                        superseded_by_id = :replacement_id,
                        updated_at = NOW()
                    WHERE id = :id
                    RETURNING *
                    """
                    ),
                    {"id": str(record_id), "replacement_id": str(replacement_id)},
                )
            )
            .mappings()
            .one()
        )
    return ok(AcceptanceRecord.model_validate(dict(row)).model_dump(mode="json"))


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


def _record_where(f: RecordListFilters, org_id: UUID) -> tuple[str, dict[str, Any]]:
    clauses = ["r.organization_id = :org"]
    params: dict[str, Any] = {"org": str(org_id)}
    if f.project_id:
        clauses.append("r.project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.acceptance_level:
        clauses.append("r.acceptance_level = :level")
        params["level"] = f.acceptance_level.value
    if f.status:
        clauses.append("r.status = :status")
        params["status"] = f.status.value
    if f.work_item_code:
        clauses.append(":work_code = ANY(r.work_item_codes)")
        params["work_code"] = f.work_item_code
    return " AND ".join(clauses), params


__all__ = ["router"]
