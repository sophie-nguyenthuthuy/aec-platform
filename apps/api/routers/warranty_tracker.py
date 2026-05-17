"""WarrantyTracker — claims workflow + upcoming-expiry surface.

Builds on the existing /handover/warranties endpoint with new
workflow + reminder endpoints:

  * GET    /api/v1/warranty-tracker/projects/{pid}/expiring
           — warranties expiring in the next 90 days (KPI tile data).
  * POST   /api/v1/warranty-tracker/items/{wid}/claims
           — file a claim for a warranty item.
  * GET    /api/v1/warranty-tracker/projects/{pid}/claims
           — list claims with their warranty + project context.
  * PATCH  /api/v1/warranty-tracker/claims/{cid}
           — update status / cost / resolution.
  * GET    /api/v1/warranty-tracker/projects/{pid}/summary
           — KPI rollup (active warranties / open claims /
             expiring 30d / cost vendor-covered).

The daily reminder cron (`warranty_reminder_cron`) is registered
in `workers/queue.py` separately.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import text

from core.envelope import ok
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role

router = APIRouter(prefix="/api/v1/warranty-tracker", tags=["warranty-tracker"])


# ---------- Schemas ----------


class ClaimCreate(BaseModel):
    severity: Literal["minor", "major", "critical"] = "major"
    summary: str = Field(min_length=2, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    reporter_name: str | None = Field(default=None, max_length=200)
    reporter_email: EmailStr | None = None
    reporter_phone: str | None = Field(default=None, max_length=20)
    reported_on: date | None = None
    linked_defect_id: UUID | None = None
    evidence_file_ids: list[UUID] | None = None


class ClaimUpdate(BaseModel):
    """All fields optional — PATCH semantics."""
    status: (
        Literal[
            "open",
            "investigating",
            "vendor_notified",
            "in_repair",
            "resolved",
            "rejected",
            "abandoned",
        ]
        | None
    ) = None
    severity: Literal["minor", "major", "critical"] | None = None
    acknowledged_on: date | None = None
    resolved_on: date | None = None
    cost_vnd: int | None = Field(default=None, ge=0)
    paid_by: (
        Literal["vendor_covered", "contractor_absorbed", "owner_paid", "shared"]
        | None
    ) = None
    description: str | None = Field(default=None, max_length=5000)


# ---------- Expiring warranties ----------


@router.get("/projects/{project_id}/expiring")
async def list_expiring(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    days: Annotated[int, Query(ge=7, le=365)] = 90,
):
    """Warranties expiring in the next N days. Sorted by expiry ASC
    (most-urgent first). The default 90 days matches the reminder
    cron's farthest-out window."""
    horizon = date.today() + timedelta(days=days)

    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        w.id, w.item_name, w.category, w.vendor,
                        w.start_date, w.expiry_date, w.warranty_period_months,
                        w.coverage, w.status, w.claim_contact,
                        (w.expiry_date - CURRENT_DATE)::int AS days_to_expiry
                    FROM warranty_items w
                    WHERE w.project_id = :pid
                      AND w.expiry_date IS NOT NULL
                      AND w.expiry_date <= :horizon
                      AND w.status = 'active'
                    ORDER BY w.expiry_date ASC NULLS LAST
                    """
                ),
                {"pid": str(project_id), "horizon": horizon},
            )
        ).mappings().all()

    return ok(
        {
            "horizon_days": days,
            "items": [
                {
                    "id": str(r["id"]),
                    "item_name": r["item_name"],
                    "category": r["category"],
                    "vendor": r["vendor"],
                    "start_date": r["start_date"].isoformat() if r["start_date"] else None,
                    "expiry_date": r["expiry_date"].isoformat() if r["expiry_date"] else None,
                    "days_to_expiry": int(r["days_to_expiry"]) if r["days_to_expiry"] is not None else None,
                    "warranty_period_months": r["warranty_period_months"],
                    "coverage": r["coverage"],
                    "status": r["status"],
                    "claim_contact": r["claim_contact"],
                }
                for r in rows
            ],
        }
    )


# ---------- Claims ----------


@router.post(
    "/items/{warranty_item_id}/claims",
    status_code=status.HTTP_201_CREATED,
)
async def file_claim(
    warranty_item_id: UUID,
    payload: ClaimCreate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.MEMBER))],
):
    """File a warranty claim. Member-writable — facilities team /
    PMs file claims daily; not gated to admin."""
    async with TenantAwareSession(auth.organization_id) as session:
        # Verify the warranty exists + is active (no claims on expired
        # warranties — should file a separate cost dispute instead).
        warranty = (
            await session.execute(
                text(
                    """
                    SELECT id, expiry_date, status
                    FROM warranty_items
                    WHERE id = :id
                    """
                ),
                {"id": str(warranty_item_id)},
            )
        ).mappings().one_or_none()
        if warranty is None:
            raise HTTPException(404, "warranty_item_not_found")
        if warranty["status"] != "active":
            raise HTTPException(
                400,
                f"cannot file claim — warranty status is '{warranty['status']}'",
            )
        if warranty["expiry_date"] and warranty["expiry_date"] < date.today():
            raise HTTPException(
                400,
                "cannot file claim — warranty already expired; file a separate dispute",
            )

        claim_id = uuid4()
        await session.execute(
            text(
                """
                INSERT INTO warranty_claims
                    (id, organization_id, warranty_item_id, severity, summary,
                     description, reporter_name, reporter_email, reporter_phone,
                     reported_on, linked_defect_id, evidence_file_ids, created_by)
                VALUES (:id, :org, :wid, :sev, :sum, :desc,
                        :rname, :remail, :rphone, :reported, :defect,
                        :files, :uid)
                """
            ),
            {
                "id": str(claim_id),
                "org": str(auth.organization_id),
                "wid": str(warranty_item_id),
                "sev": payload.severity,
                "sum": payload.summary,
                "desc": payload.description,
                "rname": payload.reporter_name,
                "remail": payload.reporter_email,
                "rphone": payload.reporter_phone,
                "reported": payload.reported_on or date.today(),
                "defect": str(payload.linked_defect_id)
                if payload.linked_defect_id
                else None,
                "files": [str(f) for f in payload.evidence_file_ids]
                if payload.evidence_file_ids
                else None,
                "uid": str(auth.user_id),
            },
        )
        await session.commit()

    return ok({"id": str(claim_id)})


@router.get("/projects/{project_id}/claims")
async def list_claims(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    """Claims for a project — joined with their warranty item for the
    list view (item_name + vendor inlined)."""
    where = ["w.project_id = :pid"]
    params: dict[str, Any] = {"pid": str(project_id), "limit": limit}
    if status_filter:
        where.append("c.status = :status")
        params["status"] = status_filter

    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT
                        c.id, c.status, c.severity, c.summary, c.description,
                        c.reporter_name, c.reporter_email,
                        c.reported_on, c.acknowledged_on, c.resolved_on,
                        c.cost_vnd, c.paid_by, c.created_at,
                        w.id AS warranty_item_id,
                        w.item_name, w.vendor, w.expiry_date
                    FROM warranty_claims c
                    JOIN warranty_items w ON w.id = c.warranty_item_id
                    WHERE {' AND '.join(where)}
                    ORDER BY c.created_at DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
        ).mappings().all()

    return ok(
        {
            "claims": [
                {
                    "id": str(r["id"]),
                    "status": r["status"],
                    "severity": r["severity"],
                    "summary": r["summary"],
                    "description": r["description"],
                    "reporter_name": r["reporter_name"],
                    "reporter_email": r["reporter_email"],
                    "reported_on": r["reported_on"].isoformat() if r["reported_on"] else None,
                    "acknowledged_on": r["acknowledged_on"].isoformat() if r["acknowledged_on"] else None,
                    "resolved_on": r["resolved_on"].isoformat() if r["resolved_on"] else None,
                    "cost_vnd": int(r["cost_vnd"]) if r["cost_vnd"] else None,
                    "paid_by": r["paid_by"],
                    "warranty_item_id": str(r["warranty_item_id"]),
                    "item_name": r["item_name"],
                    "vendor": r["vendor"],
                    "expiry_date": r["expiry_date"].isoformat() if r["expiry_date"] else None,
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ]
        }
    )


@router.patch("/claims/{claim_id}")
async def update_claim(
    claim_id: UUID,
    payload: ClaimUpdate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.MEMBER))],
):
    """Patch any subset. Auto-stamps `resolved_on` if status flips to
    resolved/rejected and resolved_on isn't explicitly provided."""
    fields: dict[str, Any] = {}
    if payload.status is not None:
        fields["status"] = payload.status
    if payload.severity is not None:
        fields["severity"] = payload.severity
    if payload.acknowledged_on is not None:
        fields["acknowledged_on"] = payload.acknowledged_on
    if payload.resolved_on is not None:
        fields["resolved_on"] = payload.resolved_on
    if payload.cost_vnd is not None:
        fields["cost_vnd"] = payload.cost_vnd
    if payload.paid_by is not None:
        fields["paid_by"] = payload.paid_by
    if payload.description is not None:
        fields["description"] = payload.description

    if not fields:
        raise HTTPException(400, "no_fields_to_update")

    # Auto-stamp resolved_on when status flips to terminal state and
    # caller didn't provide a date explicitly. Acceptable convention
    # in the same PATCH; saves a follow-up request.
    if (
        payload.status in ("resolved", "rejected", "abandoned")
        and payload.resolved_on is None
    ):
        fields["resolved_on"] = date.today()

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = str(claim_id)

    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text(
                f"""
                UPDATE warranty_claims
                SET {set_clause}, updated_at = NOW()
                WHERE id = :id
                """
            ),
            fields,
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "claim_not_found")

    return ok({"id": str(claim_id)})


# ---------- Summary KPI ----------


@router.get("/projects/{project_id}/summary")
async def project_summary(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """KPI tile data for the project's warranty dashboard.

    Returns:
      * active_count — warranties with status='active' + expiry_date in future
      * expiring_30 / expiring_90 — within 30 / 90 days
      * open_claims — claims with status IN ('open','investigating',
        'vendor_notified','in_repair')
      * vendor_covered_vnd — sum of cost_vnd on resolved claims where
        vendor paid (proves warranty value to the customer)
    """
    today = date.today()
    async with TenantAwareSession(auth.organization_id) as session:
        warranty_row = (
            await session.execute(
                text(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE status = 'active'
                              AND (expiry_date IS NULL OR expiry_date >= :today)
                        ) AS active_count,
                        COUNT(*) FILTER (
                            WHERE status = 'active'
                              AND expiry_date IS NOT NULL
                              AND expiry_date BETWEEN :today AND :horizon_30
                        ) AS expiring_30,
                        COUNT(*) FILTER (
                            WHERE status = 'active'
                              AND expiry_date IS NOT NULL
                              AND expiry_date BETWEEN :today AND :horizon_90
                        ) AS expiring_90
                    FROM warranty_items
                    WHERE project_id = :pid
                    """
                ),
                {
                    "pid": str(project_id),
                    "today": today,
                    "horizon_30": today + timedelta(days=30),
                    "horizon_90": today + timedelta(days=90),
                },
            )
        ).mappings().one()

        claims_row = (
            await session.execute(
                text(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE c.status IN ('open', 'investigating', 'vendor_notified', 'in_repair')
                        ) AS open_count,
                        COUNT(*) FILTER (WHERE c.status = 'resolved') AS resolved_count,
                        COUNT(*) FILTER (WHERE c.status = 'rejected') AS rejected_count,
                        COALESCE(SUM(c.cost_vnd) FILTER (
                            WHERE c.status = 'resolved' AND c.paid_by = 'vendor_covered'
                        ), 0)::bigint AS vendor_covered_vnd,
                        COALESCE(SUM(c.cost_vnd) FILTER (
                            WHERE c.status = 'resolved' AND c.paid_by = 'contractor_absorbed'
                        ), 0)::bigint AS contractor_absorbed_vnd
                    FROM warranty_claims c
                    JOIN warranty_items w ON w.id = c.warranty_item_id
                    WHERE w.project_id = :pid
                    """
                ),
                {"pid": str(project_id)},
            )
        ).mappings().one()

    return ok(
        {
            "active_count": int(warranty_row["active_count"] or 0),
            "expiring_30": int(warranty_row["expiring_30"] or 0),
            "expiring_90": int(warranty_row["expiring_90"] or 0),
            "open_claims": int(claims_row["open_count"] or 0),
            "resolved_claims": int(claims_row["resolved_count"] or 0),
            "rejected_claims": int(claims_row["rejected_count"] or 0),
            "vendor_covered_vnd": int(claims_row["vendor_covered_vnd"] or 0),
            "contractor_absorbed_vnd": int(claims_row["contractor_absorbed_vnd"] or 0),
        }
    )
