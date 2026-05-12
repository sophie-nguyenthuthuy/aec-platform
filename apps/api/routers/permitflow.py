"""PERMITFLOW router — Vietnamese construction permit chain endpoints.

The router owns four resources:

  * **Dossiers** — one per project block; created with the 5 canonical
    stages auto-seeded.
  * **Stages** — sequential gates: chủ trương đầu tư → quy hoạch 1/500
    → thẩm định TKCS → GPXD → nghiệm thu PCCC. Status transitions are
    validated against a matrix.
  * **Submissions** — every round-trip with the issuing authority,
    including RFI responses.
  * **Alerts** — computed view over stages with `expiry_date` or
    overdue `target_submit_date`. Not persisted.
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
from schemas.permitflow import (
    STAGE_ORDER,
    Authority,
    DossierDetail,
    DossierListFilters,
    DossierStatus,
    DossierSummary,
    DossierTimeline,
    PermitAlert,
    PermitDossier,
    PermitDossierCreate,
    PermitDossierUpdate,
    PermitStage,
    PermitSubmission,
    ProjectClassification,
    StageCode,
    StageStatus,
    StageTransition,
    StageUpdate,
    StageWithSubmissions,
    SubmissionCreate,
    SubmissionOutcome,
    SubmissionType,
    SubmissionUpdate,
    TimelineEvent,
    default_authority,
    default_legal_basis,
)

router = APIRouter(prefix="/api/v1/permitflow", tags=["permitflow"])


# ---------- Stage transition matrix ----------
#
# Each stage status maps to the set of statuses it can transition to.
# Captures the "no skip" rule + reasonable round-trip patterns:
#   not_started → preparing → submitted → in_review → rfi ⇄ submitted
#                                                  ↘  approved | rejected
# Withdrawal is permitted from any active state until a decision is final.

_TRANSITIONS: dict[StageStatus, set[StageStatus]] = {
    StageStatus.not_started: {StageStatus.preparing, StageStatus.submitted},
    StageStatus.preparing: {StageStatus.submitted, StageStatus.withdrawn},
    StageStatus.submitted: {StageStatus.in_review, StageStatus.rfi, StageStatus.withdrawn},
    StageStatus.in_review: {
        StageStatus.rfi,
        StageStatus.approved,
        StageStatus.rejected,
        StageStatus.withdrawn,
    },
    StageStatus.rfi: {StageStatus.submitted, StageStatus.withdrawn},
    # Terminal states — `expired` is set by the alerts cron, not a user
    # action, so it doesn't appear as a target here.
    StageStatus.approved: set(),
    StageStatus.rejected: {StageStatus.preparing},
    StageStatus.withdrawn: {StageStatus.preparing},
    StageStatus.expired: {StageStatus.preparing},
}


# ---------- Dossiers ----------


@router.post("/dossiers", status_code=status.HTTP_201_CREATED)
async def create_dossier(
    payload: PermitDossierCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Create a dossier and seed the 5 canonical stages.

    The stages are inserted in canonical order with `sequence = 1..5`,
    authority derived from (stage, classification, investment_type), and
    legal_basis pre-populated. The first stage (`chu_truong_dau_tu`) is
    advanced to `preparing` so the user has somewhere to act; the rest
    stay `not_started` and unlock as predecessors are approved.
    """
    dossier_id = uuid4()
    now = datetime.now(UTC)

    async with TenantAwareSession(auth.organization_id) as session:
        dossier_row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO permit_dossiers
                      (id, organization_id, project_id, name, classification,
                       investment_type, status, location, land_cert_file_id,
                       land_parcel_no, notes, created_by, created_at, updated_at)
                    VALUES
                      (:id, :org, :project_id, :name, :classification,
                       :investment_type, 'planning', CAST(:location AS jsonb),
                       :land_cert_file_id, :land_parcel_no, :notes,
                       :created_by, :now, :now)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(dossier_id),
                        "org": str(auth.organization_id),
                        "project_id": str(payload.project_id),
                        "name": payload.name,
                        "classification": payload.classification.value,
                        "investment_type": payload.investment_type.value,
                        "location": _json(payload.location),
                        "land_cert_file_id": str(payload.land_cert_file_id)
                        if payload.land_cert_file_id
                        else None,
                        "land_parcel_no": payload.land_parcel_no,
                        "notes": payload.notes,
                        "created_by": str(auth.user_id),
                        "now": now,
                    },
                )
            )
            .mappings()
            .one()
        )

        # Seed the 5 stages in a single multi-row INSERT to keep the
        # round-trip count down — there's no per-row branching needed.
        stage_rows: list[dict[str, Any]] = []
        for idx, stage_code in enumerate(STAGE_ORDER, start=1):
            authority = default_authority(stage_code, payload.classification, payload.investment_type)
            stage_status = StageStatus.preparing if idx == 1 else StageStatus.not_started
            stage_rows.append(
                {
                    "id": str(uuid4()),
                    "org": str(auth.organization_id),
                    "dossier_id": str(dossier_id),
                    "stage_code": stage_code.value,
                    "sequence": idx,
                    "authority": authority.value,
                    "status": stage_status.value,
                    "legal_basis": default_legal_basis(stage_code),
                }
            )

        await session.execute(
            text(
                """
            INSERT INTO permit_stages
              (id, organization_id, dossier_id, stage_code, sequence,
               authority, status, legal_basis, created_at, updated_at)
            SELECT
              (s->>'id')::uuid,
              (s->>'org')::uuid,
              (s->>'dossier_id')::uuid,
              s->>'stage_code',
              (s->>'sequence')::int,
              s->>'authority',
              s->>'status',
              ARRAY(SELECT jsonb_array_elements_text(s->'legal_basis')),
              NOW(), NOW()
            FROM jsonb_array_elements(CAST(:rows AS jsonb)) AS s
            """
            ),
            {"rows": _json(stage_rows)},
        )

    return ok(PermitDossier.model_validate(dict(dossier_row)).model_dump(mode="json"))


@router.get("/dossiers")
async def list_dossiers(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    dossier_status: DossierStatus | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = DossierListFilters(project_id=project_id, status=dossier_status, limit=limit, offset=offset)
    where, params = _dossier_where(filters, auth.organization_id)

    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT
                      d.*,
                      COALESCE(s.total, 0)::int AS stages_total,
                      COALESCE(s.approved, 0)::int AS stages_approved,
                      ns.stage_code AS next_stage_code,
                      ns.status AS next_stage_status,
                      ex.nearest_expiry
                    FROM permit_dossiers d
                    LEFT JOIN (
                      SELECT dossier_id,
                             COUNT(*) AS total,
                             COUNT(*) FILTER (WHERE status = 'approved') AS approved
                      FROM permit_stages
                      GROUP BY dossier_id
                    ) s ON s.dossier_id = d.id
                    LEFT JOIN LATERAL (
                      SELECT stage_code, status
                      FROM permit_stages
                      WHERE dossier_id = d.id
                        AND status NOT IN ('approved', 'withdrawn', 'expired')
                      ORDER BY sequence ASC
                      LIMIT 1
                    ) ns ON true
                    LEFT JOIN LATERAL (
                      SELECT MIN(expiry_date) AS nearest_expiry
                      FROM permit_stages
                      WHERE dossier_id = d.id
                        AND status = 'approved'
                        AND expiry_date IS NOT NULL
                        AND expiry_date >= CURRENT_DATE
                    ) ex ON true
                    WHERE {where}
                    ORDER BY d.created_at DESC
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
            await session.execute(text(f"SELECT COUNT(*) FROM permit_dossiers d WHERE {where}"), params)
        ).scalar_one()

    items = [DossierSummary.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.get("/dossiers/{dossier_id}")
async def get_dossier(
    dossier_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Return the dossier + nested stages + nested submissions.

    One query per table — three round-trips total, which is fine for
    the largest legit shape (1 dossier × 5 stages × ~5 submissions
    each = ~25 submission rows).
    """
    async with TenantAwareSession(auth.organization_id) as session:
        dossier = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM permit_dossiers
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(dossier_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if dossier is None:
            raise HTTPException(status_code=404, detail="dossier_not_found")

        stage_rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM permit_stages
                    WHERE dossier_id = :id
                    ORDER BY sequence ASC
                    """
                    ),
                    {"id": str(dossier_id)},
                )
            )
            .mappings()
            .all()
        )
        sub_rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT s.* FROM permit_submissions s
                    JOIN permit_stages st ON st.id = s.stage_id
                    WHERE st.dossier_id = :id
                    ORDER BY s.stage_id, s.round_number ASC
                    """
                    ),
                    {"id": str(dossier_id)},
                )
            )
            .mappings()
            .all()
        )

    subs_by_stage: dict[UUID, list[PermitSubmission]] = {}
    for s in sub_rows:
        subs_by_stage.setdefault(s["stage_id"], []).append(PermitSubmission.model_validate(dict(s)))

    stages = [
        StageWithSubmissions.model_validate(
            {**dict(s), "submissions": subs_by_stage.get(s["id"], [])}
        )
        for s in stage_rows
    ]
    detail = DossierDetail.model_validate({**dict(dossier), "stages": stages})
    return ok(detail.model_dump(mode="json"))


@router.patch("/dossiers/{dossier_id}")
async def update_dossier(
    dossier_id: UUID,
    payload: PermitDossierUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(dossier_id), "org": str(auth.organization_id)}
    if payload.name is not None:
        assigns.append("name = :name")
        params["name"] = payload.name
    if payload.classification is not None:
        assigns.append("classification = :classification")
        params["classification"] = payload.classification.value
    if payload.investment_type is not None:
        assigns.append("investment_type = :investment_type")
        params["investment_type"] = payload.investment_type.value
    if payload.status is not None:
        assigns.append("status = :status")
        params["status"] = payload.status.value
    if payload.location is not None:
        assigns.append("location = CAST(:location AS jsonb)")
        params["location"] = _json(payload.location)
    if payload.land_cert_file_id is not None:
        assigns.append("land_cert_file_id = :land_cert_file_id")
        params["land_cert_file_id"] = str(payload.land_cert_file_id)
    if payload.land_parcel_no is not None:
        assigns.append("land_parcel_no = :land_parcel_no")
        params["land_parcel_no"] = payload.land_parcel_no
    if payload.notes is not None:
        assigns.append("notes = :notes")
        params["notes"] = payload.notes
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE permit_dossiers SET {", ".join(assigns)}
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
        raise HTTPException(status_code=404, detail="dossier_not_found")
    return ok(PermitDossier.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Stages ----------


@router.get("/dossiers/{dossier_id}/stages")
async def list_stages(
    dossier_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT s.* FROM permit_stages s
                    JOIN permit_dossiers d ON d.id = s.dossier_id
                    WHERE s.dossier_id = :id AND d.organization_id = :org
                    ORDER BY s.sequence ASC
                    """
                    ),
                    {"id": str(dossier_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .all()
        )
    items = [PermitStage.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return ok(items)


@router.patch("/stages/{stage_id}")
async def update_stage(
    stage_id: UUID,
    payload: StageUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Edit stage metadata (authority delegation, target dates, decision
    file). Status changes flow through `/stages/{id}/transition` so the
    transition matrix is enforced in one place."""
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(stage_id), "org": str(auth.organization_id)}
    if payload.authority is not None:
        assigns.append("authority = :authority")
        params["authority"] = payload.authority.value
    if payload.target_submit_date is not None:
        assigns.append("target_submit_date = :target_submit_date")
        params["target_submit_date"] = payload.target_submit_date
    if payload.submitted_date is not None:
        assigns.append("submitted_date = :submitted_date")
        params["submitted_date"] = payload.submitted_date
    if payload.decision_date is not None:
        assigns.append("decision_date = :decision_date")
        params["decision_date"] = payload.decision_date
    if payload.decision_number is not None:
        assigns.append("decision_number = :decision_number")
        params["decision_number"] = payload.decision_number
    if payload.decision_file_id is not None:
        assigns.append("decision_file_id = :decision_file_id")
        params["decision_file_id"] = str(payload.decision_file_id)
    if payload.expiry_date is not None:
        assigns.append("expiry_date = :expiry_date")
        params["expiry_date"] = payload.expiry_date
    if payload.legal_basis is not None:
        assigns.append("legal_basis = CAST(:legal_basis AS text[])")
        params["legal_basis"] = payload.legal_basis
    if payload.notes is not None:
        assigns.append("notes = :notes")
        params["notes"] = payload.notes
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE permit_stages SET {", ".join(assigns)}
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
        raise HTTPException(status_code=404, detail="stage_not_found")
    return ok(PermitStage.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/stages/{stage_id}/transition")
async def transition_stage(
    stage_id: UUID,
    payload: StageTransition,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Change stage status against the transition matrix.

    Side effects on `approved`:
      * Decision number / date / file persisted on the same UPDATE.
      * If this stage has a known statutory expiry (GPXD = 12mo from
        decision date; nghiệm thu PCCC = 5 years), default `expiry_date`
        when caller didn't pass one.
      * Unlock the next stage by flipping its status from `not_started`
        to `preparing` (no-op if already further along — e.g. user
        manually advanced).
    """
    async with TenantAwareSession(auth.organization_id) as session:
        current = (
            (
                await session.execute(
                    text(
                        """
                    SELECT s.*, d.id AS dossier_id_check
                    FROM permit_stages s
                    JOIN permit_dossiers d ON d.id = s.dossier_id
                    WHERE s.id = :id AND d.organization_id = :org
                    """
                    ),
                    {"id": str(stage_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if current is None:
            raise HTTPException(status_code=404, detail="stage_not_found")

        cur_status = StageStatus(current["status"])
        allowed = _TRANSITIONS.get(cur_status, set())
        if payload.to_status not in allowed:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_transition",
                    "message": (
                        f"Cannot transition stage from '{cur_status.value}' "
                        f"to '{payload.to_status.value}'."
                    ),
                    "allowed": [s.value for s in sorted(allowed, key=lambda x: x.value)],
                },
            )

        # Compute default statutory expiry when approving and caller
        # didn't supply one. GPXD lapses 12 months after issuance unless
        # construction has started; PCCC fire-safety cert valid 5 years.
        expiry_date = payload.expiry_date
        if (
            payload.to_status == StageStatus.approved
            and expiry_date is None
            and payload.decision_date is not None
        ):
            stage_code = StageCode(current["stage_code"])
            if stage_code == StageCode.gpxd:
                expiry_date = payload.decision_date + timedelta(days=365)
            elif stage_code == StageCode.nghiem_thu_pccc:
                expiry_date = payload.decision_date + timedelta(days=365 * 5)

        assigns = ["status = :status", "updated_at = NOW()"]
        params: dict[str, Any] = {"id": str(stage_id), "status": payload.to_status.value}
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
        if payload.to_status == StageStatus.rejected and payload.rejection_reason:
            # Append rejection reason to existing notes rather than
            # overwriting — useful when stage churns through multiple
            # rejections during back-and-forth with the authority.
            assigns.append(
                "notes = COALESCE(notes || E'\\n', '') || :rejection_reason"
            )
            params["rejection_reason"] = (
                f"[{payload.decision_date or 'no-date'}] Rejected: {payload.rejection_reason}"
            )
        if payload.to_status == StageStatus.submitted:
            assigns.append("submitted_date = COALESCE(submitted_date, CURRENT_DATE)")

        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE permit_stages SET {", ".join(assigns)}
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

        # Unlock the next stage when this one approves. Only flips
        # `not_started` → `preparing`; leaves later states alone so
        # we don't accidentally rewind a manually-advanced stage.
        if payload.to_status == StageStatus.approved:
            await session.execute(
                text(
                    """
                UPDATE permit_stages SET status = 'preparing', updated_at = NOW()
                WHERE dossier_id = :dossier_id
                  AND sequence = :next_seq
                  AND status = 'not_started'
                """
                ),
                {
                    "dossier_id": str(current["dossier_id"]),
                    "next_seq": current["sequence"] + 1,
                },
            )

    return ok(PermitStage.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Submissions ----------


@router.post("/stages/{stage_id}/submissions", status_code=status.HTTP_201_CREATED)
async def log_submission(
    stage_id: UUID,
    payload: SubmissionCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Log a round-trip with the issuing authority.

    Side effects:
      * Bumps the stage to `submitted` (if currently `preparing` or
        `rfi`) — captures the common "submit → review" flow without
        forcing the caller to also POST to `/transition`.
      * `round_number` is auto-incremented from existing submissions.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        stage = (
            (
                await session.execute(
                    text(
                        """
                    SELECT s.* FROM permit_stages s
                    WHERE s.id = :id AND s.organization_id = :org
                    """
                    ),
                    {"id": str(stage_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if stage is None:
            raise HTTPException(status_code=404, detail="stage_not_found")

        # Compute round_number: max existing + 1, starting at 1.
        max_round = (
            await session.execute(
                text("SELECT COALESCE(MAX(round_number), 0) FROM permit_submissions WHERE stage_id = :id"),
                {"id": str(stage_id)},
            )
        ).scalar_one()

        sub_id = uuid4()
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO permit_submissions
                      (id, organization_id, stage_id, round_number, submission_type,
                       submitted_at, submitted_by, receipt_number, package_file_ids,
                       outcome, outcome_status)
                    VALUES
                      (:id, :org, :stage_id, :round, :stype,
                       :submitted_at, :submitted_by, :receipt, CAST(:files AS uuid[]),
                       :outcome, 'pending')
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(sub_id),
                        "org": str(auth.organization_id),
                        "stage_id": str(stage_id),
                        "round": int(max_round) + 1,
                        "stype": payload.submission_type.value,
                        "submitted_at": payload.submitted_at,
                        "submitted_by": str(auth.user_id),
                        "receipt": payload.receipt_number,
                        "files": [str(f) for f in payload.package_file_ids],
                        "outcome": payload.outcome,
                    },
                )
            )
            .mappings()
            .one()
        )

        cur_status = StageStatus(stage["status"])
        if cur_status in (StageStatus.preparing, StageStatus.rfi):
            await session.execute(
                text(
                    """
                UPDATE permit_stages SET
                  status = 'submitted',
                  submitted_date = COALESCE(submitted_date, CURRENT_DATE),
                  updated_at = NOW()
                WHERE id = :id
                """
                ),
                {"id": str(stage_id)},
            )

    return ok(PermitSubmission.model_validate(dict(row)).model_dump(mode="json"))


@router.patch("/submissions/{submission_id}")
async def update_submission(
    submission_id: UUID,
    payload: SubmissionUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Record the outcome of a submission round (accepted / RFI / rejected).

    Driven separately from stage transitions because a single stage can
    accumulate multiple RFI rounds before final approval — each outcome
    needs its own audit row.
    """
    assigns: list[str] = []
    params: dict[str, Any] = {"id": str(submission_id), "org": str(auth.organization_id)}
    if payload.outcome is not None:
        assigns.append("outcome = :outcome")
        params["outcome"] = payload.outcome
    if payload.outcome_status is not None:
        assigns.append("outcome_status = :outcome_status")
        params["outcome_status"] = payload.outcome_status.value
        if payload.outcome_at is None:
            assigns.append("outcome_at = NOW()")
    if payload.outcome_at is not None:
        assigns.append("outcome_at = :outcome_at")
        params["outcome_at"] = payload.outcome_at
    if not assigns:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE permit_submissions SET {", ".join(assigns)}
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
            raise HTTPException(status_code=404, detail="submission_not_found")

        # Auto-flip the parent stage when the authority issues an RFI —
        # saves the caller from having to fire a separate transition.
        if payload.outcome_status == SubmissionOutcome.rfi_issued:
            await session.execute(
                text(
                    """
                UPDATE permit_stages SET status = 'rfi', updated_at = NOW()
                WHERE id = :stage_id
                  AND status IN ('submitted', 'in_review')
                """
                ),
                {"stage_id": str(row["stage_id"])},
            )

    return ok(PermitSubmission.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Timeline + alerts ----------


@router.get("/dossiers/{dossier_id}/timeline")
async def get_timeline(
    dossier_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Flatten submissions + stage decisions into a chronological feed."""
    async with TenantAwareSession(auth.organization_id) as session:
        own = (
            await session.execute(
                text(
                    """
                SELECT 1 FROM permit_dossiers
                WHERE id = :id AND organization_id = :org
                """
                ),
                {"id": str(dossier_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if own is None:
            raise HTTPException(status_code=404, detail="dossier_not_found")

        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT submitted_at AS occurred_at,
                           st.stage_code AS stage_code,
                           'submission' AS kind,
                           CONCAT('Submission round ', round_number, ' (', submission_type, ')')
                             AS description,
                           submitted_by AS actor_user_id
                    FROM permit_submissions s
                    JOIN permit_stages st ON st.id = s.stage_id
                    WHERE st.dossier_id = :id
                    UNION ALL
                    SELECT outcome_at AS occurred_at,
                           st.stage_code AS stage_code,
                           'outcome' AS kind,
                           CONCAT('Outcome: ', outcome_status,
                                  CASE WHEN outcome IS NOT NULL THEN ' — ' || outcome ELSE '' END)
                             AS description,
                           NULL AS actor_user_id
                    FROM permit_submissions s
                    JOIN permit_stages st ON st.id = s.stage_id
                    WHERE st.dossier_id = :id AND outcome_at IS NOT NULL
                    UNION ALL
                    SELECT decision_date::timestamptz AS occurred_at,
                           stage_code,
                           'transition' AS kind,
                           CONCAT('Approved (', COALESCE(decision_number, 'no decision number'), ')')
                             AS description,
                           NULL AS actor_user_id
                    FROM permit_stages
                    WHERE dossier_id = :id AND status = 'approved' AND decision_date IS NOT NULL
                    ORDER BY occurred_at ASC NULLS LAST
                    """
                    ),
                    {"id": str(dossier_id)},
                )
            )
            .mappings()
            .all()
        )

    events = [TimelineEvent.model_validate(dict(r)) for r in rows if r["occurred_at"] is not None]
    return ok(DossierTimeline(dossier_id=dossier_id, events=events).model_dump(mode="json"))


@router.get("/alerts")
async def list_alerts(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    expiring_within_days: int = Query(60, ge=1, le=365),
):
    """Computed alert list — not persisted.

    Three alert kinds:
      * `expiring_soon` — approved stage whose `expiry_date` falls within
        the given window. Severity ramps: ≤7d critical, ≤30d warning,
        else info.
      * `overdue_submission` — preparing / not_started stage past its
        `target_submit_date`.
      * `stalled_review` — submitted / in_review > 60 days with no
        outcome row. Helps surface stuck dossiers before they age out.
    """
    params: dict[str, Any] = {
        "org": str(auth.organization_id),
        "horizon": date.today() + timedelta(days=expiring_within_days),
        "today": date.today(),
        "stall_cutoff": date.today() - timedelta(days=60),
    }
    project_clause = ""
    if project_id is not None:
        project_clause = " AND d.project_id = :project_id"
        params["project_id"] = str(project_id)

    async with TenantAwareSession(auth.organization_id) as session:
        expiring = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT d.id AS dossier_id, d.project_id, s.id AS stage_id,
                           s.stage_code, s.expiry_date,
                           (s.expiry_date - :today) AS days_until
                    FROM permit_stages s
                    JOIN permit_dossiers d ON d.id = s.dossier_id
                    WHERE d.organization_id = :org
                      AND s.status = 'approved'
                      AND s.expiry_date IS NOT NULL
                      AND s.expiry_date <= :horizon
                      AND s.expiry_date >= :today
                      {project_clause}
                    ORDER BY s.expiry_date ASC
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

        overdue = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT d.id AS dossier_id, d.project_id, s.id AS stage_id,
                           s.stage_code, s.target_submit_date,
                           (:today - s.target_submit_date) AS days_overdue
                    FROM permit_stages s
                    JOIN permit_dossiers d ON d.id = s.dossier_id
                    WHERE d.organization_id = :org
                      AND s.status IN ('preparing', 'not_started')
                      AND s.target_submit_date IS NOT NULL
                      AND s.target_submit_date < :today
                      {project_clause}
                    ORDER BY s.target_submit_date ASC
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
                    SELECT d.id AS dossier_id, d.project_id, s.id AS stage_id,
                           s.stage_code, s.submitted_date,
                           (:today - s.submitted_date) AS days_since
                    FROM permit_stages s
                    JOIN permit_dossiers d ON d.id = s.dossier_id
                    WHERE d.organization_id = :org
                      AND s.status IN ('submitted', 'in_review')
                      AND s.submitted_date IS NOT NULL
                      AND s.submitted_date <= :stall_cutoff
                      {project_clause}
                    ORDER BY s.submitted_date ASC
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

    alerts: list[PermitAlert] = []
    for r in expiring:
        days = int(r["days_until"])
        severity = "critical" if days <= 7 else "warning" if days <= 30 else "info"
        alerts.append(
            PermitAlert(
                dossier_id=r["dossier_id"],
                project_id=r["project_id"],
                stage_id=r["stage_id"],
                stage_code=StageCode(r["stage_code"]),
                code="expiring_soon",
                severity=severity,
                message=f"{r['stage_code']} expires in {days} day(s)",
                expiry_date=r["expiry_date"],
                days_until=days,
            )
        )
    for r in overdue:
        days = int(r["days_overdue"])
        alerts.append(
            PermitAlert(
                dossier_id=r["dossier_id"],
                project_id=r["project_id"],
                stage_id=r["stage_id"],
                stage_code=StageCode(r["stage_code"]),
                code="overdue_submission",
                severity="warning" if days <= 30 else "critical",
                message=f"Target submit date passed {days} day(s) ago",
                days_until=-days,
            )
        )
    for r in stalled:
        days = int(r["days_since"])
        alerts.append(
            PermitAlert(
                dossier_id=r["dossier_id"],
                project_id=r["project_id"],
                stage_id=r["stage_id"],
                stage_code=StageCode(r["stage_code"]),
                code="stalled_review",
                severity="warning",
                message=f"Submitted {days} day(s) ago with no outcome recorded",
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


def _dossier_where(f: DossierListFilters, org_id: UUID) -> tuple[str, dict[str, Any]]:
    clauses = ["d.organization_id = :org"]
    params: dict[str, Any] = {"org": str(org_id)}
    if f.project_id:
        clauses.append("d.project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.status:
        clauses.append("d.status = :status")
        params["status"] = f.status.value
    return " AND ".join(clauses), params


# Re-export for tests / external callers that want to peek at the matrix.
TRANSITIONS = _TRANSITIONS

__all__ = [
    "router",
    "TRANSITIONS",
    # Re-export common enums so callers don't double-import from schemas.
    "Authority",
    "ProjectClassification",
    "StageCode",
    "StageStatus",
    "DossierStatus",
    "SubmissionType",
    "SubmissionOutcome",
]
