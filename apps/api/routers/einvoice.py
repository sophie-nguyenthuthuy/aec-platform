"""EINVOICE router — HĐĐT endpoints (NĐ 123/2020 + TT 78/2021).

Lifecycle:

  draft → issued → submitted_gdt → accepted_gdt
                                ↘─ rejected_gdt

`issued` is the local "I've finalized this" step; `submitted_gdt`
fires the call to the e-invoice service (stubbed); `accepted_gdt`
lands via the GDT callback POST. Cancellation is allowed up to 24h
post-issue per NĐ 123 Art. 19; after that, an adjustment invoice
(`adjustment_for_id`) is the only legal correction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import AdminSessionFactory, TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.einvoice import (
    CancelInvoicePayload,
    EInvoice,
    EInvoiceCreate,
    EInvoiceLine,
    EInvoiceUpdate,
    GdtCallback,
    GdtStatus,
    InvoiceDetail,
    InvoiceDirection,
    InvoiceListFilters,
    InvoiceStatus,
    InvoiceSummary,
    IssueInvoicePayload,
    MstInfo,
    MstValidateRequest,
    SubmitGdtPayload,
    build_vat_breakdown,
    compute_line,
)

router = APIRouter(prefix="/api/v1/einvoice", tags=["einvoice"])

import json  # noqa: E402  (kept here near use)


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=_default_serializer, ensure_ascii=False)


def _default_serializer(value: Any) -> Any:
    from datetime import date

    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not serializable: {type(value)}")


# ---------- Invoices ----------


@router.post("/invoices", status_code=status.HTTP_201_CREATED)
async def create_invoice(
    payload: EInvoiceCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Create an HĐĐT in `draft`, lines included.

    Totals are computed server-side from the line table — the caller
    can't override them. This keeps the API resistant to client
    misconfiguration that would otherwise produce an XML whose totals
    disagree with the line items (a hard reject at the GDT).
    """
    invoice_id = uuid4()
    now = datetime.now(UTC)

    # Pre-compute lines + totals so the INSERTs match what we promise.
    line_specs: list[dict[str, Any]] = []
    breakdown_input: list[tuple[int, int, Decimal | None]] = []
    subtotal = 0
    vat_total = 0
    for ln in payload.lines:
        line_total, vat_amount = compute_line(ln.qty, ln.unit_price, ln.discount_pct, ln.vat_rate)
        line_specs.append(
            {
                "id": str(uuid4()),
                "sort_order": ln.sort_order,
                "description": ln.description,
                "item_code": ln.item_code,
                "unit": ln.unit,
                "qty": ln.qty,
                "unit_price": ln.unit_price,
                "discount_pct": ln.discount_pct,
                "line_total": line_total,
                "vat_rate": ln.vat_rate,
                "vat_amount": vat_amount,
            }
        )
        breakdown_input.append((line_total, vat_amount, ln.vat_rate))
        subtotal += line_total
        vat_total += vat_amount
    breakdown = build_vat_breakdown(breakdown_input)
    total = subtotal + vat_total

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO einvoices
                      (id, organization_id, project_id, direction, invoice_no,
                       template_no, serial_no, status, issuer_mst, issuer_name,
                       issuer_address, issuer_bank_account, buyer_mst, buyer_name,
                       buyer_address, buyer_email, issue_date, due_date,
                       currency, exchange_rate,
                       subtotal, vat_breakdown, vat_total, total,
                       payment_method, payment_reference, notes,
                       created_by, created_at, updated_at)
                    VALUES
                      (:id, :org, :project_id, :direction, :invoice_no,
                       :template_no, :serial_no, 'draft', :issuer_mst, :issuer_name,
                       :issuer_address, :issuer_bank_account, :buyer_mst, :buyer_name,
                       :buyer_address, :buyer_email, :issue_date, :due_date,
                       :currency, :exchange_rate,
                       :subtotal, CAST(:vat_breakdown AS jsonb), :vat_total, :total,
                       :payment_method, :payment_reference, :notes,
                       :created_by, :now, :now)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(invoice_id),
                        "org": str(auth.organization_id),
                        "project_id": str(payload.project_id) if payload.project_id else None,
                        "direction": payload.direction.value,
                        "invoice_no": payload.invoice_no,
                        "template_no": payload.template_no,
                        "serial_no": payload.serial_no,
                        "issuer_mst": payload.issuer_mst,
                        "issuer_name": payload.issuer_name,
                        "issuer_address": payload.issuer_address,
                        "issuer_bank_account": payload.issuer_bank_account,
                        "buyer_mst": payload.buyer_mst,
                        "buyer_name": payload.buyer_name,
                        "buyer_address": payload.buyer_address,
                        "buyer_email": payload.buyer_email,
                        "issue_date": payload.issue_date,
                        "due_date": payload.due_date,
                        "currency": payload.currency,
                        "exchange_rate": payload.exchange_rate,
                        "subtotal": subtotal,
                        "vat_breakdown": _json(breakdown),
                        "vat_total": vat_total,
                        "total": total,
                        "payment_method": payload.payment_method,
                        "payment_reference": payload.payment_reference,
                        "notes": payload.notes,
                        "created_by": str(auth.user_id),
                        "now": now,
                    },
                )
            )
            .mappings()
            .one()
        )

        for spec in line_specs:
            await session.execute(
                text(
                    """
                INSERT INTO einvoice_lines
                  (id, organization_id, invoice_id, sort_order, description, item_code,
                   unit, qty, unit_price, discount_pct, line_total, vat_rate, vat_amount)
                VALUES
                  (:id, :org, :invoice_id, :sort_order, :description, :item_code,
                   :unit, :qty, :unit_price, :discount_pct, :line_total, :vat_rate, :vat_amount)
                """
                ),
                {
                    **spec,
                    "org": str(auth.organization_id),
                    "invoice_id": str(invoice_id),
                },
            )

    return ok(EInvoice.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/invoices")
async def list_invoices(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    direction: InvoiceDirection | None = None,
    inv_status: InvoiceStatus | None = Query(None, alias="status"),
    buyer_mst: str | None = None,
    issuer_mst: str | None = None,
    issued_year: int | None = Query(None, ge=2000, le=2100),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = InvoiceListFilters(
        project_id=project_id,
        direction=direction,
        status=inv_status,
        buyer_mst=buyer_mst,
        issuer_mst=issuer_mst,
        issued_year=issued_year,
        limit=limit,
        offset=offset,
    )
    where, params = _invoice_where(filters, auth.organization_id)
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT i.*,
                      COALESCE(l.line_count, 0)::int AS line_count
                    FROM einvoices i
                    LEFT JOIN (
                      SELECT invoice_id, COUNT(*) AS line_count
                      FROM einvoice_lines GROUP BY invoice_id
                    ) l ON l.invoice_id = i.id
                    WHERE {where}
                    ORDER BY i.issue_date DESC, i.created_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                    ),
                    {**params, "limit": limit, "offset": offset},
                )
            )
            .mappings()
            .all()
        )
        total = (await session.execute(text(f"SELECT COUNT(*) FROM einvoices i WHERE {where}"), params)).scalar_one()

    items = [InvoiceSummary.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.get("/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        inv = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM einvoices
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(invoice_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if inv is None:
            raise HTTPException(status_code=404, detail="invoice_not_found")

        lines = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM einvoice_lines
                    WHERE invoice_id = :id
                    ORDER BY sort_order ASC, created_at ASC
                    """
                    ),
                    {"id": str(invoice_id)},
                )
            )
            .mappings()
            .all()
        )

    detail = InvoiceDetail.model_validate(
        {
            **dict(inv),
            "lines": [EInvoiceLine.model_validate(dict(line)) for line in lines],
        }
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/invoices/{invoice_id}")
async def update_invoice(
    invoice_id: UUID,
    payload: EInvoiceUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Edit a draft invoice. Once issued (gdt_code set / status moved
    past `draft`), the only legal correction is an adjustment invoice."""
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(invoice_id), "org": str(auth.organization_id)}
    for col, val in (
        ("issue_date", payload.issue_date),
        ("due_date", payload.due_date),
        ("buyer_mst", payload.buyer_mst),
        ("buyer_name", payload.buyer_name),
        ("buyer_address", payload.buyer_address),
        ("buyer_email", payload.buyer_email),
        ("payment_method", payload.payment_method),
        ("payment_reference", payload.payment_reference),
        ("notes", payload.notes),
    ):
        if val is None:
            continue
        assigns.append(f"{col} = :{col}")
        params[col] = val
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        cur_status = (
            await session.execute(
                text(
                    """
                SELECT status FROM einvoices
                WHERE id = :id AND organization_id = :org
                """
                ),
                {"id": str(invoice_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if cur_status is None:
            raise HTTPException(status_code=404, detail="invoice_not_found")
        if InvoiceStatus(cur_status) != InvoiceStatus.draft:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "invoice_not_draft",
                    "message": (
                        "Hoá đơn đã phát hành — không sửa được. Phát hành hoá đơn điều chỉnh để xử lý sai sót."
                    ),
                },
            )

        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE einvoices SET {", ".join(assigns)}
                    WHERE id = :id AND organization_id = :org
                    RETURNING *
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .one()
        )
    return ok(EInvoice.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/invoices/{invoice_id}/issue")
async def issue_invoice(
    invoice_id: UUID,
    payload: IssueInvoicePayload,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Move draft → issued.

    Pre-conditions:
      * At least one line.
      * `direction = issued` only — received invoices can't be "issued"
        (they're imported as already-issued from a supplier).
    """
    _ = payload  # reserved for future cover-note metadata
    async with TenantAwareSession(auth.organization_id) as session:
        inv = (
            (
                await session.execute(
                    text(
                        """
                    SELECT direction, status FROM einvoices
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(invoice_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if inv is None:
            raise HTTPException(status_code=404, detail="invoice_not_found")
        if InvoiceStatus(inv["status"]) != InvoiceStatus.draft:
            raise HTTPException(status_code=409, detail="invoice_not_draft")
        if InvoiceDirection(inv["direction"]) != InvoiceDirection.issued:
            raise HTTPException(
                status_code=422,
                detail="only_outbound_invoices_can_be_issued",
            )

        line_count = (
            await session.execute(
                text("SELECT COUNT(*) FROM einvoice_lines WHERE invoice_id = :id"),
                {"id": str(invoice_id)},
            )
        ).scalar_one()
        if int(line_count) == 0:
            raise HTTPException(status_code=422, detail="invoice_has_no_lines")

        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE einvoices SET status = 'issued', updated_at = NOW()
                    WHERE id = :id
                    RETURNING *
                    """
                    ),
                    {"id": str(invoice_id)},
                )
            )
            .mappings()
            .one()
        )
    return ok(EInvoice.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/invoices/{invoice_id}/submit-gdt")
async def submit_to_gdt(
    invoice_id: UUID,
    payload: SubmitGdtPayload,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Send to the GDT e-invoice service.

    Stub: this just flips status + records the timestamp. Production
    wires `services.gdt_einvoice.submit()` which POSTs the signed
    XML to the GDT endpoint and returns the request id. The async
    accept/reject comes back via the `/gdt/callback` endpoint below.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE einvoices SET
                      status = 'submitted_gdt',
                      gdt_submitted_at = NOW(),
                      xml_file_id = COALESCE(:xml_file_id, xml_file_id),
                      updated_at = NOW()
                    WHERE id = :id
                      AND organization_id = :org
                      AND status = 'issued'
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(invoice_id),
                        "org": str(auth.organization_id),
                        "xml_file_id": str(payload.xml_file_id) if payload.xml_file_id else None,
                    },
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(
                status_code=409,
                detail="invoice_must_be_issued_before_gdt_submit",
            )
    return ok(EInvoice.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/invoices/{invoice_id}/gdt-callback")
async def gdt_callback(
    invoice_id: UUID,
    payload: GdtCallback,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Apply the GDT accept/reject decision.

    In prod this is wired to a webhook from the e-invoice service; the
    payload travels with a service token, not the user JWT. Here we
    keep it on the user-auth lane for simplicity — a future iteration
    will move it to `routers.webhooks` with a service-token check.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        if payload.accepted:
            row = (
                (
                    await session.execute(
                        text(
                            """
                        UPDATE einvoices SET
                          status = 'accepted_gdt',
                          gdt_code = :gdt_code,
                          gdt_accepted_at = NOW(),
                          updated_at = NOW()
                        WHERE id = :id AND organization_id = :org
                        RETURNING *
                        """
                        ),
                        {
                            "id": str(invoice_id),
                            "org": str(auth.organization_id),
                            "gdt_code": payload.gdt_code,
                        },
                    )
                )
                .mappings()
                .first()
            )
        else:
            row = (
                (
                    await session.execute(
                        text(
                            """
                        UPDATE einvoices SET
                          status = 'rejected_gdt',
                          gdt_rejection_reason = :reason,
                          updated_at = NOW()
                        WHERE id = :id AND organization_id = :org
                        RETURNING *
                        """
                        ),
                        {
                            "id": str(invoice_id),
                            "org": str(auth.organization_id),
                            "reason": payload.rejection_reason,
                        },
                    )
                )
                .mappings()
                .first()
            )
    if row is None:
        raise HTTPException(status_code=404, detail="invoice_not_found")
    return ok(EInvoice.model_validate(dict(row)).model_dump(mode="json"))


@router.post("/invoices/{invoice_id}/cancel")
async def cancel_invoice(
    invoice_id: UUID,
    payload: CancelInvoicePayload,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Cancel an invoice.

    NĐ 123/2020 Art. 19 only allows free cancellation within 24h of
    issue and before any tax declaration period closes. Past that, the
    only fix is an adjustment invoice. We enforce the 24h window for
    simplicity — period-close is out of scope for the platform.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        inv = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, status, gdt_accepted_at, issue_date
                    FROM einvoices
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(invoice_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if inv is None:
            raise HTTPException(status_code=404, detail="invoice_not_found")
        cur_status = InvoiceStatus(inv["status"])
        if cur_status == InvoiceStatus.cancelled:
            raise HTTPException(status_code=409, detail="invoice_already_cancelled")
        # Past-24h gate only fires for GDT-accepted invoices.
        if inv["gdt_accepted_at"] is not None:
            window_end = inv["gdt_accepted_at"] + timedelta(hours=24)
            if datetime.now(UTC) > window_end:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "cancel_window_closed",
                        "message": ("Đã quá 24h kể từ khi GDT chấp thuận — chỉ có thể lập hoá đơn điều chỉnh."),
                    },
                )

        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE einvoices SET
                      status = 'cancelled',
                      adjustment_for_id = :replacement_id,
                      adjustment_reason = :reason,
                      updated_at = NOW()
                    WHERE id = :id
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(invoice_id),
                        "replacement_id": str(payload.replacement_invoice_id)
                        if payload.replacement_invoice_id
                        else None,
                        "reason": payload.reason,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(EInvoice.model_validate(dict(row)).model_dump(mode="json"))


# ---------- MST validation ----------


@router.post("/mst/validate")
async def validate_mst_endpoint(
    payload: MstValidateRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Validate a MST against the Tổng cục Thuế cache.

    Cache miss → would call the GDT lookup service in prod (stubbed
    here: returns `not_found` so callers can detect a stale MST and
    require manual confirmation).

    Uses AdminSession because the cache is global (no
    organization_id) — sharing it across tenants avoids hammering
    GDT for the same MST.
    """
    async with AdminSessionFactory() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM tax_id_validations
                    WHERE mst = :mst
                    """
                    ),
                    {"mst": payload.mst},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            # Stub: would call GDT. Persist a not_found row so a UI can
            # show "we tried, no record yet" without re-hammering on
            # subsequent calls inside the cache window.
            new_id = str(uuid4())
            row_inserted = (
                (
                    await session.execute(
                        text(
                            """
                        INSERT INTO tax_id_validations
                          (id, mst, gdt_status, last_checked_at, raw_response)
                        VALUES
                          (:id, :mst, 'not_found', NOW(), CAST('{}' AS jsonb))
                        ON CONFLICT (mst) DO UPDATE SET last_checked_at = NOW()
                        RETURNING *
                        """
                        ),
                        {"id": new_id, "mst": payload.mst},
                    )
                )
                .mappings()
                .one()
            )
            return ok(MstInfo.model_validate(dict(row_inserted)).model_dump(mode="json"))

    _ = auth  # auth required, but read is global by design
    return ok(MstInfo.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/mst/{mst}")
async def get_mst(
    mst: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Read cached MST info without triggering a re-check."""
    _ = auth
    async with AdminSessionFactory() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM tax_id_validations WHERE mst = :mst
                    """
                    ),
                    {"mst": mst},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        # Surface the unknown state explicitly rather than 404 so the
        # UI can render a "Validate now" CTA.
        return ok(
            MstInfo(
                mst=mst,
                gdt_status=GdtStatus.not_found,
                last_checked_at=datetime.now(UTC),
            ).model_dump(mode="json")
        )
    return ok(MstInfo.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Helpers ----------


def _invoice_where(f: InvoiceListFilters, org_id: UUID) -> tuple[str, dict[str, Any]]:
    clauses = ["i.organization_id = :org"]
    params: dict[str, Any] = {"org": str(org_id)}
    if f.project_id:
        clauses.append("i.project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.direction:
        clauses.append("i.direction = :direction")
        params["direction"] = f.direction.value
    if f.status:
        clauses.append("i.status = :status")
        params["status"] = f.status.value
    if f.buyer_mst:
        clauses.append("i.buyer_mst = :buyer_mst")
        params["buyer_mst"] = f.buyer_mst
    if f.issuer_mst:
        clauses.append("i.issuer_mst = :issuer_mst")
        params["issuer_mst"] = f.issuer_mst
    if f.issued_year:
        clauses.append("EXTRACT(YEAR FROM i.issue_date) = :year")
        params["year"] = f.issued_year
    return " AND ".join(clauses), params


__all__ = ["router"]
