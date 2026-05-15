"""EquipmentRental — Máy thi công thuê.

Endpoints:
  * POST   /api/v1/equipment/projects/{id}/rentals — tạo hợp đồng thuê
  * GET    /api/v1/equipment/projects/{id}/rentals — list
  * PATCH  /api/v1/equipment/rentals/{id} — cập nhật contract
  * POST   /api/v1/equipment/rentals/{id}/logs — daily usage log
  * GET    /api/v1/equipment/rentals/{id}/logs — nhật ký
  * POST   /api/v1/equipment/rentals/{id}/invoices — đối chiếu hoá đơn
  * GET    /api/v1/equipment/projects/{id}/utilization — KPI usage %
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from core.envelope import ok
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role

router = APIRouter(prefix="/api/v1/equipment", tags=["equipment"])


EQUIPMENT_TYPES = [
    "crane",  # cẩu tháp / cẩu bánh
    "excavator",  # máy đào / máy xúc
    "concrete_pump",  # máy bơm bê tông
    "loader",  # máy cuộn / máy nâng
    "generator",  # máy phát điện
    "compressor",  # máy nén khí
    "scaffolding",  # giàn giáo (tính m²/ngày thay vì máy/ngày)
    "formwork",  # cốp pha
    "truck",  # xe tải / xe ben
    "lift",  # vận thăng
    "other",
]


# ---------- Schemas ----------


class RentalCreate(BaseModel):
    equipment_type: str = Field(min_length=2, max_length=50)
    equipment_name: str = Field(min_length=2, max_length=200)
    equipment_serial: str | None = Field(default=None, max_length=100)
    supplier_name: str = Field(min_length=2, max_length=200)
    supplier_phone: str | None = Field(default=None, max_length=20)
    contract_number: str | None = Field(default=None, max_length=100)
    rate_vnd_per_day: int = Field(ge=0)
    rate_tier: dict[str, Any] | None = None
    planned_start: date
    planned_finish: date
    notes: str | None = Field(default=None, max_length=2000)


class RentalUpdate(BaseModel):
    actual_start: date | None = None
    actual_finish: date | None = None
    status: Literal["planned", "active", "returned", "cancelled"] | None = None
    notes: str | None = None


class LogCreate(BaseModel):
    log_date: date
    usage_state: Literal["used", "idle", "maintenance", "off"]
    hours_operated: Decimal | None = Field(default=None, ge=0, le=24)
    operator_name: str | None = Field(default=None, max_length=200)
    operator_phone: str | None = Field(default=None, max_length=20)
    fuel_cost_vnd: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)


class InvoiceReconcile(BaseModel):
    invoice_number: str = Field(min_length=1, max_length=100)
    period_start: date
    period_end: date
    billable_days_claimed: int = Field(ge=0)
    amount_vnd_claimed: int = Field(ge=0)


# ---------- Rental contracts ----------


@router.post(
    "/projects/{project_id}/rentals",
    status_code=status.HTTP_201_CREATED,
)
async def create_rental(
    project_id: UUID,
    payload: RentalCreate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.MEMBER))],
):
    """Create a new equipment rental contract.

    Member-writable — site supervisor often books the rental + records
    contract in app on the spot. Status defaults to 'planned' until
    actual_start is set (PATCH).
    """
    rental_id = uuid4()
    async with TenantAwareSession(auth.organization_id) as session:
        await session.execute(
            text(
                """
                INSERT INTO equipment_rentals
                    (id, organization_id, project_id, equipment_type, equipment_name,
                     equipment_serial, supplier_name, supplier_phone, contract_number,
                     rate_vnd_per_day, rate_tier, planned_start, planned_finish,
                     status, notes, created_by)
                VALUES (:id, :org, :pid, :etype, :ename, :serial,
                        :sname, :sphone, :cnum, :rate, CAST(:tier AS jsonb),
                        :pstart, :pend, 'planned', :notes, :uid)
                """
            ),
            {
                "id": str(rental_id),
                "org": str(auth.organization_id),
                "pid": str(project_id),
                "etype": payload.equipment_type,
                "ename": payload.equipment_name,
                "serial": payload.equipment_serial,
                "sname": payload.supplier_name,
                "sphone": payload.supplier_phone,
                "cnum": payload.contract_number,
                "rate": payload.rate_vnd_per_day,
                "tier": __import__("json").dumps(payload.rate_tier)
                if payload.rate_tier
                else None,
                "pstart": payload.planned_start,
                "pend": payload.planned_finish,
                "notes": payload.notes,
                "uid": str(auth.user_id),
            },
        )
        await session.commit()
    return ok({"id": str(rental_id)})


@router.get("/projects/{project_id}/rentals")
async def list_rentals(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
):
    """List equipment rentals for a project. Filterable by status."""
    where = ["project_id = :pid"]
    params: dict[str, Any] = {"pid": str(project_id)}
    if status_filter:
        where.append("status = :st")
        params["st"] = status_filter

    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT
                        r.id, r.equipment_type, r.equipment_name, r.equipment_serial,
                        r.supplier_name, r.supplier_phone, r.contract_number,
                        r.rate_vnd_per_day, r.planned_start, r.planned_finish,
                        r.actual_start, r.actual_finish, r.status, r.notes,
                        r.created_at,
                        COUNT(l.id)::int AS log_count,
                        COUNT(l.id) FILTER (WHERE l.usage_state = 'used')::int AS used_days,
                        COUNT(l.id) FILTER (WHERE l.usage_state = 'idle')::int AS idle_days
                    FROM equipment_rentals r
                    LEFT JOIN equipment_rental_logs l ON l.rental_id = r.id
                    WHERE {' AND '.join(where)}
                    GROUP BY r.id
                    ORDER BY r.planned_start DESC, r.created_at DESC
                    """
                ),
                params,
            )
        ).mappings().all()

    return ok(
        {
            "rentals": [
                {
                    "id": str(r["id"]),
                    "equipment_type": r["equipment_type"],
                    "equipment_name": r["equipment_name"],
                    "equipment_serial": r["equipment_serial"],
                    "supplier_name": r["supplier_name"],
                    "supplier_phone": r["supplier_phone"],
                    "contract_number": r["contract_number"],
                    "rate_vnd_per_day": int(r["rate_vnd_per_day"]),
                    "planned_start": r["planned_start"].isoformat(),
                    "planned_finish": r["planned_finish"].isoformat(),
                    "actual_start": r["actual_start"].isoformat() if r["actual_start"] else None,
                    "actual_finish": r["actual_finish"].isoformat() if r["actual_finish"] else None,
                    "status": r["status"],
                    "notes": r["notes"],
                    "log_count": r["log_count"],
                    "used_days": r["used_days"],
                    "idle_days": r["idle_days"],
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ]
        }
    )


@router.patch("/rentals/{rental_id}")
async def update_rental(
    rental_id: UUID,
    payload: RentalUpdate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.MEMBER))],
):
    """Patch rental contract (actual dates, status, notes)."""
    fields: dict[str, Any] = {}
    if payload.actual_start is not None:
        fields["actual_start"] = payload.actual_start
    if payload.actual_finish is not None:
        fields["actual_finish"] = payload.actual_finish
    if payload.status is not None:
        fields["status"] = payload.status
    if payload.notes is not None:
        fields["notes"] = payload.notes
    if not fields:
        raise HTTPException(400, "no_fields_to_update")

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = str(rental_id)

    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text(
                f"""
                UPDATE equipment_rentals
                SET {set_clause}, updated_at = NOW()
                WHERE id = :id
                """
            ),
            fields,
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "rental_not_found")
    return ok({"id": str(rental_id)})


# ---------- Daily usage logs ----------


@router.post(
    "/rentals/{rental_id}/logs",
    status_code=status.HTTP_201_CREATED,
)
async def log_usage(
    rental_id: UUID,
    payload: LogCreate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.MEMBER))],
):
    """Log one day's usage for an equipment rental.

    Daily entry by site supervisor or operator-logbook. UQ(rental, date)
    prevents duplicate entries — to correct a wrong log, PATCH instead.
    """
    log_id = uuid4()
    async with TenantAwareSession(auth.organization_id) as session:
        # Verify rental exists in this org
        exists = (
            await session.execute(
                text("SELECT 1 FROM equipment_rentals WHERE id = :id"),
                {"id": str(rental_id)},
            )
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(404, "rental_not_found")

        try:
            await session.execute(
                text(
                    """
                    INSERT INTO equipment_rental_logs
                        (id, organization_id, rental_id, log_date, usage_state,
                         hours_operated, operator_name, operator_phone, fuel_cost_vnd,
                         notes, logged_by)
                    VALUES (:id, :org, :rental, :date, :state, :hours,
                            :opname, :opphone, :fuel, :notes, :uid)
                    """
                ),
                {
                    "id": str(log_id),
                    "org": str(auth.organization_id),
                    "rental": str(rental_id),
                    "date": payload.log_date,
                    "state": payload.usage_state,
                    "hours": payload.hours_operated,
                    "opname": payload.operator_name,
                    "opphone": payload.operator_phone,
                    "fuel": payload.fuel_cost_vnd,
                    "notes": payload.notes,
                    "uid": str(auth.user_id),
                },
            )
            await session.commit()
        except Exception as exc:
            msg = str(exc).lower()
            if "uq_equipment_log_rental_date" in msg or "duplicate" in msg:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "log_already_exists_for_rental_date",
                ) from exc
            raise

    return ok({"id": str(log_id)})


@router.get("/rentals/{rental_id}/logs")
async def list_logs(
    rental_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, log_date, usage_state, hours_operated,
                           operator_name, operator_phone, fuel_cost_vnd, notes,
                           created_at
                    FROM equipment_rental_logs
                    WHERE rental_id = :rid
                    ORDER BY log_date DESC
                    """
                ),
                {"rid": str(rental_id)},
            )
        ).mappings().all()

    return ok(
        {
            "logs": [
                {
                    "id": str(r["id"]),
                    "log_date": r["log_date"].isoformat(),
                    "usage_state": r["usage_state"],
                    "hours_operated": float(r["hours_operated"]) if r["hours_operated"] else None,
                    "operator_name": r["operator_name"],
                    "operator_phone": r["operator_phone"],
                    "fuel_cost_vnd": int(r["fuel_cost_vnd"]) if r["fuel_cost_vnd"] else None,
                    "notes": r["notes"],
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ]
        }
    )


# ---------- Invoice reconciliation ----------


@router.post(
    "/rentals/{rental_id}/invoices",
    status_code=status.HTTP_201_CREATED,
)
async def reconcile_invoice(
    rental_id: UUID,
    payload: InvoiceReconcile,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """Record an NCC invoice + compute variance vs our usage logs.

    Math:
      * `billable_days_per_logs` = COUNT(logs WHERE state IN ('used','idle')
                                          AND log_date BETWEEN period_start AND period_end)
      * `amount_vnd_per_logs` = billable_days_per_logs × rate_vnd_per_day
      * `variance_vnd` = amount_claimed − amount_per_logs (>0 means NCC over-bills)

    Admin-only — disputing supplier invoices is sensitive.
    """
    invoice_id = uuid4()
    async with TenantAwareSession(auth.organization_id) as session:
        rental = (
            await session.execute(
                text(
                    "SELECT rate_vnd_per_day FROM equipment_rentals WHERE id = :id"
                ),
                {"id": str(rental_id)},
            )
        ).mappings().one_or_none()
        if rental is None:
            raise HTTPException(404, "rental_not_found")
        rate = int(rental["rate_vnd_per_day"])

        # Count billable days from logs.
        billable = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM equipment_rental_logs
                    WHERE rental_id = :rid
                      AND log_date BETWEEN :ps AND :pe
                      AND usage_state IN ('used', 'idle')
                    """
                ),
                {
                    "rid": str(rental_id),
                    "ps": payload.period_start,
                    "pe": payload.period_end,
                },
            )
        ).scalar_one()
        billable_days = int(billable)
        amount_per_logs = billable_days * rate
        variance = payload.amount_vnd_claimed - amount_per_logs

        try:
            await session.execute(
                text(
                    """
                    INSERT INTO equipment_rental_invoices
                        (id, organization_id, rental_id, invoice_number,
                         period_start, period_end,
                         billable_days_claimed, amount_vnd_claimed,
                         billable_days_per_logs, amount_vnd_per_logs,
                         variance_vnd, status, reconciled_by)
                    VALUES (:id, :org, :rental, :invno, :ps, :pe,
                            :dcl, :acl, :dpl, :apl, :var,
                            'pending_review', :uid)
                    """
                ),
                {
                    "id": str(invoice_id),
                    "org": str(auth.organization_id),
                    "rental": str(rental_id),
                    "invno": payload.invoice_number,
                    "ps": payload.period_start,
                    "pe": payload.period_end,
                    "dcl": payload.billable_days_claimed,
                    "acl": payload.amount_vnd_claimed,
                    "dpl": billable_days,
                    "apl": amount_per_logs,
                    "var": variance,
                    "uid": str(auth.user_id),
                },
            )
            await session.commit()
        except Exception as exc:
            if "uq_equipment_invoice_rental_number" in str(exc).lower():
                raise HTTPException(409, "invoice_number_already_recorded") from exc
            raise

    return ok(
        {
            "id": str(invoice_id),
            "billable_days_per_logs": billable_days,
            "amount_vnd_per_logs": amount_per_logs,
            "variance_vnd": variance,
            "verdict": (
                "ok" if abs(variance) < rate else "review" if variance < 0 else "overbilled"
            ),
        }
    )


# ---------- Project-level utilization KPI ----------


@router.get("/projects/{project_id}/utilization")
async def project_utilization(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    days: Annotated[int, Query(ge=7, le=365)] = 30,
):
    """% of equipment-days spent `used` vs total `used + idle`.

    "Utilization" excludes `maintenance` + `off` from both numerator
    and denominator — those days NCC typically doesn't charge.

    Surfaces:
      * Total equipment-days in window
      * Used + idle + maintenance + off counts
      * Used / (used + idle) % — financial efficiency view ("did we
        actually use what we paid for?")
      * Top 5 idle-heavy rentals (rentals where idle > used)
    """
    until = date.today()
    since = until - timedelta(days=days - 1)

    async with TenantAwareSession(auth.organization_id) as session:
        agg = (
            await session.execute(
                text(
                    """
                    SELECT
                        COUNT(l.id)::int AS total_days,
                        COUNT(l.id) FILTER (WHERE l.usage_state = 'used')::int AS used,
                        COUNT(l.id) FILTER (WHERE l.usage_state = 'idle')::int AS idle,
                        COUNT(l.id) FILTER (WHERE l.usage_state = 'maintenance')::int AS maint,
                        COUNT(l.id) FILTER (WHERE l.usage_state = 'off')::int AS off,
                        COALESCE(SUM(l.fuel_cost_vnd), 0)::bigint AS fuel_cost
                    FROM equipment_rental_logs l
                    JOIN equipment_rentals r ON r.id = l.rental_id
                    WHERE r.project_id = :pid
                      AND l.log_date >= :since
                      AND l.log_date <= :until
                    """
                ),
                {"pid": str(project_id), "since": since, "until": until},
            )
        ).mappings().one()

        idle_heavy = (
            await session.execute(
                text(
                    """
                    SELECT
                        r.id, r.equipment_name, r.supplier_name,
                        COUNT(l.id) FILTER (WHERE l.usage_state = 'used')::int AS used,
                        COUNT(l.id) FILTER (WHERE l.usage_state = 'idle')::int AS idle,
                        r.rate_vnd_per_day
                    FROM equipment_rentals r
                    LEFT JOIN equipment_rental_logs l ON l.rental_id = r.id
                      AND l.log_date >= :since
                      AND l.log_date <= :until
                    WHERE r.project_id = :pid
                    GROUP BY r.id
                    HAVING COUNT(l.id) FILTER (WHERE l.usage_state = 'idle') >
                           COUNT(l.id) FILTER (WHERE l.usage_state = 'used')
                    ORDER BY COUNT(l.id) FILTER (WHERE l.usage_state = 'idle') DESC
                    LIMIT 5
                    """
                ),
                {"pid": str(project_id), "since": since, "until": until},
            )
        ).mappings().all()

    used = int(agg["used"])
    idle = int(agg["idle"])
    billable = used + idle
    utilization_pct = round(100.0 * used / billable, 1) if billable > 0 else 0.0

    return ok(
        {
            "window": {
                "since": since.isoformat(),
                "until": until.isoformat(),
                "days": days,
            },
            "total_equipment_days": int(agg["total_days"]),
            "used_days": used,
            "idle_days": idle,
            "maintenance_days": int(agg["maint"]),
            "off_days": int(agg["off"]),
            "billable_days": billable,
            "utilization_pct": utilization_pct,
            "total_fuel_cost_vnd": int(agg["fuel_cost"]),
            "idle_heavy_rentals": [
                {
                    "id": str(r["id"]),
                    "equipment_name": r["equipment_name"],
                    "supplier_name": r["supplier_name"],
                    "used_days": int(r["used"]),
                    "idle_days": int(r["idle"]),
                    "wasted_vnd": int(r["idle"]) * int(r["rate_vnd_per_day"]),
                }
                for r in idle_heavy
            ],
        }
    )
