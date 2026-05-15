"""CashFlow — Dòng tiền dự án.

Endpoints:
  * GET    /api/v1/cashflow/projects/{project_id}/entries
  * POST   /api/v1/cashflow/projects/{project_id}/entries
  * PATCH  /api/v1/cashflow/entries/{entry_id}
  * DELETE /api/v1/cashflow/entries/{entry_id}
  * POST   /api/v1/cashflow/entries/{entry_id}/actuals  — record payment
  * GET    /api/v1/cashflow/projects/{project_id}/forecast — monthly net + cumulative

All endpoints are member-readable / admin-writable (PMs see the
cashflow; only owner/admin can edit entries to prevent accidental
forecast drift from junior staff).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from core.envelope import ok
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role

router = APIRouter(prefix="/api/v1/cashflow", tags=["cashflow"])


# ---------- Schemas ----------


class CashflowEntryCreate(BaseModel):
    kind: Literal["inflow", "outflow"]
    label: str = Field(min_length=2, max_length=200)
    amount_vnd: int = Field(ge=0)
    expected_date: date
    milestone_id: UUID | None = None
    supplier_id: UUID | None = None
    status: Literal[
        "planned", "committed", "invoiced", "paid", "overdue", "cancelled"
    ] = "planned"
    notes: str | None = Field(default=None, max_length=2000)


class CashflowEntryUpdate(BaseModel):
    """All fields optional; only present fields are PATCHed."""
    label: str | None = Field(default=None, min_length=2, max_length=200)
    amount_vnd: int | None = Field(default=None, ge=0)
    expected_date: date | None = None
    status: Literal[
        "planned", "committed", "invoiced", "paid", "overdue", "cancelled"
    ] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ActualCreate(BaseModel):
    amount_vnd: int = Field(ge=0)
    paid_on: date
    reference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class CashflowEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    label: str
    amount_vnd: int
    expected_date: date
    status: str
    milestone_id: UUID | None
    supplier_id: UUID | None
    notes: str | None
    paid_actual_vnd: int  # SUM of cashflow_actuals on this entry
    created_at: datetime


# ---------- List + create ----------


@router.get("/projects/{project_id}/entries")
async def list_entries(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Per-project cashflow entries with cumulative actual paid.

    Joins `cashflow_actuals` to surface `paid_actual_vnd` inline so
    the UI doesn't need a second query per row.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        e.id, e.kind, e.label, e.amount_vnd, e.expected_date,
                        e.status, e.milestone_id, e.supplier_id, e.notes,
                        e.created_at,
                        COALESCE(SUM(a.amount_vnd), 0) AS paid_actual_vnd
                    FROM cashflow_entries e
                    LEFT JOIN cashflow_actuals a ON a.entry_id = e.id
                    WHERE e.project_id = :pid
                    GROUP BY e.id
                    ORDER BY e.expected_date ASC, e.created_at ASC
                    """
                ),
                {"pid": str(project_id)},
            )
        ).mappings().all()

    return ok(
        {
            "entries": [
                {
                    "id": str(r["id"]),
                    "kind": r["kind"],
                    "label": r["label"],
                    "amount_vnd": int(r["amount_vnd"]),
                    "expected_date": r["expected_date"].isoformat(),
                    "status": r["status"],
                    "milestone_id": str(r["milestone_id"]) if r["milestone_id"] else None,
                    "supplier_id": str(r["supplier_id"]) if r["supplier_id"] else None,
                    "notes": r["notes"],
                    "paid_actual_vnd": int(r["paid_actual_vnd"]),
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ]
        }
    )


@router.post(
    "/projects/{project_id}/entries",
    status_code=status.HTTP_201_CREATED,
)
async def create_entry(
    project_id: UUID,
    payload: CashflowEntryCreate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """Create one inflow or outflow.

    Admin/owner only — adding cashflow entries influences executive
    forecasts; gate accordingly. PMs can see the forecast but
    not modify it.
    """
    entry_id = uuid4()
    async with TenantAwareSession(auth.organization_id) as session:
        await session.execute(
            text(
                """
                INSERT INTO cashflow_entries
                    (id, organization_id, project_id, kind, label,
                     amount_vnd, expected_date, milestone_id, supplier_id,
                     status, notes, created_by)
                VALUES (:id, :org, :pid, :kind, :label,
                        :amt, :date, :ms, :sup,
                        :st, :notes, :uid)
                """
            ),
            {
                "id": str(entry_id),
                "org": str(auth.organization_id),
                "pid": str(project_id),
                "kind": payload.kind,
                "label": payload.label,
                "amt": payload.amount_vnd,
                "date": payload.expected_date,
                "ms": str(payload.milestone_id) if payload.milestone_id else None,
                "sup": str(payload.supplier_id) if payload.supplier_id else None,
                "st": payload.status,
                "notes": payload.notes,
                "uid": str(auth.user_id),
            },
        )
        await session.commit()

    return ok({"id": str(entry_id)})


@router.patch("/entries/{entry_id}")
async def update_entry(
    entry_id: UUID,
    payload: CashflowEntryUpdate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """Patch any subset of mutable fields."""
    fields: dict[str, Any] = {}
    if payload.label is not None:
        fields["label"] = payload.label
    if payload.amount_vnd is not None:
        fields["amount_vnd"] = payload.amount_vnd
    if payload.expected_date is not None:
        fields["expected_date"] = payload.expected_date
    if payload.status is not None:
        fields["status"] = payload.status
    if payload.notes is not None:
        fields["notes"] = payload.notes
    if not fields:
        raise HTTPException(400, "no_fields_to_update")

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = str(entry_id)

    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text(
                f"""
                UPDATE cashflow_entries
                SET {set_clause}, updated_at = NOW()
                WHERE id = :id
                """
            ),
            fields,
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "entry_not_found")

    return ok({"id": str(entry_id)})


@router.delete(
    "/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_entry(
    entry_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.OWNER))],
):
    """Hard delete. Owner-only — deletion is irreversible and affects
    historical forecast accuracy. To "soft cancel" an entry, set
    status='cancelled' via PATCH."""
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text("DELETE FROM cashflow_entries WHERE id = :id"),
            {"id": str(entry_id)},
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "entry_not_found")


# ---------- Actual payments ----------


@router.post(
    "/entries/{entry_id}/actuals",
    status_code=status.HTTP_201_CREATED,
)
async def record_actual(
    entry_id: UUID,
    payload: ActualCreate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """Record a real payment against an entry.

    Side effect: when SUM(actuals.amount) >= entry.amount_vnd, the
    entry's status auto-flips to 'paid'. Partial payments leave the
    status alone (still 'invoiced' or whatever).
    """
    async with TenantAwareSession(auth.organization_id) as session:
        # Verify entry exists + capture expected amount.
        entry_row = (
            await session.execute(
                text(
                    "SELECT amount_vnd, status FROM cashflow_entries WHERE id = :id"
                ),
                {"id": str(entry_id)},
            )
        ).mappings().one_or_none()
        if entry_row is None:
            raise HTTPException(404, "entry_not_found")

        actual_id = uuid4()
        await session.execute(
            text(
                """
                INSERT INTO cashflow_actuals
                    (id, organization_id, entry_id, amount_vnd,
                     paid_on, reference, notes, recorded_by)
                VALUES (:id, :org, :entry, :amt,
                        :paid_on, :ref, :notes, :uid)
                """
            ),
            {
                "id": str(actual_id),
                "org": str(auth.organization_id),
                "entry": str(entry_id),
                "amt": payload.amount_vnd,
                "paid_on": payload.paid_on,
                "ref": payload.reference,
                "notes": payload.notes,
                "uid": str(auth.user_id),
            },
        )

        # Compute new running total + auto-flip status if fully paid.
        running = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(SUM(amount_vnd), 0) AS total
                    FROM cashflow_actuals WHERE entry_id = :entry
                    """
                ),
                {"entry": str(entry_id)},
            )
        ).scalar_one()
        if int(running) >= int(entry_row["amount_vnd"]):
            await session.execute(
                text(
                    "UPDATE cashflow_entries SET status = 'paid', updated_at = NOW() WHERE id = :id"
                ),
                {"id": str(entry_id)},
            )

        await session.commit()

    return ok({"id": str(actual_id), "running_total_vnd": int(running)})


# ---------- Forecast ----------


@router.get("/projects/{project_id}/forecast")
async def project_forecast(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    months: int = 12,
):
    """Monthly cashflow forecast + cumulative net.

    Aggregates by `date_trunc('month', expected_date)`. Returns
    `inflow_vnd`, `outflow_vnd`, `net_vnd`, `cumulative_vnd` per
    month from current month forward.

    Includes a `summary` block with totals + alerts (e.g. "tháng 4
    sẽ âm 2 tỷ đồng — chuẩn bị vốn lưu động").
    """
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        date_trunc('month', expected_date) AS month,
                        SUM(amount_vnd) FILTER (WHERE kind = 'inflow')::bigint AS inflow,
                        SUM(amount_vnd) FILTER (WHERE kind = 'outflow')::bigint AS outflow
                    FROM cashflow_entries
                    WHERE project_id = :pid
                      AND status != 'cancelled'
                    GROUP BY date_trunc('month', expected_date)
                    ORDER BY 1 ASC
                    LIMIT :months
                    """
                ),
                {"pid": str(project_id), "months": months},
            )
        ).mappings().all()

    series: list[dict[str, Any]] = []
    cumulative = 0
    for r in rows:
        inflow = int(r["inflow"] or 0)
        outflow = int(r["outflow"] or 0)
        net = inflow - outflow
        cumulative += net
        series.append(
            {
                "month": r["month"].date().isoformat(),
                "inflow_vnd": inflow,
                "outflow_vnd": outflow,
                "net_vnd": net,
                "cumulative_vnd": cumulative,
            }
        )

    # Alerts: any month where cumulative goes negative — likely working-
    # capital crunch. Highlight to PM.
    deficit_months = [s["month"] for s in series if s["cumulative_vnd"] < 0]

    total_inflow = sum(s["inflow_vnd"] for s in series)
    total_outflow = sum(s["outflow_vnd"] for s in series)

    return ok(
        {
            "series": series,
            "summary": {
                "total_inflow_vnd": total_inflow,
                "total_outflow_vnd": total_outflow,
                "total_net_vnd": total_inflow - total_outflow,
                "deficit_months": deficit_months,
                "horizon_months": len(series),
            },
        }
    )
