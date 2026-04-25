from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.core import Project
from models.winwork import FeeBenchmark, Proposal, ProposalTemplate
from schemas.winwork import (
    BenchmarkFilters,
    FeeEstimateRequest,
    FeeEstimateResponse,
    MonthlyWinRate,
    ProjectTypeWinRate,
    ProposalCreate,
    ProposalGenerateRequest,
    ProposalListFilters,
    ProposalOutcomeUpdate,
    ProposalUpdate,
    SendProposalRequest,
    WinRateAnalytics,
)


# ---------- Fee benchmarks ----------

async def lookup_benchmarks(session: AsyncSession, filters: BenchmarkFilters) -> list[FeeBenchmark]:
    stmt = select(FeeBenchmark).where(FeeBenchmark.country_code == filters.country_code)
    if filters.discipline:
        stmt = stmt.where(FeeBenchmark.discipline == filters.discipline)
    if filters.project_type:
        stmt = stmt.where(FeeBenchmark.project_type == filters.project_type)
    if filters.province:
        stmt = stmt.where(or_(FeeBenchmark.province == filters.province, FeeBenchmark.province.is_(None)))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def estimate_fee(session: AsyncSession, req: FeeEstimateRequest) -> FeeEstimateResponse:
    """Cost per m² is loosely tied to market rates. For a quick estimate we pick the
    narrowest benchmark band that matches the discipline + project type and apply it
    against an assumed construction cost/m². Falls back to a conservative default when
    no benchmark row is found."""
    stmt = (
        select(FeeBenchmark)
        .where(
            FeeBenchmark.discipline == req.discipline,
            FeeBenchmark.project_type == req.project_type,
            FeeBenchmark.country_code == req.country_code,
        )
        .order_by(FeeBenchmark.area_sqm_min.asc().nullsfirst())
    )
    rows = (await session.execute(stmt)).scalars().all()

    # Pick the benchmark band whose area range contains req.area_sqm
    selected: FeeBenchmark | None = None
    for row in rows:
        lo = row.area_sqm_min or Decimal(0)
        hi = row.area_sqm_max or Decimal("1e12")
        if lo <= Decimal(str(req.area_sqm)) <= hi:
            selected = row
            break
    if selected is None and rows:
        selected = rows[0]

    if selected is None:
        low, mid, high = 5.0, 7.5, 10.0
        basis = "default (no benchmark found)"
        confidence = 0.35
    else:
        low = float(selected.fee_percent_low or 0)
        mid = float(selected.fee_percent_mid or 0)
        high = float(selected.fee_percent_high or 0)
        basis = selected.source or "benchmark"
        confidence = 0.75 if selected.province == req.province else 0.6

    construction_cost_per_sqm_vnd = _construction_cost_per_sqm(req.project_type)
    base_cost = int(req.area_sqm * construction_cost_per_sqm_vnd)

    return FeeEstimateResponse(
        fee_low_vnd=int(base_cost * low / 100),
        fee_mid_vnd=int(base_cost * mid / 100),
        fee_high_vnd=int(base_cost * high / 100),
        fee_percent_low=low,
        fee_percent_mid=mid,
        fee_percent_high=high,
        basis=basis,
        confidence=confidence,
    )


def _construction_cost_per_sqm(project_type: str) -> int:
    """VND/m² construction cost reference (rough). Calibrated against the Vietnam
    market as of early 2026 — refine as benchmark data accumulates."""
    table = {
        "residential_villa": 12_000_000,
        "residential_apartment": 10_000_000,
        "commercial_office": 15_000_000,
        "commercial_retail": 14_000_000,
        "industrial": 8_000_000,
        "infrastructure": 20_000_000,
    }
    return table.get(project_type, 12_000_000)


# ---------- Proposals CRUD ----------

async def list_proposals(
    session: AsyncSession, filters: ProposalListFilters
) -> tuple[list[Proposal], int]:
    stmt = select(Proposal)
    count_stmt = select(func.count()).select_from(Proposal)

    if filters.status:
        stmt = stmt.where(Proposal.status == filters.status)
        count_stmt = count_stmt.where(Proposal.status == filters.status)
    if filters.project_id:
        stmt = stmt.where(Proposal.project_id == filters.project_id)
        count_stmt = count_stmt.where(Proposal.project_id == filters.project_id)
    if filters.q:
        term = f"%{filters.q}%"
        stmt = stmt.where(or_(Proposal.title.ilike(term), Proposal.client_name.ilike(term)))
        count_stmt = count_stmt.where(or_(Proposal.title.ilike(term), Proposal.client_name.ilike(term)))

    stmt = (
        stmt.order_by(Proposal.created_at.desc())
        .offset((filters.page - 1) * filters.per_page)
        .limit(filters.per_page)
    )

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows), int(total)


async def get_proposal(session: AsyncSession, proposal_id: UUID) -> Proposal | None:
    return await session.get(Proposal, proposal_id)


async def create_proposal(
    session: AsyncSession, org_id: UUID, user_id: UUID, data: ProposalCreate
) -> Proposal:
    proposal = Proposal(
        id=uuid4(),
        organization_id=org_id,
        project_id=data.project_id,
        title=data.title,
        status=data.status,
        client_name=data.client_name,
        client_email=data.client_email,
        scope_of_work=data.scope_of_work.model_dump() if data.scope_of_work else None,
        fee_breakdown=data.fee_breakdown.model_dump() if data.fee_breakdown else None,
        total_fee_vnd=data.total_fee_vnd,
        total_fee_currency=data.total_fee_currency,
        valid_until=data.valid_until,
        notes=data.notes,
        ai_generated=False,
        created_by=user_id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(proposal)
    await session.flush()
    return proposal


async def update_proposal(
    session: AsyncSession, proposal_id: UUID, data: ProposalUpdate
) -> Proposal | None:
    proposal = await session.get(Proposal, proposal_id)
    if proposal is None:
        return None
    payload = data.model_dump(exclude_unset=True)
    for key, value in payload.items():
        if key in ("scope_of_work", "fee_breakdown") and value is not None:
            setattr(proposal, key, value if isinstance(value, dict) else value.model_dump())
        else:
            setattr(proposal, key, value)
    await session.flush()
    return proposal


async def mark_outcome(
    session: AsyncSession, proposal_id: UUID, data: ProposalOutcomeUpdate
) -> Proposal | None:
    proposal = await session.get(Proposal, proposal_id)
    if proposal is None:
        return None
    proposal.status = data.status
    proposal.responded_at = datetime.now(timezone.utc)
    notes = proposal.notes or ""
    if data.reason:
        notes = f"{notes}\n[outcome reason] {data.reason}".strip()
    if data.actual_fee_vnd is not None:
        notes = f"{notes}\n[actual_fee_vnd] {data.actual_fee_vnd}".strip()
    proposal.notes = notes

    # Won-deal handoff: if this proposal just flipped to 'won' and isn't yet
    # attached to a project, seed a projects row so downstream modules
    # (PULSE / COSTPULSE / DRAWBRIDGE / HANDOVER) have something to key off.
    # Idempotent via the `proposal.project_id is None` check — re-marking a
    # won proposal won't spawn duplicate projects.
    if data.status == "won" and proposal.project_id is None:
        project = await _seed_project_from_proposal(session, proposal, data)
        proposal.project_id = project.id

    await session.flush()
    return proposal


async def _seed_project_from_proposal(
    session: AsyncSession,
    proposal: Proposal,
    data: ProposalOutcomeUpdate,
) -> Project:
    """Create a projects row from a won proposal.

    Naming: strip the 'Proposal — ' prefix if present so the project reads
    naturally in PULSE/COSTPULSE.
    Budget: prefer the actual (won) fee over the quoted total.
    """
    name = proposal.title
    if name.startswith("Proposal — "):
        name = name[len("Proposal — "):]
    name = name[:200] or f"Project from proposal {proposal.id}"

    project = Project(
        id=uuid4(),
        organization_id=proposal.organization_id,
        name=name,
        type=None,  # unknown from a free-form proposal; PULSE can let the user set this
        status="active",
        budget_vnd=data.actual_fee_vnd or proposal.total_fee_vnd,
        metadata_={
            "seeded_from": "winwork.proposal",
            "proposal_id": str(proposal.id),
        },
        created_at=datetime.now(timezone.utc),
    )
    session.add(project)
    await session.flush()
    return project


async def mark_sent(session: AsyncSession, proposal_id: UUID) -> Proposal | None:
    stmt = (
        update(Proposal)
        .where(Proposal.id == proposal_id)
        .values(status="sent", sent_at=datetime.now(timezone.utc))
        .returning(Proposal)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ---------- Analytics ----------

async def win_rate_analytics(session: AsyncSession) -> WinRateAnalytics:
    status_counts_stmt = select(Proposal.status, func.count(Proposal.id)).group_by(Proposal.status)
    status_counts = {s: int(c) for s, c in (await session.execute(status_counts_stmt)).all()}

    total = sum(status_counts.values())
    won = status_counts.get("won", 0)
    lost = status_counts.get("lost", 0)
    pending = status_counts.get("sent", 0) + status_counts.get("draft", 0)
    decided = won + lost
    win_rate = (won / decided) if decided else 0.0

    avg_stmt = select(func.coalesce(func.avg(Proposal.total_fee_vnd), 0))
    avg_fee = int((await session.execute(avg_stmt)).scalar_one() or 0)

    by_type_stmt = (
        select(
            Project.type.label("project_type"),
            func.count(Proposal.id).label("total"),
            func.count(Proposal.id).filter(Proposal.status == "won").label("won"),
        )
        .join(Project, Project.id == Proposal.project_id, isouter=True)
        .group_by(Project.type)
    )
    rows = (await session.execute(by_type_stmt)).all()
    by_project_type = [
        ProjectTypeWinRate(
            project_type=pt or "unknown",
            total=int(t),
            won=int(w),
            win_rate=(int(w) / int(t)) if t else 0.0,
        )
        for pt, t, w in rows
    ]

    month_trunc = func.to_char(func.date_trunc("month", Proposal.created_at), "YYYY-MM")
    by_month_stmt = (
        select(
            month_trunc.label("month"),
            func.count(Proposal.id).label("total"),
            func.count(Proposal.id).filter(Proposal.status == "won").label("won"),
            func.count(Proposal.id).filter(Proposal.status == "lost").label("lost"),
        )
        .group_by(month_trunc)
        .order_by(month_trunc)
    )
    by_month = [
        MonthlyWinRate(month=m, total=int(t), won=int(w), lost=int(l))
        for m, t, w, l in (await session.execute(by_month_stmt)).all()
    ]

    return WinRateAnalytics(
        total=total,
        won=won,
        lost=lost,
        pending=pending,
        win_rate=round(win_rate, 3),
        avg_fee_vnd=avg_fee,
        by_project_type=by_project_type,
        by_month=by_month,
    )


# ---------- Email send (stub) ----------

async def send_proposal_email(
    session: AsyncSession, proposal: Proposal, payload: SendProposalRequest
) -> None:
    """Email sending intentionally left as a stub. Hook in an SMTP/SES client here,
    render the proposal via TipTap → HTML, and enqueue a Celery task for delivery
    so the request returns quickly."""
    if not proposal.client_email:
        raise ValueError("Proposal has no client_email")
    # TODO: integrate with email transport (Celery task posting to SES/SMTP).
    await mark_sent(session, proposal.id)


# ---------- Persistence hook for the AI pipeline ----------

async def persist_generated_proposal(
    session: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    request: ProposalGenerateRequest,
    ai_output: dict[str, Any],
) -> Proposal:
    scope = ai_output["scope_of_work"]
    fees = ai_output["fee_breakdown"]
    proposal = Proposal(
        id=uuid4(),
        organization_id=org_id,
        project_id=request.project_id,
        title=ai_output["title"],
        status="draft",
        client_name=None,
        client_email=None,
        scope_of_work=scope,
        fee_breakdown=fees,
        total_fee_vnd=fees["total_vnd"],
        total_fee_currency="VND",
        valid_until=None,
        notes=ai_output.get("notes"),
        ai_generated=True,
        ai_confidence=Decimal(str(ai_output.get("confidence", 0.0))),
        created_by=user_id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(proposal)
    await session.flush()
    return proposal
