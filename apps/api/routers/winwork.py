from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok, paginated
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from schemas.winwork import (
    BenchmarkFilters,
    FeeEstimateRequest,
    ProposalCreate,
    ProposalGenerateRequest,
    ProposalGenerateResponse,
    ProposalListFilters,
    ProposalOutcomeUpdate,
    ProposalStatus,
    ProposalUpdate,
    SendProposalRequest,
)
from schemas.winwork import (
    FeeBenchmark as FeeBenchmarkSchema,
)
from schemas.winwork import (
    Proposal as ProposalSchema,
)
from services import winwork as service

router = APIRouter(prefix="/api/v1/winwork", tags=["winwork"])


# ---------- Fee tools ----------


@router.get("/benchmarks")
async def list_benchmarks(
    discipline: str | None = Query(None),
    project_type: str | None = Query(None),
    country_code: str = Query("VN"),
    province: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_auth),
) -> dict:
    filters = BenchmarkFilters(
        discipline=discipline,  # type: ignore[arg-type]
        project_type=project_type,
        country_code=country_code,
        province=province,
    )
    rows = await service.lookup_benchmarks(session, filters)
    return ok([FeeBenchmarkSchema.model_validate(r).model_dump() for r in rows])


@router.post("/fee-estimate")
async def fee_estimate(
    payload: FeeEstimateRequest,
    session: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_auth),
) -> dict:
    estimate = await service.estimate_fee(session, payload)
    return ok(estimate.model_dump())


# ---------- Proposals ----------


@router.get("/proposals")
async def list_proposals_route(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status_filter: ProposalStatus | None = Query(None, alias="status"),
    project_id: UUID | None = Query(None),
    q: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_auth),
) -> dict:
    filters = ProposalListFilters(page=page, per_page=per_page, status=status_filter, project_id=project_id, q=q)
    rows, total = await service.list_proposals(session, filters)
    return paginated(
        [ProposalSchema.model_validate(r).model_dump(mode="json") for r in rows],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.get("/proposals/{proposal_id}")
async def get_proposal_route(
    proposal_id: UUID,
    session: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_auth),
) -> dict:
    proposal = await service.get_proposal(session, proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return ok(ProposalSchema.model_validate(proposal).model_dump(mode="json"))


@router.post("/proposals", status_code=status.HTTP_201_CREATED)
async def create_proposal_route(
    payload: ProposalCreate,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_auth),
) -> dict:
    proposal = await service.create_proposal(session, ctx.organization_id, ctx.user_id, payload)
    return ok(ProposalSchema.model_validate(proposal).model_dump(mode="json"))


@router.patch("/proposals/{proposal_id}")
async def update_proposal_route(
    proposal_id: UUID,
    payload: ProposalUpdate,
    session: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_auth),
) -> dict:
    proposal = await service.update_proposal(session, proposal_id, payload)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return ok(ProposalSchema.model_validate(proposal).model_dump(mode="json"))


@router.post("/proposals/{proposal_id}/send")
async def send_proposal_route(
    proposal_id: UUID,
    payload: SendProposalRequest,
    session: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_auth),
) -> dict:
    proposal = await service.get_proposal(session, proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    try:
        await service.send_proposal_email(session, proposal, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.refresh(proposal)
    return ok(ProposalSchema.model_validate(proposal).model_dump(mode="json"))


@router.patch("/proposals/{proposal_id}/outcome")
async def mark_outcome_route(
    proposal_id: UUID,
    payload: ProposalOutcomeUpdate,
    session: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_auth),
) -> dict:
    proposal = await service.mark_outcome(session, proposal_id, payload)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return ok(ProposalSchema.model_validate(proposal).model_dump(mode="json"))


# ---------- AI generation ----------


@router.post("/proposals/generate")
async def generate_proposal_route(
    payload: ProposalGenerateRequest,
    session: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_auth),
) -> dict:
    # Imported lazily so the API can boot even when ML deps are absent in the container.
    # `apps/ml` must be on PYTHONPATH (set in Docker/dev env).
    from pipelines.winwork import run_proposal_pipeline

    ai_output = await run_proposal_pipeline(session=session, org_id=ctx.organization_id, request=payload)
    proposal = await service.persist_generated_proposal(session, ctx.organization_id, ctx.user_id, payload, ai_output)
    return ok(
        ProposalGenerateResponse(
            proposal=ProposalSchema.model_validate(proposal),
            ai_job_id=ai_output["ai_job_id"],
        ).model_dump(mode="json")
    )


# ---------- Analytics ----------


@router.get("/analytics/win-rate")
async def win_rate_route(
    session: AsyncSession = Depends(get_db),
    _ctx: AuthContext = Depends(require_auth),
) -> dict:
    analytics = await service.win_rate_analytics(session)
    return ok(analytics.model_dump())
