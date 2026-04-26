"""FastAPI router for CostPulse endpoints."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok, paginated
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from models.costpulse import BoqItem, Estimate, MaterialPrice, PriceAlert, Rfq, Supplier
from models.pulse import ChangeOrder
from schemas.costpulse import (
    AiEstimateResult,
    BoqItemIn,
    BoqItemOut,
    CostBenchmarkBucket,
    CostBenchmarkResponse,
    EstimateConfidence,
    EstimateCreate,
    EstimateDetail,
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

    await db.execute(delete(BoqItem).where(BoqItem.estimate_id == estimate_id))
    total = _persist_items(db, estimate_id, payload.items, recompute=payload.recompute_totals)
    estimate.total_vnd = int(total)
    await db.commit()

    detail = await _load_estimate_detail(db, estimate_id)
    return ok(detail.model_dump(mode="json"))


@router.post("/estimates/{estimate_id}/approve")
async def approve_estimate(
    estimate_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
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
