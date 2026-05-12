"""THANHTOAN router — progress payment claims.

State machine:

  draft → submitted → in_review → approved → paid
                                ↘─ rejected (terminal)
                                ↘─ cancelled (any state pre-paid)

Both CĐT and TVGS sign separately; the claim only flips to `approved`
when CĐT approves (TVGS reject is recorded but doesn't terminate —
CĐT is the contractual decider). A CĐT `reject` lands the claim in
`rejected` regardless of TVGS state.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.thanhtoan import (
    ClaimListFilters,
    ClaimStatus,
    ClaimSummary,
    CumulativeRow,
    CumulativeView,
    EvidenceCreate,
    MarkPaidPayload,
    PartyDecision,
    PaymentClaim,
    PaymentClaimCreate,
    PaymentClaimDetail,
    PaymentClaimEvidence,
    PaymentClaimLine,
    PaymentClaimLineCreate,
    PaymentClaimLineUpdate,
    PaymentClaimUpdate,
    SignPayload,
    SubmitPayload,
    recompute_totals,
)

router = APIRouter(prefix="/api/v1/thanhtoan", tags=["thanhtoan"])


# Statuses that lock the line / header for editing.
_LOCKED_FOR_EDIT = {
    ClaimStatus.submitted,
    ClaimStatus.in_review,
    ClaimStatus.approved,
    ClaimStatus.rejected,
    ClaimStatus.paid,
    ClaimStatus.cancelled,
}


# ---------- Claims ----------


@router.post("/claims", status_code=status.HTTP_201_CREATED)
async def create_claim(
    payload: PaymentClaimCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Open a draft claim for a period.

    Sequence numbers are assigned per project: the next claim under
    project X gets `sequence = max(existing) + 1`. The string
    `claim_no` is caller-supplied so site teams can preserve their
    own numbering schemes (PT-2026-04, etc.).
    """
    claim_id = uuid4()

    async with TenantAwareSession(auth.organization_id) as session:
        next_seq = (
            await session.execute(
                text(
                    """
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM payment_claims
                WHERE organization_id = :org AND project_id = :project_id
                """
                ),
                {"org": str(auth.organization_id), "project_id": str(payload.project_id)},
            )
        ).scalar_one()
        cumulative_prev = (
            await session.execute(
                text(
                    """
                SELECT COALESCE(SUM(net_payable_vnd), 0)
                FROM payment_claims
                WHERE organization_id = :org
                  AND project_id = :project_id
                  AND status IN ('approved', 'paid')
                """
                ),
                {"org": str(auth.organization_id), "project_id": str(payload.project_id)},
            )
        ).scalar_one()

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO payment_claims
                      (id, organization_id, project_id, claim_no, sequence,
                       period_start, period_end, status,
                       subtotal_vnd, vat_pct, vat_vnd, gross_vnd,
                       retention_pct, retention_vnd, tndn_pct, tndn_vnd,
                       net_payable_vnd, cumulative_prev_vnd,
                       due_at, notes, created_by, created_at, updated_at)
                    VALUES
                      (:id, :org, :project_id, :claim_no, :sequence,
                       :period_start, :period_end, 'draft',
                       0, :vat_pct, 0, 0,
                       :retention_pct, 0, :tndn_pct, 0,
                       0, :cumulative_prev,
                       :due_at, :notes, :created_by, NOW(), NOW())
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(claim_id),
                        "org": str(auth.organization_id),
                        "project_id": str(payload.project_id),
                        "claim_no": payload.claim_no,
                        "sequence": int(next_seq),
                        "period_start": payload.period_start,
                        "period_end": payload.period_end,
                        "vat_pct": payload.vat_pct,
                        "retention_pct": payload.retention_pct,
                        "tndn_pct": payload.tndn_pct,
                        "cumulative_prev": int(cumulative_prev),
                        "due_at": payload.due_at,
                        "notes": payload.notes,
                        "created_by": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(PaymentClaim.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/claims")
async def list_claims(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    claim_status: ClaimStatus | None = Query(None, alias="status"),
    period_year: int | None = Query(None, ge=2000, le=2100),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = ClaimListFilters(
        project_id=project_id,
        status=claim_status,
        period_year=period_year,
        limit=limit,
        offset=offset,
    )
    where, params = _claim_where(filters, auth.organization_id)
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT c.*,
                           COALESCE(l.line_count, 0)::int AS line_count
                    FROM payment_claims c
                    LEFT JOIN (
                      SELECT claim_id, COUNT(*) AS line_count
                      FROM payment_claim_lines GROUP BY claim_id
                    ) l ON l.claim_id = c.id
                    WHERE {where}
                    ORDER BY c.period_end DESC, c.sequence DESC
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
            await session.execute(text(f"SELECT COUNT(*) FROM payment_claims c WHERE {where}"), params)
        ).scalar_one()

    items = [ClaimSummary.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.get("/claims/{claim_id}")
async def get_claim(
    claim_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        claim = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM payment_claims
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(claim_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if claim is None:
            raise HTTPException(status_code=404, detail="claim_not_found")

        lines = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM payment_claim_lines
                    WHERE claim_id = :id
                    ORDER BY sort_order ASC, created_at ASC
                    """
                    ),
                    {"id": str(claim_id)},
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
                    SELECT * FROM payment_claim_evidence
                    WHERE claim_id = :id
                    ORDER BY sort_order ASC, created_at ASC
                    """
                    ),
                    {"id": str(claim_id)},
                )
            )
            .mappings()
            .all()
        )

    detail = PaymentClaimDetail.model_validate(
        {
            **dict(claim),
            "lines": [PaymentClaimLine.model_validate(dict(line)) for line in lines],
            "evidence": [PaymentClaimEvidence.model_validate(dict(e)) for e in evidence],
        }
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/claims/{claim_id}")
async def update_claim(
    claim_id: UUID,
    payload: PaymentClaimUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(claim_id), "org": str(auth.organization_id)}
    if payload.period_start is not None:
        assigns.append("period_start = :period_start")
        params["period_start"] = payload.period_start
    if payload.period_end is not None:
        assigns.append("period_end = :period_end")
        params["period_end"] = payload.period_end
    if payload.vat_pct is not None:
        assigns.append("vat_pct = :vat_pct")
        params["vat_pct"] = payload.vat_pct
    if payload.retention_pct is not None:
        assigns.append("retention_pct = :retention_pct")
        params["retention_pct"] = payload.retention_pct
    if payload.tndn_pct is not None:
        assigns.append("tndn_pct = :tndn_pct")
        params["tndn_pct"] = payload.tndn_pct
    if payload.due_at is not None:
        assigns.append("due_at = :due_at")
        params["due_at"] = payload.due_at
    if payload.notes is not None:
        assigns.append("notes = :notes")
        params["notes"] = payload.notes
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        cur = await _ensure_draft(session, claim_id, auth.organization_id)
        # Tax-rate edits force a recompute so the header doesn't go
        # stale relative to the lines.
        needs_recompute = any(
            f is not None
            for f in (payload.vat_pct, payload.retention_pct, payload.tndn_pct)
        )

        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE payment_claims SET {", ".join(assigns)}
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
            raise HTTPException(status_code=404, detail="claim_not_found")

        if needs_recompute:
            row = await _do_recompute(session, claim_id, row)

    _ = cur  # silence linter — we used it as a precondition above.
    return ok(PaymentClaim.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Lines ----------


@router.post("/claims/{claim_id}/lines", status_code=status.HTTP_201_CREATED)
async def add_line(
    claim_id: UUID,
    payload: PaymentClaimLineCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Add a line and update header totals atomically.

    `cumulative_qty` for this line = (sum of `this_period_qty` across
    every prior approved claim for the same work_item_code) +
    `this_period_qty`. The cumulative amount is the cumulative qty ×
    unit rate (frozen on this line — historical rate changes don't
    rewrite prior approved lines).
    """
    async with TenantAwareSession(auth.organization_id) as session:
        claim = await _ensure_draft(session, claim_id, auth.organization_id)

        prior_qty = (
            await session.execute(
                text(
                    """
                SELECT COALESCE(SUM(l.this_period_qty), 0)
                FROM payment_claim_lines l
                JOIN payment_claims c ON c.id = l.claim_id
                WHERE c.organization_id = :org
                  AND c.project_id = :project_id
                  AND c.status IN ('approved', 'paid')
                  AND l.work_item_code = :code
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "project_id": str(claim["project_id"]),
                    "code": payload.work_item_code,
                },
            )
        ).scalar_one()

        cumulative_qty = Decimal(prior_qty) + payload.this_period_qty
        this_amount = int((payload.this_period_qty * payload.unit_rate_vnd).to_integral_value())
        cumulative_amount = int((cumulative_qty * payload.unit_rate_vnd).to_integral_value())
        completion_pct = (
            (cumulative_qty / payload.planned_qty * Decimal("100"))
            if payload.planned_qty > 0
            else None
        )

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO payment_claim_lines
                      (id, organization_id, claim_id, work_item_code, description,
                       unit, planned_qty, this_period_qty, cumulative_qty,
                       unit_rate_vnd, this_period_amount_vnd, cumulative_amount_vnd,
                       completion_pct, notes, evidence_file_ids, sort_order,
                       created_at, updated_at)
                    VALUES
                      (:id, :org, :claim_id, :code, :description,
                       :unit, :planned_qty, :this_period_qty, :cumulative_qty,
                       :unit_rate, :this_amount, :cumulative_amount,
                       :completion_pct, :notes, CAST(:evidence AS uuid[]), :sort_order,
                       NOW(), NOW())
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "claim_id": str(claim_id),
                        "code": payload.work_item_code,
                        "description": payload.description,
                        "unit": payload.unit,
                        "planned_qty": payload.planned_qty,
                        "this_period_qty": payload.this_period_qty,
                        "cumulative_qty": cumulative_qty,
                        "unit_rate": payload.unit_rate_vnd,
                        "this_amount": this_amount,
                        "cumulative_amount": cumulative_amount,
                        "completion_pct": completion_pct,
                        "notes": payload.notes,
                        "evidence": [str(f) for f in payload.evidence_file_ids],
                        "sort_order": payload.sort_order,
                    },
                )
            )
            .mappings()
            .one()
        )

        await _do_recompute(session, claim_id, claim)

    return ok(PaymentClaimLine.model_validate(dict(row)).model_dump(mode="json"))


@router.patch("/lines/{line_id}")
async def update_line(
    line_id: UUID,
    payload: PaymentClaimLineUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Edit a line on a draft claim. Recomputes the header on save."""
    async with TenantAwareSession(auth.organization_id) as session:
        line = (
            (
                await session.execute(
                    text(
                        """
                    SELECT l.*, c.status AS claim_status, c.id AS claim_id_fk
                    FROM payment_claim_lines l
                    JOIN payment_claims c ON c.id = l.claim_id
                    WHERE l.id = :id AND l.organization_id = :org
                    """
                    ),
                    {"id": str(line_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if line is None:
            raise HTTPException(status_code=404, detail="line_not_found")
        if ClaimStatus(line["claim_status"]) in _LOCKED_FOR_EDIT:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "claim_locked",
                    "message": "Claim đã nộp / phê duyệt — không sửa được dòng.",
                },
            )

        # Re-derive amounts from new (or existing) qty + rate.
        new_qty = payload.this_period_qty if payload.this_period_qty is not None else line["this_period_qty"]
        new_rate = payload.unit_rate_vnd if payload.unit_rate_vnd is not None else line["unit_rate_vnd"]
        this_amount = int((Decimal(new_qty) * Decimal(new_rate)).to_integral_value())
        # cumulative_qty bumps by (new_qty - old_qty).
        delta = Decimal(new_qty) - Decimal(line["this_period_qty"])
        cumulative_qty = Decimal(line["cumulative_qty"]) + delta
        cumulative_amount = int((cumulative_qty * Decimal(new_rate)).to_integral_value())
        completion_pct = (
            (cumulative_qty / Decimal(line["planned_qty"]) * Decimal("100"))
            if Decimal(line["planned_qty"]) > 0
            else None
        )

        assigns = [
            "this_period_qty = :this_period_qty",
            "unit_rate_vnd = :unit_rate",
            "this_period_amount_vnd = :this_amount",
            "cumulative_qty = :cumulative_qty",
            "cumulative_amount_vnd = :cumulative_amount",
            "completion_pct = :completion_pct",
            "updated_at = NOW()",
        ]
        params: dict[str, Any] = {
            "id": str(line_id),
            "this_period_qty": new_qty,
            "unit_rate": new_rate,
            "this_amount": this_amount,
            "cumulative_qty": cumulative_qty,
            "cumulative_amount": cumulative_amount,
            "completion_pct": completion_pct,
        }
        if payload.description is not None:
            assigns.append("description = :description")
            params["description"] = payload.description
        if payload.notes is not None:
            assigns.append("notes = :notes")
            params["notes"] = payload.notes
        if payload.evidence_file_ids is not None:
            assigns.append("evidence_file_ids = CAST(:evidence AS uuid[])")
            params["evidence"] = [str(f) for f in payload.evidence_file_ids]

        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE payment_claim_lines SET {", ".join(assigns)}
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

        await _do_recompute(session, line["claim_id_fk"], None)

    return ok(PaymentClaimLine.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Recompute, submit, sign, mark-paid ----------


@router.post("/claims/{claim_id}/recompute")
async def recompute_claim(
    claim_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Re-derive header money columns from the line table.

    Useful after a manual SQL edit or before submitting if the auditor
    wants to refresh the totals. Idempotent and cheap.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        claim = await _ensure_draft(session, claim_id, auth.organization_id)
        row = await _do_recompute(session, claim_id, claim)
    return ok(PaymentClaim.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/claims/{claim_id}/submit")
async def submit_claim(
    claim_id: UUID,
    payload: SubmitPayload,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Move draft → submitted.

    Side effects:
      * Recompute header one last time so what's submitted is what's
        on file.
      * Refresh `cumulative_prev_vnd` so a contemporaneous approval on
        another claim doesn't double-count.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        claim = await _ensure_draft(session, claim_id, auth.organization_id)
        await _do_recompute(session, claim_id, claim)

        cumulative_prev = (
            await session.execute(
                text(
                    """
                SELECT COALESCE(SUM(net_payable_vnd), 0)
                FROM payment_claims
                WHERE organization_id = :org
                  AND project_id = :project_id
                  AND id <> :id
                  AND status IN ('approved', 'paid')
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "project_id": str(claim["project_id"]),
                    "id": str(claim_id),
                },
            )
        ).scalar_one()

        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE payment_claims SET
                      status = 'submitted',
                      submitted_at = NOW(),
                      cumulative_prev_vnd = :cumulative_prev,
                      notes = COALESCE(:notes, notes),
                      updated_at = NOW()
                    WHERE id = :id
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(claim_id),
                        "cumulative_prev": int(cumulative_prev),
                        "notes": payload.notes,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(PaymentClaim.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/claims/{claim_id}/sign")
async def sign_claim(
    claim_id: UUID,
    payload: SignPayload,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Record CĐT or TVGS decision.

    CĐT approve → status `approved`; CĐT reject → status `rejected`.
    TVGS decisions are persisted but don't flip status — CĐT is the
    contractual decider per a typical FIDIC-based VN contract.
    """
    role = (payload.role or "").lower()
    if role not in ("cdt", "tvgs"):
        raise HTTPException(status_code=422, detail="role_must_be_cdt_or_tvgs")

    async with TenantAwareSession(auth.organization_id) as session:
        cur = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, status FROM payment_claims
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(claim_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if cur is None:
            raise HTTPException(status_code=404, detail="claim_not_found")
        cur_status = ClaimStatus(cur["status"])
        if cur_status not in (ClaimStatus.submitted, ClaimStatus.in_review):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "claim_not_in_review",
                    "message": (
                        f"Claim ở trạng thái '{cur_status.value}' — chỉ ký được "
                        "khi 'submitted' hoặc 'in_review'."
                    ),
                },
            )

        assigns = [
            f"{role}_signed_at = NOW()",
            f"{role}_signed_by = :user_id",
            f"{role}_decision = :decision",
            f"{role}_comment = :comment",
            "updated_at = NOW()",
        ]
        params: dict[str, Any] = {
            "id": str(claim_id),
            "user_id": str(auth.user_id),
            "decision": payload.decision.value,
            "comment": payload.comment,
        }

        # CĐT decision is terminal.
        if role == "cdt":
            if payload.decision == PartyDecision.approve:
                assigns.extend(["status = 'approved'", "approved_at = NOW()"])
            else:
                assigns.extend(["status = 'rejected'", "rejected_at = NOW()"])
        elif cur_status == ClaimStatus.submitted:
            # Move into `in_review` on first TVGS interaction so the UI
            # shows the right active stage.
            assigns.append("status = 'in_review'")

        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE payment_claims SET {", ".join(assigns)}
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

    return ok(PaymentClaim.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/claims/{claim_id}/mark-paid")
async def mark_paid(
    claim_id: UUID,
    payload: MarkPaidPayload,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Record actual payment. Only valid from `approved`."""
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE payment_claims SET
                      status = 'paid',
                      paid_at = :paid_at,
                      payment_reference = :ref,
                      updated_at = NOW()
                    WHERE id = :id
                      AND organization_id = :org
                      AND status = 'approved'
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(claim_id),
                        "org": str(auth.organization_id),
                        "paid_at": payload.paid_at,
                        "ref": payload.payment_reference,
                    },
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "claim_not_approved",
                    "message": "Claim phải ở trạng thái 'approved' mới mark paid được.",
                },
            )
    return ok(PaymentClaim.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/claims/{claim_id}/cancel")
async def cancel_claim(
    claim_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Cancel a not-yet-paid claim. Terminal — re-issue is a new claim."""
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE payment_claims SET status = 'cancelled', updated_at = NOW()
                    WHERE id = :id
                      AND organization_id = :org
                      AND status <> 'paid'
                    RETURNING *
                    """
                    ),
                    {"id": str(claim_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(status_code=409, detail="cannot_cancel_paid_or_missing")
    return ok(PaymentClaim.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Evidence ----------


@router.post("/claims/{claim_id}/evidence", status_code=status.HTTP_201_CREATED)
async def add_evidence(
    claim_id: UUID,
    payload: EvidenceCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    if payload.file_id is None and payload.external_ref is None:
        raise HTTPException(
            status_code=400,
            detail="evidence_requires_file_id_or_external_ref",
        )

    async with TenantAwareSession(auth.organization_id) as session:
        claim = (
            await session.execute(
                text(
                    """
                SELECT id FROM payment_claims
                WHERE id = :id AND organization_id = :org
                """
                ),
                {"id": str(claim_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if claim is None:
            raise HTTPException(status_code=404, detail="claim_not_found")

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO payment_claim_evidence
                      (id, organization_id, claim_id, kind, file_id, external_ref,
                       caption, payload, sort_order)
                    VALUES
                      (:id, :org, :claim_id, :kind, :file_id, :external_ref,
                       :caption, CAST(:payload AS jsonb), :sort_order)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "claim_id": str(claim_id),
                        "kind": payload.kind.value,
                        "file_id": str(payload.file_id) if payload.file_id else None,
                        "external_ref": payload.external_ref,
                        "caption": payload.caption,
                        "payload": _json(payload.payload),
                        "sort_order": payload.sort_order,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(PaymentClaimEvidence.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Cumulative (cross-period) ----------


@router.get("/claims/{claim_id}/cumulative")
async def cumulative_view(
    claim_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Per-work-item running totals across every approved claim on the
    same project, plus this claim's lines. Useful for the BBNT cover
    sheet that shows 'Khối lượng luỹ kế'."""
    async with TenantAwareSession(auth.organization_id) as session:
        claim = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, project_id FROM payment_claims
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(claim_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if claim is None:
            raise HTTPException(status_code=404, detail="claim_not_found")

        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT l.work_item_code,
                           MAX(l.description) AS description,
                           MAX(l.unit) AS unit,
                           MAX(l.planned_qty) AS planned_qty,
                           SUM(
                             CASE WHEN c.status IN ('approved', 'paid') OR c.id = :id
                                  THEN l.this_period_qty ELSE 0 END
                           ) AS cumulative_qty,
                           SUM(
                             CASE WHEN c.status IN ('approved', 'paid') OR c.id = :id
                                  THEN l.this_period_amount_vnd ELSE 0 END
                           )::bigint AS cumulative_amount_vnd
                    FROM payment_claim_lines l
                    JOIN payment_claims c ON c.id = l.claim_id
                    WHERE c.organization_id = :org
                      AND c.project_id = :project_id
                    GROUP BY l.work_item_code
                    ORDER BY l.work_item_code
                    """
                    ),
                    {
                        "org": str(auth.organization_id),
                        "project_id": str(claim["project_id"]),
                        "id": str(claim_id),
                    },
                )
            )
            .mappings()
            .all()
        )

    items: list[CumulativeRow] = []
    grand = 0
    for r in rows:
        cumulative_qty = Decimal(r["cumulative_qty"] or 0)
        planned_qty = Decimal(r["planned_qty"] or 0)
        pct = (cumulative_qty / planned_qty * Decimal("100")) if planned_qty > 0 else None
        items.append(
            CumulativeRow(
                work_item_code=r["work_item_code"],
                description=r["description"] or "",
                unit=r["unit"] or "",
                planned_qty=planned_qty,
                cumulative_qty=cumulative_qty,
                cumulative_amount_vnd=int(r["cumulative_amount_vnd"] or 0),
                completion_pct=pct,
            )
        )
        grand += int(r["cumulative_amount_vnd"] or 0)

    return ok(
        CumulativeView(
            claim_id=claim_id,
            project_id=claim["project_id"],
            rows=items,
            grand_total_vnd=grand,
        ).model_dump(mode="json")
    )


# ---------- Internal helpers ----------


async def _ensure_draft(session, claim_id: UUID, org_id: UUID) -> dict[str, Any]:
    """Fetch the claim and 409 if it's past draft. Returns the row."""
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT * FROM payment_claims
                WHERE id = :id AND organization_id = :org
                """
                ),
                {"id": str(claim_id), "org": str(org_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="claim_not_found")
    if ClaimStatus(row["status"]) != ClaimStatus.draft:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "claim_not_draft",
                "message": "Chỉ chỉnh sửa được claim ở trạng thái 'draft'.",
            },
        )
    return dict(row)


async def _do_recompute(session, claim_id: UUID, claim_row: dict | None) -> dict:
    """Recompute header money columns from the line table + persist."""
    lines = (
        await session.execute(
            text(
                """
            SELECT this_period_amount_vnd
            FROM payment_claim_lines
            WHERE claim_id = :id
            """
            ),
            {"id": str(claim_id)},
        )
    ).all()
    amounts = [int(r[0]) for r in lines]

    if claim_row is None:
        claim_row_result = (
            (
                await session.execute(
                    text(
                        """
                    SELECT vat_pct, retention_pct, tndn_pct
                    FROM payment_claims WHERE id = :id
                    """
                    ),
                    {"id": str(claim_id)},
                )
            )
            .mappings()
            .one()
        )
        vat_pct = Decimal(claim_row_result["vat_pct"])
        retention_pct = Decimal(claim_row_result["retention_pct"])
        tndn_pct = Decimal(claim_row_result["tndn_pct"])
    else:
        vat_pct = Decimal(claim_row["vat_pct"])
        retention_pct = Decimal(claim_row["retention_pct"])
        tndn_pct = Decimal(claim_row["tndn_pct"])

    totals = recompute_totals(amounts, vat_pct, retention_pct, tndn_pct)

    row = (
        (
            await session.execute(
                text(
                    """
                UPDATE payment_claims SET
                  subtotal_vnd = :subtotal,
                  vat_vnd = :vat,
                  gross_vnd = :gross,
                  retention_vnd = :retention,
                  tndn_vnd = :tndn,
                  net_payable_vnd = :net,
                  updated_at = NOW()
                WHERE id = :id
                RETURNING *
                """
                ),
                {
                    "id": str(claim_id),
                    "subtotal": totals["subtotal_vnd"],
                    "vat": totals["vat_vnd"],
                    "gross": totals["gross_vnd"],
                    "retention": totals["retention_vnd"],
                    "tndn": totals["tndn_vnd"],
                    "net": totals["net_payable_vnd"],
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=_default_serializer, ensure_ascii=False)


def _default_serializer(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not serializable: {type(value)}")


def _claim_where(f: ClaimListFilters, org_id: UUID) -> tuple[str, dict[str, Any]]:
    clauses = ["c.organization_id = :org"]
    params: dict[str, Any] = {"org": str(org_id)}
    if f.project_id:
        clauses.append("c.project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.status:
        clauses.append("c.status = :status")
        params["status"] = f.status.value
    if f.period_year:
        clauses.append("EXTRACT(YEAR FROM c.period_end) = :year")
        params["year"] = f.period_year
    return " AND ".join(clauses), params


# Re-export so tests can call without round-tripping through the API.
__all__ = ["router", "recompute_totals"]
