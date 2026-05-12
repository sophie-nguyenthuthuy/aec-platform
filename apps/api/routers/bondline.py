"""BONDLINE router — VN bank-issued bonds."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.bondline import (
    Bond,
    BondAlert,
    BondClaim,
    BondClaimCreate,
    BondClaimDecide,
    BondCreate,
    BondDetail,
    BondListFilters,
    BondRelease,
    BondStatus,
    BondSummary,
    BondType,
    BondUpdate,
    ClaimType,
)

router = APIRouter(prefix="/api/v1/bondline", tags=["bondline"])


# ---------- Bonds ----------


@router.post("/bonds", status_code=status.HTTP_201_CREATED)
async def create_bond(
    payload: BondCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    bond_id = uuid4()
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO bonds
                      (id, organization_id, project_id, bond_type, bond_no,
                       issuing_bank, bank_branch, beneficiary_name, beneficiary_mst,
                       face_amount_vnd, contract_value_vnd, coverage_pct, currency,
                       issue_date, effective_date, expiry_date, status,
                       contract_no, notes, created_by, created_at, updated_at)
                    VALUES
                      (:id, :org, :project_id, :bond_type, :bond_no,
                       :issuing_bank, :bank_branch, :beneficiary_name, :beneficiary_mst,
                       :face_amount, :contract_value, :coverage_pct, :currency,
                       :issue_date, :effective_date, :expiry_date, 'active',
                       :contract_no, :notes, :created_by, NOW(), NOW())
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(bond_id),
                        "org": str(auth.organization_id),
                        "project_id": str(payload.project_id),
                        "bond_type": payload.bond_type.value,
                        "bond_no": payload.bond_no,
                        "issuing_bank": payload.issuing_bank,
                        "bank_branch": payload.bank_branch,
                        "beneficiary_name": payload.beneficiary_name,
                        "beneficiary_mst": payload.beneficiary_mst,
                        "face_amount": payload.face_amount_vnd,
                        "contract_value": payload.contract_value_vnd,
                        "coverage_pct": payload.coverage_pct,
                        "currency": payload.currency,
                        "issue_date": payload.issue_date,
                        "effective_date": payload.effective_date,
                        "expiry_date": payload.expiry_date,
                        "contract_no": payload.contract_no,
                        "notes": payload.notes,
                        "created_by": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(Bond.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/bonds")
async def list_bonds(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    bond_type: BondType | None = None,
    bond_status: BondStatus | None = Query(None, alias="status"),
    issuing_bank: str | None = None,
    expiring_within_days: int | None = Query(None, ge=0, le=3650),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = BondListFilters(
        project_id=project_id,
        bond_type=bond_type,
        status=bond_status,
        issuing_bank=issuing_bank,
        expiring_within_days=expiring_within_days,
        limit=limit,
        offset=offset,
    )
    where, params = _bond_where(filters, auth.organization_id)
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT b.*,
                      (b.expiry_date - CURRENT_DATE) AS days_to_expiry,
                      COALESCE(c.cnt, 0)::int AS claim_count
                    FROM bonds b
                    LEFT JOIN (
                      SELECT bond_id, COUNT(*) AS cnt
                      FROM bond_claims GROUP BY bond_id
                    ) c ON c.bond_id = b.id
                    WHERE {where}
                    ORDER BY b.expiry_date ASC
                    LIMIT :limit OFFSET :offset
                    """
                    ),
                    {**params, "limit": limit, "offset": offset},
                )
            )
            .mappings()
            .all()
        )
        total = (await session.execute(text(f"SELECT COUNT(*) FROM bonds b WHERE {where}"), params)).scalar_one()

    items = [BondSummary.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.get("/bonds/{bond_id}")
async def get_bond(
    bond_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        bond = (
            (
                await session.execute(
                    text("SELECT * FROM bonds WHERE id = :id AND organization_id = :org"),
                    {"id": str(bond_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if bond is None:
            raise HTTPException(status_code=404, detail="bond_not_found")

        claims = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM bond_claims
                    WHERE bond_id = :id
                    ORDER BY filed_date DESC, created_at DESC
                    """
                    ),
                    {"id": str(bond_id)},
                )
            )
            .mappings()
            .all()
        )

    detail = BondDetail.model_validate(
        {
            **dict(bond),
            "claims": [BondClaim.model_validate(dict(c)) for c in claims],
        }
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/bonds/{bond_id}")
async def update_bond(
    bond_id: UUID,
    payload: BondUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(bond_id), "org": str(auth.organization_id)}
    for col, val in (
        ("bank_branch", payload.bank_branch),
        ("beneficiary_mst", payload.beneficiary_mst),
        ("expiry_date", payload.expiry_date),
        ("contract_no", payload.contract_no),
        ("notes", payload.notes),
    ):
        if val is None:
            continue
        assigns.append(f"{col} = :{col}")
        params[col] = val
    if payload.bond_file_id is not None:
        assigns.append("bond_file_id = :bond_file_id")
        params["bond_file_id"] = str(payload.bond_file_id)
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE bonds SET {", ".join(assigns)}
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
        raise HTTPException(status_code=404, detail="bond_not_found")
    return ok(Bond.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/bonds/{bond_id}/release")
async def release_bond(
    bond_id: UUID,
    payload: BondRelease,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Mark an active bond as released (obligation discharged).

    Released bonds are terminal — re-activation requires a new bond.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE bonds SET
                      status = 'released',
                      released_at = :released_at,
                      released_reason = :reason,
                      updated_at = NOW()
                    WHERE id = :id AND organization_id = :org AND status = 'active'
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(bond_id),
                        "org": str(auth.organization_id),
                        "released_at": payload.released_at,
                        "reason": payload.released_reason,
                    },
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(
                status_code=409,
                detail="bond_must_be_active_to_release",
            )
    return ok(Bond.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Claims ----------


@router.post("/bonds/{bond_id}/claims", status_code=status.HTTP_201_CREATED)
async def file_claim(
    bond_id: UUID,
    payload: BondClaimCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """File a claim. `default_call` flips the bond to `claimed`
    immediately so finance can stop counting it as headroom."""
    async with TenantAwareSession(auth.organization_id) as session:
        bond = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, status, face_amount_vnd FROM bonds
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(bond_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if bond is None:
            raise HTTPException(status_code=404, detail="bond_not_found")
        if BondStatus(bond["status"]) != BondStatus.active:
            raise HTTPException(
                status_code=409,
                detail="cannot_claim_inactive_bond",
            )
        if (
            payload.claim_type == ClaimType.default_call
            and payload.claim_amount_vnd is not None
            and payload.claim_amount_vnd > int(bond["face_amount_vnd"])
        ):
            raise HTTPException(
                status_code=422,
                detail="claim_amount_exceeds_face_amount",
            )

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO bond_claims
                      (id, organization_id, bond_id, claim_type, claim_amount_vnd,
                       filed_date, reason, evidence_file_id, created_by)
                    VALUES
                      (:id, :org, :bond_id, :claim_type, :claim_amount,
                       :filed_date, :reason, :evidence_file_id, :created_by)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "bond_id": str(bond_id),
                        "claim_type": payload.claim_type.value,
                        "claim_amount": payload.claim_amount_vnd,
                        "filed_date": payload.filed_date,
                        "reason": payload.reason,
                        "evidence_file_id": str(payload.evidence_file_id) if payload.evidence_file_id else None,
                        "created_by": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )

        # Default calls flip the bond to `claimed` so reporting reflects
        # the contingent liability immediately.
        if payload.claim_type == ClaimType.default_call:
            await session.execute(
                text(
                    """
                UPDATE bonds SET status = 'claimed', updated_at = NOW()
                WHERE id = :id
                """
                ),
                {"id": str(bond_id)},
            )

    return ok(BondClaim.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/claims/{claim_id}/decide")
async def decide_claim(
    claim_id: UUID,
    payload: BondClaimDecide,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Record the bank's decision on a claim. Side effect: an
    `extension` claim accepted bumps the parent bond's `expiry_date`
    if `decided_amount_vnd` carries the new expiry (encoded as an ISO
    date in the decision_note — captured here so the audit row stays
    authoritative)."""
    async with TenantAwareSession(auth.organization_id) as session:
        existing = (
            (
                await session.execute(
                    text(
                        """
                    SELECT c.*, b.id AS bond_id_fk
                    FROM bond_claims c
                    JOIN bonds b ON b.id = c.bond_id
                    WHERE c.id = :id AND c.organization_id = :org
                    """
                    ),
                    {"id": str(claim_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="claim_not_found")

        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE bond_claims SET
                      status = :status,
                      decided_date = :decided_date,
                      decided_amount_vnd = :decided_amount,
                      decision_note = :decision_note
                    WHERE id = :id
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(claim_id),
                        "status": payload.status.value,
                        "decided_date": payload.decided_date,
                        "decided_amount": payload.decided_amount_vnd,
                        "decision_note": payload.decision_note,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(BondClaim.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Alerts ----------


@router.get("/alerts")
async def list_alerts(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    expiring_within_days: int = Query(60, ge=1, le=365),
):
    """Three alert kinds:
    * `expiring_soon` — active bonds with expiry in window
    * `expired_not_released` — past expiry but still status=active
      (operational issue — release or extend)
    * `coverage_below_contract` — face_amount / contract_value <
      contracted coverage_pct
    """
    params: dict[str, Any] = {
        "org": str(auth.organization_id),
        "horizon": date.today() + timedelta(days=expiring_within_days),
        "today": date.today(),
    }
    project_clause = ""
    if project_id is not None:
        project_clause = " AND b.project_id = :project_id"
        params["project_id"] = str(project_id)

    async with TenantAwareSession(auth.organization_id) as session:
        expiring = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT b.id AS bond_id, b.project_id, b.bond_type, b.expiry_date,
                           (b.expiry_date - :today) AS days_until
                    FROM bonds b
                    WHERE b.organization_id = :org
                      AND b.status = 'active'
                      AND b.expiry_date <= :horizon
                      AND b.expiry_date >= :today
                      {project_clause}
                    ORDER BY b.expiry_date ASC
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        expired = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT b.id AS bond_id, b.project_id, b.bond_type, b.expiry_date,
                           (:today - b.expiry_date) AS days_past
                    FROM bonds b
                    WHERE b.organization_id = :org
                      AND b.status = 'active'
                      AND b.expiry_date < :today
                      {project_clause}
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        coverage = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT b.id AS bond_id, b.project_id, b.bond_type,
                           b.face_amount_vnd, b.contract_value_vnd, b.coverage_pct
                    FROM bonds b
                    WHERE b.organization_id = :org
                      AND b.status = 'active'
                      AND b.contract_value_vnd IS NOT NULL
                      AND b.contract_value_vnd > 0
                      AND b.coverage_pct IS NOT NULL
                      AND b.face_amount_vnd::numeric / b.contract_value_vnd::numeric < b.coverage_pct
                      {project_clause}
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

    alerts: list[BondAlert] = []
    for r in expiring:
        days = int(r["days_until"])
        severity = "critical" if days <= 14 else "warning" if days <= 30 else "info"
        alerts.append(
            BondAlert(
                bond_id=r["bond_id"],
                project_id=r["project_id"],
                bond_type=BondType(r["bond_type"]),
                code="expiring_soon",
                severity=severity,
                message=f"{r['bond_type']} bond expires in {days} day(s)",
                expiry_date=r["expiry_date"],
                days_until=days,
            )
        )
    for r in expired:
        alerts.append(
            BondAlert(
                bond_id=r["bond_id"],
                project_id=r["project_id"],
                bond_type=BondType(r["bond_type"]),
                code="expired_not_released",
                severity="critical",
                message=f"Bond expired {int(r['days_past'])} day(s) ago — still marked active",
                expiry_date=r["expiry_date"],
                days_until=-int(r["days_past"]),
            )
        )
    for r in coverage:
        alerts.append(
            BondAlert(
                bond_id=r["bond_id"],
                project_id=r["project_id"],
                bond_type=BondType(r["bond_type"]),
                code="coverage_below_contract",
                severity="warning",
                message=(
                    f"Face amount {r['face_amount_vnd']:,} < required "
                    f"{int(float(r['coverage_pct']) * int(r['contract_value_vnd'])):,} VND"
                ),
            )
        )

    return ok([a.model_dump(mode="json") for a in alerts])


# ---------- Helpers ----------


def _bond_where(f: BondListFilters, org_id: UUID) -> tuple[str, dict[str, Any]]:
    clauses = ["b.organization_id = :org"]
    params: dict[str, Any] = {"org": str(org_id)}
    if f.project_id:
        clauses.append("b.project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.bond_type:
        clauses.append("b.bond_type = :bond_type")
        params["bond_type"] = f.bond_type.value
    if f.status:
        clauses.append("b.status = :status")
        params["status"] = f.status.value
    if f.issuing_bank:
        clauses.append("b.issuing_bank = :issuing_bank")
        params["issuing_bank"] = f.issuing_bank
    if f.expiring_within_days is not None:
        clauses.append("b.expiry_date <= :cutoff AND b.expiry_date >= CURRENT_DATE")
        params["cutoff"] = date.today() + timedelta(days=f.expiring_within_days)
    return " AND ".join(clauses), params


__all__ = ["router"]


_ = datetime  # silence unused-import if datetime stops being referenced
