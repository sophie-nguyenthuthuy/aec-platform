"""FastAPI router for BIDRADAR endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import Envelope, Meta, ok, paginated
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from models.bidradar import FirmProfile as FirmProfileModel, Tender, TenderDigest, TenderMatch
from models.winwork import Proposal as ProposalModel
from schemas.bidradar import (
    AIRecommendation,
    CreateProposalRequest,
    CreateProposalResponse,
    FirmProfile,
    FirmProfileInput,
    MatchStatus,
    ScoreMatchesRequest,
    ScoreMatchesResult,
    ScrapeRequest,
    ScrapeResult,
    SendDigestRequest,
    TenderDetail,
    TenderMatch as TenderMatchSchema,
    TenderMatchWithTender,
    TenderSummary,
    UpdateMatchStatusRequest,
    WeeklyDigest,
)

from ml.pipelines.bidradar import (
    embed_tender,
    scrape_source,
    score_tender_for_firm,
    send_weekly_digest,
)


router = APIRouter(prefix="/api/v1/bidradar", tags=["bidradar"])


# ---------- Firm profile ----------

@router.get("/profile")
async def get_firm_profile(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    stmt = select(FirmProfileModel).where(FirmProfileModel.organization_id == auth.organization_id)
    profile = (await db.execute(stmt)).scalar_one_or_none()
    if profile is None:
        return ok(None)
    return ok(FirmProfile.model_validate(profile).model_dump(mode="json"))


@router.put("/profile")
async def upsert_firm_profile(
    payload: FirmProfileInput,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    stmt = select(FirmProfileModel).where(FirmProfileModel.organization_id == auth.organization_id)
    profile = (await db.execute(stmt)).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if profile is None:
        profile = FirmProfileModel(
            id=uuid4(),
            organization_id=auth.organization_id,
            **payload.model_dump(),
            updated_at=now,
        )
        db.add(profile)
    else:
        for k, v in payload.model_dump().items():
            setattr(profile, k, v)
        profile.updated_at = now

    await db.commit()
    await db.refresh(profile)
    return ok(FirmProfile.model_validate(profile).model_dump(mode="json"))


# ---------- Tenders (aggregated, cross-tenant) ----------

@router.get("/tenders")
async def list_tenders(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    country_code: str | None = Query(default=None, max_length=2),
    province: str | None = None,
    discipline: str | None = None,
    min_budget_vnd: int | None = Query(default=None, ge=0),
    max_budget_vnd: int | None = Query(default=None, ge=0),
    deadline_before: datetime | None = None,
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    stmt = select(Tender)
    if country_code:
        stmt = stmt.where(Tender.country_code == country_code.upper())
    if province:
        stmt = stmt.where(Tender.province == province)
    if discipline:
        stmt = stmt.where(Tender.disciplines.any(discipline))
    if min_budget_vnd is not None:
        stmt = stmt.where(Tender.budget_vnd >= min_budget_vnd)
    if max_budget_vnd is not None:
        stmt = stmt.where(Tender.budget_vnd <= max_budget_vnd)
    if deadline_before is not None:
        stmt = stmt.where(Tender.submission_deadline <= deadline_before)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Tender.title.ilike(like), Tender.description.ilike(like), Tender.issuer.ilike(like)))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    stmt = stmt.order_by(Tender.submission_deadline.asc().nulls_last()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return paginated(
        [TenderSummary.model_validate(t).model_dump(mode="json") for t in rows],
        page=offset // max(limit, 1) + 1,
        per_page=limit,
        total=total,
    )


@router.get("/tenders/{tender_id}")
async def get_tender(
    tender_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    tender = await db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    return ok(TenderDetail.model_validate(tender).model_dump(mode="json"))


# ---------- Matches ----------

@router.get("/matches")
async def list_matches(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: MatchStatus | None = Query(default=None, alias="status"),
    min_score: float | None = Query(default=None, ge=0, le=100),
    recommended_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    stmt = (
        select(TenderMatch, Tender)
        .join(Tender, Tender.id == TenderMatch.tender_id)
        .where(TenderMatch.organization_id == auth.organization_id)
    )
    if status_filter is not None:
        stmt = stmt.where(TenderMatch.status == status_filter.value)
    if min_score is not None:
        stmt = stmt.where(TenderMatch.match_score >= min_score)
    if recommended_only:
        stmt = stmt.where(TenderMatch.recommended_bid.is_(True))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    stmt = stmt.order_by(TenderMatch.match_score.desc().nulls_last()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).all()

    items = []
    for match, tender in rows:
        data = TenderMatchWithTender.model_validate(
            {**match.__dict__, "tender": tender}
        ).model_dump(mode="json")
        items.append(data)

    return paginated(
        items,
        page=offset // max(limit, 1) + 1,
        per_page=limit,
        total=total,
    )


@router.get("/matches/{match_id}")
async def get_match(
    match_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    stmt = (
        select(TenderMatch, Tender)
        .join(Tender, Tender.id == TenderMatch.tender_id)
        .where(
            and_(
                TenderMatch.id == match_id,
                TenderMatch.organization_id == auth.organization_id,
            )
        )
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Match not found")
    match, tender = row
    data = TenderMatchWithTender.model_validate({**match.__dict__, "tender": tender}).model_dump(mode="json")
    return ok(data)


@router.patch("/matches/{match_id}/status")
async def update_match_status(
    match_id: UUID,
    payload: UpdateMatchStatusRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    stmt = select(TenderMatch).where(
        and_(TenderMatch.id == match_id, TenderMatch.organization_id == auth.organization_id)
    )
    match = (await db.execute(stmt)).scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")

    match.status = payload.status.value
    match.reviewed_by = auth.user_id
    match.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(match)
    return ok(TenderMatchSchema.model_validate(match).model_dump(mode="json"))


# ---------- Scrape + score ----------

@router.post("/scrape")
async def trigger_scrape(
    payload: ScrapeRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    started_at = datetime.now(timezone.utc)
    try:
        scraped = await scrape_source(source=payload.source.value, max_pages=payload.max_pages)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Scrape failed: {exc}")

    new_count = 0
    tender_ids: list[UUID] = []
    tender_texts: dict[UUID, tuple[str, str | None]] = {}
    for item in scraped:
        values = {
            "id": uuid4(),
            "source": payload.source.value,
            "external_id": item["external_id"],
            "title": item["title"],
            "issuer": item.get("issuer"),
            "type": item.get("type"),
            "budget_vnd": item.get("budget_vnd"),
            "currency": item.get("currency", "VND"),
            "country_code": item.get("country_code", "VN"),
            "province": item.get("province"),
            "disciplines": item.get("disciplines"),
            "project_types": item.get("project_types"),
            "submission_deadline": item.get("submission_deadline"),
            "published_at": item.get("published_at"),
            "description": item.get("description"),
            "raw_url": item.get("raw_url"),
            "raw_payload": item.get("raw_payload"),
            "scraped_at": started_at,
        }
        stmt = (
            pg_insert(Tender)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["source", "external_id"],
                set_={
                    "title": values["title"],
                    "budget_vnd": values["budget_vnd"],
                    "submission_deadline": values["submission_deadline"],
                    "description": values["description"],
                    "raw_payload": values["raw_payload"],
                    "scraped_at": values["scraped_at"],
                },
            )
            .returning(Tender.id, Tender.created_at if hasattr(Tender, "created_at") else Tender.id)
        )
        result = await db.execute(stmt)
        row = result.first()
        if row is not None:
            tender_ids.append(row[0])
            tender_texts[row[0]] = (values["title"], values["description"])
            new_count += 1

    await db.commit()

    for tid, (title, description) in tender_texts.items():
        try:
            await embed_tender(
                db=db,
                organization_id=auth.organization_id,
                tender_id=tid,
                title=title,
                description=description,
            )
        except Exception:
            pass
    if tender_texts:
        await db.commit()

    profile_stmt = select(FirmProfileModel).where(FirmProfileModel.organization_id == auth.organization_id)
    profile = (await db.execute(profile_stmt)).scalar_one_or_none()

    matches_created = 0
    if profile is not None and tender_ids:
        matches_created = await _score_and_persist(
            db=db,
            organization_id=auth.organization_id,
            profile=profile,
            tender_ids=tender_ids,
            rescore_existing=False,
        )

    return ok(
        ScrapeResult(
            source=payload.source.value,
            tenders_found=len(scraped),
            new_tenders=new_count,
            matches_created=matches_created,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
        ).model_dump(mode="json")
    )


@router.post("/score")
async def score_matches(
    payload: ScoreMatchesRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    profile_stmt = select(FirmProfileModel).where(FirmProfileModel.organization_id == auth.organization_id)
    profile = (await db.execute(profile_stmt)).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=400, detail="Firm profile required before scoring")

    if payload.tender_ids:
        tender_ids = payload.tender_ids
    else:
        tid_stmt = select(Tender.id).where(
            Tender.submission_deadline > datetime.now(timezone.utc)
        )
        tender_ids = list((await db.execute(tid_stmt)).scalars().all())

    scored = await _score_and_persist(
        db=db,
        organization_id=auth.organization_id,
        profile=profile,
        tender_ids=tender_ids,
        rescore_existing=payload.rescore_existing,
    )

    recommended_stmt = select(func.count()).select_from(
        select(TenderMatch)
        .where(
            and_(
                TenderMatch.organization_id == auth.organization_id,
                TenderMatch.recommended_bid.is_(True),
            )
        )
        .subquery()
    )
    recommended = (await db.execute(recommended_stmt)).scalar_one()

    return ok(ScoreMatchesResult(scored=scored, recommended=recommended).model_dump(mode="json"))


async def _score_and_persist(
    db: AsyncSession,
    organization_id: UUID,
    profile: FirmProfileModel,
    tender_ids: list[UUID],
    rescore_existing: bool,
) -> int:
    if not tender_ids:
        return 0

    existing_stmt = select(TenderMatch).where(
        and_(
            TenderMatch.organization_id == organization_id,
            TenderMatch.tender_id.in_(tender_ids),
        )
    )
    existing_rows = (await db.execute(existing_stmt)).scalars().all()
    existing_by_tender = {m.tender_id: m for m in existing_rows}

    tenders_stmt = select(Tender).where(Tender.id.in_(tender_ids))
    tenders = (await db.execute(tenders_stmt)).scalars().all()

    scored_count = 0
    for tender in tenders:
        existing = existing_by_tender.get(tender.id)
        if existing is not None and not rescore_existing:
            continue

        try:
            rec = await score_tender_for_firm(tender=tender, profile=profile)
        except Exception:
            continue

        if existing is None:
            db.add(
                TenderMatch(
                    id=uuid4(),
                    organization_id=organization_id,
                    tender_id=tender.id,
                    match_score=rec.match_score,
                    estimated_value_vnd=rec.estimated_value_vnd,
                    competition_level=rec.competition_level.value,
                    win_probability=rec.win_probability,
                    recommended_bid=rec.recommended_bid,
                    ai_recommendation=rec.model_dump(mode="json"),
                    status=MatchStatus.new.value,
                )
            )
        else:
            existing.match_score = rec.match_score
            existing.estimated_value_vnd = rec.estimated_value_vnd
            existing.competition_level = rec.competition_level.value
            existing.win_probability = rec.win_probability
            existing.recommended_bid = rec.recommended_bid
            existing.ai_recommendation = rec.model_dump(mode="json")

        scored_count += 1

    await db.commit()
    return scored_count


# ---------- Proposal creation (routes to WinWork) ----------

@router.post("/matches/{match_id}/create-proposal")
async def create_proposal(
    match_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    stmt = (
        select(TenderMatch, Tender)
        .join(Tender, Tender.id == TenderMatch.tender_id)
        .where(
            and_(
                TenderMatch.id == match_id,
                TenderMatch.organization_id == auth.organization_id,
            )
        )
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Match not found")
    match, tender = row

    if match.proposal_id is not None:
        proposal_id = match.proposal_id
    else:
        # Seed a draft proposal in the `proposals` table so the WinWork detail
        # page has a real row to render. We prefill what we know from the tender
        # (title, budget → total_fee hint, a notes blob with the full brief), and
        # leave AI enrichment to the user via the Generate step in the editor.
        proposal_id = uuid4()
        notes_parts = [f"Source tender: {tender.title}"]
        if tender.issuer:
            notes_parts.append(f"Issuer: {tender.issuer}")
        if tender.submission_deadline:
            notes_parts.append(f"Submission deadline: {tender.submission_deadline.isoformat()}")
        if tender.raw_url:
            notes_parts.append(f"Tender URL: {tender.raw_url}")
        if tender.description:
            notes_parts.append("")
            notes_parts.append(tender.description)

        seed = ProposalModel(
            id=proposal_id,
            organization_id=auth.organization_id,
            project_id=None,
            title=f"Proposal — {tender.title}"[:500],
            status="draft",
            client_name=tender.issuer,
            client_email=None,
            scope_of_work=None,
            fee_breakdown=None,
            total_fee_vnd=tender.budget_vnd,
            total_fee_currency=tender.currency or "VND",
            valid_until=None,
            ai_generated=False,
            ai_confidence=None,
            notes="\n".join(notes_parts),
            created_by=auth.user_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(seed)
        match.proposal_id = proposal_id
        match.status = MatchStatus.pursuing.value
        match.reviewed_by = auth.user_id
        match.reviewed_at = datetime.now(timezone.utc)
        await db.commit()

    winwork_url = f"/winwork/proposals/{proposal_id}?from_tender={tender.id}"
    return ok(
        CreateProposalResponse(
            match_id=match_id,
            proposal_id=proposal_id,
            winwork_url=winwork_url,
        ).model_dump(mode="json")
    )


# ---------- Weekly digest ----------

@router.get("/digests")
async def list_digests(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=12, ge=1, le=52),
) -> dict:
    stmt = (
        select(TenderDigest)
        .where(TenderDigest.organization_id == auth.organization_id)
        .order_by(TenderDigest.week_start.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return ok([WeeklyDigest.model_validate(d).model_dump(mode="json") for d in rows])


@router.post("/digests/send")
async def send_digest(
    payload: SendDigestRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).date()
    week_end = week_start + timedelta(days=6)

    top_stmt = (
        select(TenderMatch)
        .where(
            and_(
                TenderMatch.organization_id == auth.organization_id,
                TenderMatch.created_at >= datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc),
                TenderMatch.recommended_bid.is_(True),
            )
        )
        .order_by(TenderMatch.match_score.desc().nulls_last())
        .limit(payload.top_n)
    )
    top_matches = (await db.execute(top_stmt)).scalars().all()
    top_match_ids = [m.id for m in top_matches]

    try:
        await send_weekly_digest(
            organization_id=auth.organization_id,
            recipients=[str(e) for e in payload.recipients],
            match_ids=top_match_ids,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Digest send failed: {exc}")

    digest = TenderDigest(
        id=uuid4(),
        organization_id=auth.organization_id,
        week_start=week_start,
        week_end=week_end,
        top_match_ids=top_match_ids,
        sent_to=[str(e) for e in payload.recipients],
        sent_at=now,
    )
    db.add(digest)
    await db.commit()
    await db.refresh(digest)

    return ok(WeeklyDigest.model_validate(digest).model_dump(mode="json"))
