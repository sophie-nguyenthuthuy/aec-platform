"""FastAPI router for CostPulse endpoints."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok, paginated
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role
from models.costpulse import BoqItem, Estimate, MaterialPrice, PriceAlert, Rfq, Supplier
from models.pulse import ChangeOrder
from schemas.costpulse import (
    AiEstimateResult,
    BoqDiffRow,
    BoqItemIn,
    BoqItemOut,
    CostBenchmarkBucket,
    CostBenchmarkResponse,
    EstimateConfidence,
    EstimateCreate,
    EstimateDetail,
    EstimateDiff,
    EstimateFromBriefRequest,
    EstimateFromDrawingsRequest,
    EstimateMethod,
    EstimateStatus,
    EstimateSummary,
    MaterialPriceOut,
    PriceHistoryPoint,
    PriceHistoryResponse,
    RfqCreate,
    RfqOut,
    RfqStatus,
    SupplierCreate,
    SupplierOut,
    UpdateBoqRequest,
)

router = APIRouter(prefix="/api/v1/costpulse", tags=["costpulse"])


# ---------- AI Estimation ----------


@router.post("/estimate/from-brief")
async def estimate_from_brief(
    payload: EstimateFromBriefRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """AI estimate from high-level project parameters (rough_order / preliminary)."""
    from ml.pipelines.costpulse import estimate_from_brief as pipeline_brief

    try:
        result: AiEstimateResult = await pipeline_brief(
            db=db,
            organization_id=auth.organization_id,
            created_by=auth.user_id,
            payload=payload,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Estimate pipeline failed: {exc}") from exc

    return ok(result.model_dump(mode="json"))


@router.post("/estimate/from-drawings")
async def estimate_from_drawings(
    payload: EstimateFromDrawingsRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """AI BOQ extraction from uploaded drawings (detailed)."""
    from ml.pipelines.costpulse import estimate_from_drawings as pipeline_drawings

    try:
        result: AiEstimateResult = await pipeline_drawings(
            db=db,
            organization_id=auth.organization_id,
            created_by=auth.user_id,
            payload=payload,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Drawing pipeline failed: {exc}") from exc

    return ok(result.model_dump(mode="json"))


# ---------- Estimates CRUD ----------


@router.get("/estimates")
async def list_estimates(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID | None = None,
    status_filter: EstimateStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    stmt = select(Estimate).where(Estimate.organization_id == auth.organization_id)
    if project_id:
        stmt = stmt.where(Estimate.project_id == project_id)
    if status_filter:
        stmt = stmt.where(Estimate.status == status_filter.value)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (await db.execute(stmt.order_by(Estimate.created_at.desc()).limit(per_page).offset((page - 1) * per_page)))
        .scalars()
        .all()
    )

    return paginated(
        [EstimateSummary.model_validate(r).model_dump(mode="json") for r in rows],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post("/estimates", status_code=status.HTTP_201_CREATED)
async def create_estimate(
    payload: EstimateCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    estimate = Estimate(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        name=payload.name,
        version=1,
        status=EstimateStatus.draft.value,
        method=payload.method.value,
        confidence=payload.confidence.value,
        created_by=auth.user_id,
    )
    db.add(estimate)
    await db.flush()

    total = _persist_items(db, estimate.id, payload.items)
    estimate.total_vnd = int(total)

    await db.commit()
    await db.refresh(estimate)

    detail = await _load_estimate_detail(db, estimate.id)
    return ok(detail.model_dump(mode="json"))


@router.get("/estimates/{estimate_id}")
async def get_estimate(
    estimate_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = (
        await db.execute(
            select(Estimate).where(
                Estimate.id == estimate_id,
                Estimate.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estimate not found")

    detail = await _load_estimate_detail(db, estimate_id)
    return ok(detail.model_dump(mode="json"))


@router.put("/estimates/{estimate_id}/boq")
async def update_boq(
    estimate_id: UUID,
    payload: UpdateBoqRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Save a new version of the BOQ.

    Each save **forks a new Estimate row** with `version = old.version + 1`
    and marks the previous one as `superseded`. The previous BOQ items
    stay attached to the previous estimate id — that's the audit trail.
    The response carries the NEW estimate id so the client can navigate
    to the latest version's URL.
    """
    estimate = await _load_writable_estimate(db, auth, estimate_id)
    # `created_by` is a users.id FK; for api-key callers `auth.user_id`
    # is actually api_keys.id and would FK-violate. Pass None for those
    # callers — the audit row above carries the real api-key actor.
    creator = None if auth.role == "api_key" else auth.user_id
    new_estimate = _supersede_and_clone(db, estimate, actor_user_id=creator)
    await db.flush()  # populate new_estimate.id without committing yet

    total = _persist_items(db, new_estimate.id, payload.items, recompute=payload.recompute_totals)
    new_estimate.total_vnd = int(total)
    await db.commit()

    detail = await _load_estimate_detail(db, new_estimate.id)
    return ok(detail.model_dump(mode="json"))


# ---------- BOQ Excel/PDF I/O ----------


# Cap on import payload size. Realistic BOQs are at most a few MB; we
# reject anything bigger so a misconfigured client can't OOM the worker
# by uploading a 1GB binary that openpyxl would try to load fully.
_MAX_BOQ_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


@router.post("/estimates/{estimate_id}/boq/import")
async def import_boq_xlsx(
    estimate_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(description="BOQ as .xlsx")],
):
    """Replace the estimate's BOQ from an uploaded Excel file.

    Same write semantics as `PUT /boq` — wipes the existing items and
    inserts the parsed ones. Approved estimates are read-only here too.
    Returns the refreshed `EstimateDetail` so the UI can re-render
    without a separate fetch.
    """
    estimate = (
        await db.execute(
            select(Estimate).where(
                Estimate.id == estimate_id,
                Estimate.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if estimate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estimate not found")
    if estimate.status == EstimateStatus.approved.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Approved estimates are read-only")

    content = await file.read()
    if len(content) > _MAX_BOQ_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"BOQ upload exceeds the {_MAX_BOQ_UPLOAD_BYTES // 1024 // 1024} MB limit.",
        )

    from services.boq_io import BoqIOError, parse_boq_xlsx

    try:
        rows = parse_boq_xlsx(content)
    except BoqIOError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # Map BoqRow → BoqItemIn (Pydantic) so we can reuse the existing
    # `_persist_items` writer + total recompute logic.
    items_in: list[BoqItemIn] = [
        BoqItemIn(
            id=None,
            parent_id=None,
            sort_order=row.sort_order,
            code=row.code,
            description=row.description,
            unit=row.unit,
            quantity=row.quantity,
            unit_price_vnd=row.unit_price_vnd,
            total_price_vnd=row.total_price_vnd,
            material_code=row.material_code,
        )
        for row in rows
    ]

    await db.execute(delete(BoqItem).where(BoqItem.estimate_id == estimate_id))
    total = _persist_items(db, estimate_id, items_in, recompute=True)
    estimate.total_vnd = int(total)

    # Audit before the commit so the audit row + BOQ rewrite land
    # atomically. `after.row_count` + `total_vnd` give the activity
    # feed enough to render "imported 47 lines, total 120M VND"
    # without dumping every row in `before`/`after`.
    from services.audit import record as record_audit

    await record_audit(
        db,
        organization_id=auth.organization_id,
        auth=auth,
        action="costpulse.boq.import",
        resource_type="estimate",
        resource_id=estimate_id,
        after={
            "filename": file.filename,
            "row_count": len(items_in),
            "total_vnd": int(total),
        },
    )

    await db.commit()

    detail = await _load_estimate_detail(db, estimate_id)
    return ok(detail.model_dump(mode="json"))


@router.get("/estimates/{estimate_id}/boq/export.xlsx")
async def export_boq_xlsx(
    estimate_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Download the estimate's BOQ as an Excel workbook."""
    rows, estimate = await _load_estimate_for_export(db, auth, estimate_id)

    from services.boq_io import render_boq_xlsx

    blob = render_boq_xlsx(rows, sheet_name=_safe_sheet_name(estimate.name))
    filename = _filename_for_export(estimate.name, ext="xlsx")
    return Response(
        content=blob,
        media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/estimates/{estimate_id}/boq/export.pdf")
async def export_boq_pdf(
    estimate_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Download the estimate's BOQ as a PDF report."""
    rows, estimate = await _load_estimate_for_export(db, auth, estimate_id)

    from services.boq_io import render_boq_pdf

    blob = render_boq_pdf(estimate.name, rows)
    filename = _filename_for_export(estimate.name, ext="pdf")
    return Response(
        content=blob,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/estimates/{estimate_id}/approve")
async def approve_estimate(
    estimate_id: UUID,
    # Approving an estimate locks in the project budget AND emits a
    # COSTPULSE → PULSE change order on variance — admin/owner only.
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    estimate = (
        await db.execute(
            select(Estimate).where(
                Estimate.id == estimate_id,
                Estimate.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if estimate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estimate not found")

    was_already_approved = estimate.status == EstimateStatus.approved.value
    estimate.status = EstimateStatus.approved.value
    estimate.approved_by = auth.user_id

    # COSTPULSE → PULSE handoff: when a revised estimate is approved for a
    # project that already had an approved baseline, emit a draft ChangeOrder
    # so the budget delta surfaces in the project's pulse feed.
    if not was_already_approved:
        await _emit_variance_change_order(db, estimate, auth.organization_id)

    await db.commit()
    await db.refresh(estimate)
    return ok(EstimateSummary.model_validate(estimate).model_dump(mode="json"))


# ---------- Prices ----------


@router.get("/prices")
async def lookup_prices(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = None,
    material_code: str | None = None,
    category: str | None = None,
    province: str | None = None,
    as_of: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Returns the latest effective price per (material_code, province) as of today or `as_of`."""
    effective = as_of or date.today()

    latest = (
        select(
            MaterialPrice.material_code,
            MaterialPrice.province,
            func.max(MaterialPrice.effective_date).label("max_date"),
        )
        .where(MaterialPrice.effective_date <= effective)
        .group_by(MaterialPrice.material_code, MaterialPrice.province)
        .subquery()
    )

    stmt = select(MaterialPrice).join(
        latest,
        and_(
            MaterialPrice.material_code == latest.c.material_code,
            MaterialPrice.province.is_not_distinct_from(latest.c.province),
            MaterialPrice.effective_date == latest.c.max_date,
        ),
    )

    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(MaterialPrice.name.ilike(like), MaterialPrice.material_code.ilike(like)))
    if material_code:
        stmt = stmt.where(MaterialPrice.material_code == material_code)
    if category:
        stmt = stmt.where(MaterialPrice.category == category)
    if province:
        stmt = stmt.where(MaterialPrice.province == province)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(MaterialPrice.name).limit(limit).offset(offset))).scalars().all()

    return paginated(
        [MaterialPriceOut.model_validate(r).model_dump(mode="json") for r in rows],
        page=(offset // limit) + 1,
        per_page=limit,
        total=total,
    )


@router.get("/prices/history/{material_code}")
async def price_history(
    material_code: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    province: str | None = None,
    lookback_days: int = Query(default=365, ge=7, le=3650),
):
    cutoff = date.today() - timedelta(days=lookback_days)
    stmt = select(MaterialPrice).where(
        MaterialPrice.material_code == material_code,
        MaterialPrice.effective_date >= cutoff,
    )
    if province:
        stmt = stmt.where(MaterialPrice.province == province)
    rows = (await db.execute(stmt.order_by(MaterialPrice.effective_date.asc()))).scalars().all()

    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No price data for material_code")

    points = [
        PriceHistoryPoint(
            effective_date=r.effective_date,
            price_vnd=r.price_vnd,
            province=r.province,
            source=r.source,  # type: ignore[arg-type]
        )
        for r in rows
    ]

    def _pct_change(days: int) -> float | None:
        if len(points) < 2:
            return None
        latest = points[-1]
        target = latest.effective_date - timedelta(days=days)
        prior = next((p for p in reversed(points[:-1]) if p.effective_date <= target), None)
        if prior is None or prior.price_vnd == 0:
            return None
        return float((latest.price_vnd - prior.price_vnd) / prior.price_vnd * 100)

    response = PriceHistoryResponse(
        material_code=material_code,
        name=rows[-1].name,
        unit=rows[-1].unit,
        points=points,
        pct_change_30d=_pct_change(30),
        pct_change_1y=_pct_change(365),
    )
    return ok(response.model_dump(mode="json"))


@router.post("/prices/override")
async def override_price(
    material_code: str,
    price_vnd: Decimal,
    province: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    name: str | None = None,
    unit: str | None = None,
    category: str | None = None,
):
    """User-submitted price override → captured as crowdsource data point."""
    existing = (
        await db.execute(
            select(MaterialPrice)
            .where(MaterialPrice.material_code == material_code)
            .order_by(MaterialPrice.effective_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    record = MaterialPrice(
        id=uuid4(),
        material_code=material_code,
        name=name or (existing.name if existing else material_code),
        unit=unit or (existing.unit if existing else "pcs"),
        category=category or (existing.category if existing else None),
        price_vnd=price_vnd,
        province=province,
        source="crowdsource",
        effective_date=date.today(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return ok(MaterialPriceOut.model_validate(record).model_dump(mode="json"))


# ---------- Suppliers ----------


@router.get("/suppliers")
async def list_suppliers(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = None,
    province: str | None = None,
    verified_only: bool = False,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    stmt = select(Supplier)
    if category:
        stmt = stmt.where(Supplier.categories.any(category))
    if province:
        stmt = stmt.where(Supplier.provinces.any(province))
    if verified_only:
        stmt = stmt.where(Supplier.verified.is_(True))
    if q:
        stmt = stmt.where(Supplier.name.ilike(f"%{q}%"))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Supplier.verified.desc(), Supplier.rating.desc().nullslast(), Supplier.name)
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
        )
        .scalars()
        .all()
    )

    return paginated(
        [SupplierOut.model_validate(r).model_dump(mode="json") for r in rows],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.post("/suppliers", status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    supplier = Supplier(
        id=uuid4(),
        organization_id=auth.organization_id,
        name=payload.name,
        categories=payload.categories,
        provinces=payload.provinces,
        contact=payload.contact,
        verified=False,
    )
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)
    return ok(SupplierOut.model_validate(supplier).model_dump(mode="json"))


# Same OOM-guard cap as `import_boq_xlsx` — supplier directories are
# small in practice (hundreds of rows max), so 5 MB is generous.
_MAX_SUPPLIERS_UPLOAD_BYTES = 5 * 1024 * 1024


@router.get("/suppliers/export.xlsx")
async def export_suppliers_xlsx(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Stream the org's supplier directory as a downloadable .xlsx.

    Header row matches what `POST /suppliers/import` recognises, so a
    buyer can export, edit in Excel, and re-import to bulk-update.
    """
    return await _export_suppliers(auth=auth, db=db, fmt="xlsx")


@router.get("/suppliers/export.csv")
async def export_suppliers_csv(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Stream the org's supplier directory as a UTF-8-with-BOM CSV."""
    return await _export_suppliers(auth=auth, db=db, fmt="csv")


async def _export_suppliers(*, auth: AuthContext, db: AsyncSession, fmt: str) -> Response:
    """Shared body for both export endpoints. Renders bytes once, picks
    the right Content-Type / Content-Disposition off `fmt`."""
    rows = (
        (
            await db.execute(
                select(Supplier).where(Supplier.organization_id == auth.organization_id).order_by(Supplier.name.asc())
            )
        )
        .scalars()
        .all()
    )

    from services.suppliers_io import render_suppliers_csv, render_suppliers_xlsx

    if fmt == "xlsx":
        body = render_suppliers_xlsx(rows)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "suppliers.xlsx"
    else:
        body = render_suppliers_csv(rows)
        media_type = "text/csv; charset=utf-8"
        filename = "suppliers.csv"

    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/suppliers/import")
async def import_suppliers(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),  # noqa: B008 — FastAPI UploadFile DI
):
    """Bulk-upload suppliers from a CSV or XLSX file.

    Idempotent on `(organization_id, lower(name))`: re-uploading the
    same spreadsheet updates the existing rows (categories /
    provinces / contact get overwritten with the new values) rather
    than creating duplicates. The buyer can iterate on their CSV and
    re-import safely.

    File format autodetected from `content_type` + the upload's bytes
    — XLSX magic bytes start with `PK` (zip), CSV doesn't. Files that
    look like neither return 400.

    Limits:
      * 5 MB max upload (OOM guard).
      * No row cap — but `name` is required per row, blanks skipped.

    Response: `{ inserted, updated, skipped, total }` so the buyer's
    UI can render a confirmation banner with concrete numbers.
    """

    from services.suppliers_io import (
        SupplierImportError,
        parse_suppliers_csv,
        parse_suppliers_xlsx,
    )

    body = await file.read()
    if len(body) > _MAX_SUPPLIERS_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Upload exceeds {_MAX_SUPPLIERS_UPLOAD_BYTES // (1024 * 1024)} MB cap",
        )

    # XLSX files start with the zip magic `PK\x03\x04`. Anything else
    # we treat as CSV. Falling through to CSV parsing on a malformed
    # XLSX gives a clearer 400 (CSV decode error) than openpyxl's
    # opaque ZipFile complaint.
    is_xlsx = body[:4] == b"PK\x03\x04"

    try:
        rows = parse_suppliers_xlsx(body) if is_xlsx else parse_suppliers_csv(body)
    except SupplierImportError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    inserted = 0
    updated = 0
    skipped = 0

    # Idempotent upsert via Postgres `INSERT ... ON CONFLICT
    # (organization_id, lower(name)) DO UPDATE`. The expression-index
    # `ix_suppliers_org_lower_name` (added in migration 0024 sibling)
    # is what makes the conflict target work.
    #
    # If the index doesn't exist (older DB), we fall back to a per-row
    # SELECT-then-UPDATE-or-INSERT path. This keeps the endpoint
    # functional during a rolling deploy where the index migration
    # hasn't fired yet.
    for row in rows:
        if not row.name.strip():
            skipped += 1
            continue
        existing = (
            await db.execute(
                select(Supplier).where(
                    Supplier.organization_id == auth.organization_id,
                    func.lower(Supplier.name) == row.name.lower(),
                )
            )
        ).scalar_one_or_none()
        contact = _build_contact(row)
        if existing is not None:
            existing.categories = row.categories or existing.categories
            existing.provinces = row.provinces or existing.provinces
            # Merge contact: the spreadsheet wins on overlapping keys
            # (most recent intent), but we don't drop fields the user
            # set elsewhere (e.g. address, hours).
            merged = dict(existing.contact or {})
            merged.update(contact)
            existing.contact = merged
            updated += 1
        else:
            db.add(
                Supplier(
                    id=uuid4(),
                    organization_id=auth.organization_id,
                    name=row.name,
                    categories=row.categories,
                    provinces=row.provinces,
                    contact=contact,
                    verified=False,
                )
            )
            inserted += 1

    # Audit before commit: "user imported supplier list with N rows".
    # Resource id is null because the import touches many rows; the
    # counts in `after` are the meaningful summary for an activity
    # feed entry.
    from services.audit import record as record_audit

    await record_audit(
        db,
        organization_id=auth.organization_id,
        auth=auth,
        action="costpulse.suppliers.import",
        resource_type="supplier_directory",
        resource_id=None,
        after={
            "filename": file.filename,
            "format": "xlsx" if is_xlsx else "csv",
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "total": len(rows),
        },
    )

    await db.commit()

    return ok(
        {
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "total": len(rows),
        }
    )


def _build_contact(row) -> dict:
    """Compose the JSONB contact blob from CSV columns.

    Only sets keys that the row actually has — avoids overwriting an
    existing supplier's `contact.email` with `null` because the new
    spreadsheet didn't have an email column at all.
    """
    contact: dict[str, str] = {}
    if row.email:
        contact["email"] = row.email
    if row.phone:
        contact["phone"] = row.phone
    return contact


# ---------- RFQ ----------


@router.post("/rfq", status_code=status.HTTP_201_CREATED)
async def create_rfq(
    payload: RfqCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from workers.queue import enqueue_rfq_dispatch

    rfq = Rfq(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        estimate_id=payload.estimate_id,
        status=RfqStatus.draft.value,
        sent_to=payload.supplier_ids,
        responses=[],
        deadline=payload.deadline,
    )
    db.add(rfq)
    await db.commit()
    await db.refresh(rfq)
    await enqueue_rfq_dispatch(organization_id=auth.organization_id, rfq_id=rfq.id)
    return ok(RfqOut.model_validate(rfq).model_dump(mode="json"))


@router.get("/rfq")
async def list_rfq(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID | None = None,
):
    stmt = select(Rfq).where(Rfq.organization_id == auth.organization_id)
    if project_id:
        stmt = stmt.where(Rfq.project_id == project_id)
    rows = (await db.execute(stmt.order_by(Rfq.created_at.desc()))).scalars().all()
    return ok([RfqOut.model_validate(r).model_dump(mode="json") for r in rows])


# ---------- Estimate version history & diff ----------


@router.get("/estimates/{estimate_id}/versions")
async def list_estimate_versions(
    estimate_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the version chain for the estimate's `(project_id, name)`.

    Surfaces every prior + current version of the estimate (`draft`,
    `approved`, `superseded`) sorted `version DESC` for a most-recent-
    first sidebar. Pivot id is included even if it's superseded — that's
    how the buyer navigates *into* the history view.
    """
    pivot = (
        await db.execute(
            select(Estimate).where(
                Estimate.id == estimate_id,
                Estimate.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if pivot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estimate not found")

    if pivot.project_id is None:
        # Both NULL on `project_id` means "freelance estimate" — match by
        # IS NULL since SQLAlchemy `==` on a None value still emits
        # `= NULL` (which never matches in SQL).
        project_clause = Estimate.project_id.is_(None)
    else:
        project_clause = Estimate.project_id == pivot.project_id

    rows = (
        (
            await db.execute(
                select(Estimate)
                .where(
                    Estimate.organization_id == auth.organization_id,
                    Estimate.name == pivot.name,
                    project_clause,
                )
                .order_by(Estimate.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return ok([EstimateSummary.model_validate(r).model_dump(mode="json") for r in rows])


@router.get("/estimates/{estimate_id}/diff")
async def diff_estimate_versions(
    estimate_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    to: UUID = Query(..., description="The 'to' estimate id (newer version, typically)"),
):
    """Line-by-line BOQ diff between two estimates in the same chain.

    Path id is the `from` baseline; query `to=` is the comparison.
    Both must be in the caller's org and in the same `(project, name)`
    family — that's what version-diff *means*. Cross-family diffs would
    technically work but signal a buyer miscued click; we 400 to surface.

    Match key for line pairing:
      1. `material_code` if set (catalogue-canonical, survives renames).
      2. Otherwise a folded `(code, description)` tuple — handles
         hand-typed rows across versions even without a material match.

    Response is `EstimateDiff` with rows bucketed `added | changed |
    removed`, alphabetised by description within each bucket so the
    diff is stable across reruns.
    """
    rows = (
        (
            await db.execute(
                select(Estimate).where(
                    Estimate.id.in_([estimate_id, to]),
                    Estimate.organization_id == auth.organization_id,
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {e.id: e for e in rows}
    if estimate_id not in by_id or to not in by_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estimate not found")
    base, target = by_id[estimate_id], by_id[to]

    if (base.project_id, base.name) != (target.project_id, target.name):
        # Different family → almost certainly a UI bug. Surface as 400
        # rather than emit a nonsense "everything added/removed" payload.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Estimates aren't in the same (project, name) version chain",
        )

    base_items = (
        (await db.execute(select(BoqItem).where(BoqItem.estimate_id == estimate_id).order_by(BoqItem.sort_order)))
        .scalars()
        .all()
    )
    target_items = (
        (await db.execute(select(BoqItem).where(BoqItem.estimate_id == to).order_by(BoqItem.sort_order)))
        .scalars()
        .all()
    )

    base_map: dict[tuple, BoqItem] = {_diff_key(it): it for it in base_items}
    target_map: dict[tuple, BoqItem] = {_diff_key(it): it for it in target_items}

    added_rows: list[BoqDiffRow] = []
    removed_rows: list[BoqDiffRow] = []
    changed_rows: list[BoqDiffRow] = []

    for key, t in target_map.items():
        b = base_map.get(key)
        if b is None:
            added_rows.append(_added(t))
        elif _materially_different(b, t):
            changed_rows.append(_changed(b, t))
    for key, b in base_map.items():
        if key not in target_map:
            removed_rows.append(_removed(b))

    added_rows.sort(key=lambda r: r.description.lower())
    changed_rows.sort(key=lambda r: r.description.lower())
    removed_rows.sort(key=lambda r: r.description.lower())

    diff = EstimateDiff(
        from_version=base.version,
        to_version=target.version,
        from_total_vnd=base.total_vnd,
        to_total_vnd=target.total_vnd,
        rows=added_rows + changed_rows + removed_rows,
    )
    return ok(diff.model_dump(mode="json"))


def _diff_key(item: BoqItem) -> tuple:
    """Stable match key for pairing items across versions.

    Prefer `material_code` (catalogue-canonical, survives renames).
    Fall back to a (code, folded-description) pair so hand-typed rows
    still pair across versions when the buyer hasn't normalised them
    to a material yet.
    """
    if item.material_code:
        return ("mc", item.material_code)
    folded_desc = " ".join((item.description or "").lower().split())
    return ("cd", item.code or "", folded_desc)


def _materially_different(a: BoqItem, b: BoqItem) -> bool:
    """Diff "what the buyer cares about": qty, unit price, total, unit.

    Description is intentionally excluded — typo fixes shouldn't show
    up as "changed" rows when the underlying numbers are identical.
    """
    return (
        a.quantity != b.quantity
        or a.unit_price_vnd != b.unit_price_vnd
        or a.total_price_vnd != b.total_price_vnd
        or (a.unit or "") != (b.unit or "")
    )


def _added(t: BoqItem) -> BoqDiffRow:
    return BoqDiffRow(
        kind="added",
        material_code=t.material_code,
        code=t.code,
        description=t.description or "",
        to_qty=t.quantity,
        to_unit_price_vnd=t.unit_price_vnd,
        to_total_price_vnd=t.total_price_vnd,
        to_unit=t.unit,
    )


def _removed(b: BoqItem) -> BoqDiffRow:
    return BoqDiffRow(
        kind="removed",
        material_code=b.material_code,
        code=b.code,
        description=b.description or "",
        from_qty=b.quantity,
        from_unit_price_vnd=b.unit_price_vnd,
        from_total_price_vnd=b.total_price_vnd,
        from_unit=b.unit,
    )


def _changed(b: BoqItem, t: BoqItem) -> BoqDiffRow:
    return BoqDiffRow(
        kind="changed",
        material_code=t.material_code or b.material_code,
        code=t.code or b.code,
        description=t.description or b.description or "",
        from_qty=b.quantity,
        to_qty=t.quantity,
        from_unit_price_vnd=b.unit_price_vnd,
        to_unit_price_vnd=t.unit_price_vnd,
        from_total_price_vnd=b.total_price_vnd,
        to_total_price_vnd=t.total_price_vnd,
        from_unit=b.unit,
        to_unit=t.unit,
    )


# ---------- Analytics ----------


@router.get("/analytics/cost-benchmark")
async def cost_benchmark(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_type: str | None = None,
    province: str | None = None,
):
    """Compute cost/m² p25/median/p75 across approved estimates joined to projects."""
    from models.core import Project

    stmt = (
        select(
            Project.type.label("project_type"),
            Project.address["province"].astext.label("province"),
            func.percentile_cont(0.25).within_group(Estimate.total_vnd / Project.area_sqm).label("p25"),
            func.percentile_cont(0.5).within_group(Estimate.total_vnd / Project.area_sqm).label("median"),
            func.percentile_cont(0.75).within_group(Estimate.total_vnd / Project.area_sqm).label("p75"),
            func.count(Estimate.id).label("sample_size"),
        )
        .join(Project, Project.id == Estimate.project_id)
        .where(
            Estimate.status == EstimateStatus.approved.value,
            Estimate.total_vnd.is_not(None),
            Project.area_sqm.is_not(None),
            Project.area_sqm > 0,
        )
        .group_by(Project.type, Project.address["province"].astext)
    )
    if project_type:
        stmt = stmt.where(Project.type == project_type)
    if province:
        stmt = stmt.where(Project.address["province"].astext == province)

    rows = (await db.execute(stmt)).all()
    buckets = [
        CostBenchmarkBucket(
            project_type=r.project_type or "unknown",
            province=r.province,
            quality_tier=None,
            cost_per_sqm_vnd_p25=int(r.p25 or 0),
            cost_per_sqm_vnd_median=int(r.median or 0),
            cost_per_sqm_vnd_p75=int(r.p75 or 0),
            sample_size=int(r.sample_size or 0),
        )
        for r in rows
    ]
    return ok(CostBenchmarkResponse(buckets=buckets).model_dump(mode="json"))


# ---------- Price alerts ----------


@router.post("/price-alerts", status_code=status.HTTP_201_CREATED)
async def create_price_alert(
    material_code: str,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    province: str | None = None,
    threshold_pct: float = 5.0,
):
    alert = PriceAlert(
        id=uuid4(),
        organization_id=auth.organization_id,
        user_id=auth.user_id,
        material_code=material_code,
        province=province,
        threshold_pct=Decimal(str(threshold_pct)),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return ok({"id": str(alert.id), "material_code": alert.material_code})


# ---------- Helpers ----------


VARIANCE_THRESHOLD_PCT = Decimal("2")


async def _emit_variance_change_order(
    db: AsyncSession,
    estimate: Estimate,
    organization_id: UUID,
) -> ChangeOrder | None:
    """Insert a draft ChangeOrder when an approved estimate deviates from the
    project's prior approved baseline by more than `VARIANCE_THRESHOLD_PCT`.

    Idempotent via the (project_id, number) unique constraint — we derive a
    deterministic number from the estimate id and short-circuit if that row
    already exists.
    """
    if estimate.project_id is None or estimate.total_vnd is None:
        return None

    prior = (
        await db.execute(
            select(Estimate)
            .where(
                Estimate.project_id == estimate.project_id,
                Estimate.id != estimate.id,
                Estimate.status == EstimateStatus.approved.value,
                Estimate.total_vnd.is_not(None),
            )
            .order_by(Estimate.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if prior is None:
        return None  # first approved estimate — no baseline to compare against

    prior_total = Decimal(prior.total_vnd)
    new_total = Decimal(estimate.total_vnd)
    delta = new_total - prior_total
    if prior_total == 0:
        return None
    pct = (delta / prior_total) * Decimal(100)
    if abs(pct) < VARIANCE_THRESHOLD_PCT:
        return None

    number = f"COST-{estimate.id.hex[:8].upper()}"
    existing = (
        await db.execute(
            select(ChangeOrder).where(
                ChangeOrder.project_id == estimate.project_id,
                ChangeOrder.number == number,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    direction = "increase" if delta > 0 else "decrease"
    co = ChangeOrder(
        id=uuid4(),
        organization_id=organization_id,
        project_id=estimate.project_id,
        number=number,
        title=f"Budget {direction}: {estimate.name} (v{estimate.version})",
        description=(
            f"Approved estimate '{estimate.name}' (v{estimate.version}) shifts the "
            f"project budget by {pct:+.2f}% vs. the prior approved baseline "
            f"(prior total {int(prior_total):,} VND → new total {int(new_total):,} VND)."
        ),
        status="draft",
        initiator="costpulse",
        cost_impact_vnd=int(delta),
        schedule_impact_days=None,
        ai_analysis={
            "source": "costpulse.estimate_approved",
            "new_estimate_id": str(estimate.id),
            "prior_estimate_id": str(prior.id),
            "prior_total_vnd": int(prior_total),
            "new_total_vnd": int(new_total),
            "delta_vnd": int(delta),
            "variance_pct": float(pct),
        },
    )
    db.add(co)
    await db.flush()
    return co


async def _load_writable_estimate(
    db: AsyncSession,
    auth: AuthContext,
    estimate_id: UUID,
) -> Estimate:
    """Load an Estimate scoped to the caller's org and refuse if it's
    immutable.

    Used by `update_boq` (PUT /estimates/{id}/boq) — that route forks a
    new version row, so the source estimate must be in a state that
    *can* be superseded:

      * 404 if the estimate doesn't exist or belongs to another org.
      * 409 if it's already `superseded` (newer version exists) or
        `approved` (locked for change-order workflow). Approved
        estimates require an unapprove step before BOQ edits.
    """
    estimate = (
        await db.execute(
            select(Estimate).where(
                Estimate.id == estimate_id,
                Estimate.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if estimate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estimate not found")
    if estimate.status in ("superseded", "approved"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Estimate is {estimate.status} and cannot be edited",
        )
    return estimate


def _supersede_and_clone(
    db: AsyncSession,
    estimate: Estimate,
    actor_user_id: UUID | None,
) -> Estimate:
    """Mark `estimate` as superseded and add a fresh draft clone with
    `version = old.version + 1`.

    Returns the *new* Estimate (not yet flushed — caller must flush
    before referencing `new.id`). The old BOQ items stay attached to
    the old estimate id; that's the audit trail. The new estimate
    starts empty — `update_boq` immediately calls `_persist_items`
    against it.

    `actor_user_id` is recorded on the new row's `created_by` so the
    audit log can answer "who started this revision."
    """
    estimate.status = "superseded"

    new_estimate = Estimate(
        id=uuid4(),
        organization_id=estimate.organization_id,
        project_id=estimate.project_id,
        name=estimate.name,
        version=estimate.version + 1,
        status="draft",
        # `total_vnd` deliberately starts None — `_persist_items` returns
        # the recomputed total which `update_boq` writes back here. If we
        # carried over the old total it would briefly be wrong (between
        # this clone and the items being inserted).
        total_vnd=None,
        confidence=estimate.confidence,
        method=estimate.method,
        created_by=actor_user_id,
        approved_by=None,  # new draft, not yet approved
    )
    db.add(new_estimate)
    return new_estimate


def _persist_items(
    db: AsyncSession,
    estimate_id: UUID,
    items: list[BoqItemIn],
    recompute: bool = True,
) -> Decimal:
    """Insert items and return the root-level total (sum of items with no parent)."""
    total = Decimal(0)
    id_map: dict[UUID, UUID] = {}

    for item in items:
        new_id = uuid4()
        if item.id is not None:
            id_map[item.id] = new_id

    for item in items:
        new_id = id_map.get(item.id or uuid4()) if item.id else uuid4()
        parent_id = id_map.get(item.parent_id) if item.parent_id else None

        line_total = item.total_price_vnd
        if recompute and item.quantity is not None and item.unit_price_vnd is not None:
            line_total = Decimal(item.quantity) * Decimal(item.unit_price_vnd)

        boq = BoqItem(
            id=new_id,
            estimate_id=estimate_id,
            parent_id=parent_id,
            sort_order=item.sort_order,
            code=item.code,
            description=item.description,
            unit=item.unit,
            quantity=item.quantity,
            unit_price_vnd=item.unit_price_vnd,
            total_price_vnd=line_total,
            material_code=item.material_code,
            source=item.source.value if item.source else None,
            notes=item.notes,
        )
        db.add(boq)

        if parent_id is None and line_total is not None:
            total += Decimal(line_total)

    return total


async def _load_estimate_detail(db: AsyncSession, estimate_id: UUID) -> EstimateDetail:
    estimate = (await db.execute(select(Estimate).where(Estimate.id == estimate_id))).scalar_one()
    items = (
        (
            await db.execute(
                select(BoqItem).where(BoqItem.estimate_id == estimate_id).order_by(BoqItem.sort_order, BoqItem.code)
            )
        )
        .scalars()
        .all()
    )

    return EstimateDetail(
        id=estimate.id,
        project_id=estimate.project_id,
        name=estimate.name,
        version=estimate.version,
        status=EstimateStatus(estimate.status),
        total_vnd=estimate.total_vnd,
        confidence=EstimateConfidence(estimate.confidence) if estimate.confidence else None,
        method=EstimateMethod(estimate.method) if estimate.method else None,
        created_by=estimate.created_by,
        approved_by=estimate.approved_by,
        created_at=estimate.created_at,
        items=[BoqItemOut.model_validate(i) for i in items],
    )


# ---------- BOQ-export helpers ----------


async def _load_estimate_for_export(
    db: AsyncSession,
    auth: AuthContext,
    estimate_id: UUID,
) -> tuple[list, Estimate]:
    """Common loader for the export endpoints.

    Returns `(boq_rows, estimate)` so the caller can render either format
    without two round-trips to the DB. `boq_rows` is `list[BoqRow]` from
    `services.boq_io`, ready for `render_boq_xlsx` / `render_boq_pdf`.
    """
    estimate = (
        await db.execute(
            select(Estimate).where(
                Estimate.id == estimate_id,
                Estimate.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if estimate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estimate not found")

    items = (
        (await db.execute(select(BoqItem).where(BoqItem.estimate_id == estimate_id).order_by(BoqItem.sort_order)))
        .scalars()
        .all()
    )

    from services.boq_io import BoqRow

    rows = [
        BoqRow(
            description=i.description or "",
            code=i.code,
            unit=i.unit,
            quantity=i.quantity,
            unit_price_vnd=i.unit_price_vnd,
            total_price_vnd=i.total_price_vnd,
            material_code=i.material_code,
            sort_order=i.sort_order or 0,
        )
        for i in items
    ]
    return rows, estimate


def _safe_sheet_name(name: str) -> str:
    """Excel sheet names cap at 31 chars and disallow `:\\/?*[]`.

    Trim + replace illegal chars with hyphens. Empty / whitespace falls
    back to "BOQ" so a sheet always has a stable name.
    """
    cleaned = "".join("-" if c in r":\\/?*[]" else c for c in (name or "").strip())
    return (cleaned[:31] or "BOQ").rstrip()


def _filename_for_export(estimate_name: str, *, ext: str) -> str:
    """ASCII-safe filename for the `Content-Disposition` header.

    HTTP filename* RFC-5987 is the proper handling for non-ASCII names,
    but most browsers and curl handle the unquoted simple form fine for
    ASCII-only filenames — and Vietnamese estimate names contain
    diacritics that some clients mangle. We strip to a safe-ASCII slug
    rather than escape, accepting that the visual fidelity of the
    download name takes a small hit in exchange for cross-client
    reliability.
    """
    import re

    base = re.sub(r"[^A-Za-z0-9._-]+", "-", (estimate_name or "boq")).strip("-_") or "boq"
    return f"{base[:80]}.{ext}"
