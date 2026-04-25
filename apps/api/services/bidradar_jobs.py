"""Background jobs for BIDRADAR — scheduled scrape + per-org digest.

Invoked by Celery tasks in `apps/worker/tasks.py`. Scraping is global
(tenders are cross-tenant), so we scrape once and then fan out to every
org that has a `FirmProfile` to generate / update their matches.

Each DB interaction runs under `TenantAwareSession(org_id)` so the
RLS `app.current_org_id` is set and tenant-scoped inserts/updates are
allowed. Cross-tenant inserts into `tenders` use a dedicated system
session which bypasses RLS because `tenders` has no organization_id.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from ml.pipelines.bidradar import (
    embed_tender,
    score_tender_for_firm,
    scrape_source,
    send_weekly_digest,
)
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import AdminSessionFactory, SessionFactory, tenant_session
from models.bidradar import FirmProfile, Tender, TenderDigest, TenderMatch
from models.core import Organization

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# Scrape + score across all tenants with a FirmProfile
# ------------------------------------------------------------


async def scrape_and_score_for_all_orgs(source: str, max_pages: int = 5) -> dict:
    """Scrape one source, upsert tenders, then score for every firm profile."""
    started_at = datetime.now(UTC)
    scraped = await scrape_source(source=source, max_pages=max_pages)

    tender_ids = await _upsert_tenders(source=source, items=scraped, scraped_at=started_at)

    scored_orgs = 0
    total_matches = 0
    # `firm_profiles` has RLS; we need every org's profile in one pass so we
    # can fan out to tenant_session(...) below. Admin factory (BYPASSRLS) is
    # the correct escape hatch.
    async with AdminSessionFactory() as session:
        profiles = (await session.execute(select(FirmProfile))).scalars().all()

    for profile in profiles:
        async with tenant_session(profile.organization_id) as db:
            # Re-fetch the profile inside the tenant session so RLS sees it.
            tenant_profile = (
                await db.execute(select(FirmProfile).where(FirmProfile.organization_id == profile.organization_id))
            ).scalar_one_or_none()
            if tenant_profile is None:
                continue
            created = await _score_and_persist(
                db=db,
                organization_id=profile.organization_id,
                profile=tenant_profile,
                tender_ids=tender_ids,
                rescore_existing=False,
            )
            if created:
                scored_orgs += 1
                total_matches += created

    # Best-effort embedding pass (idempotent per tender; skipped if no key).
    await _embed_new_tenders(tender_ids)

    return {
        "source": source,
        "tenders_found": len(scraped),
        "new_or_updated_tenders": len(tender_ids),
        "orgs_scored": scored_orgs,
        "matches_created": total_matches,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
    }


async def _upsert_tenders(source: str, items: list[dict], scraped_at: datetime) -> list[UUID]:
    """Insert tenders under a system session (cross-tenant). Returns ids."""
    if not items:
        return []

    tender_ids: list[UUID] = []
    async with SessionFactory() as session:
        for item in items:
            values = {
                "id": uuid4(),
                "source": source,
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
                "scraped_at": scraped_at,
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
                .returning(Tender.id)
            )
            result = await session.execute(stmt)
            row = result.first()
            if row is not None:
                tender_ids.append(row[0])
        await session.commit()
    return tender_ids


async def _score_and_persist(
    db: AsyncSession,
    organization_id: UUID,
    profile: FirmProfile,
    tender_ids: list[UUID],
    rescore_existing: bool,
) -> int:
    """Score each tender for the given org; upsert TenderMatch rows."""
    if not tender_ids:
        return 0

    existing_rows = (
        (
            await db.execute(
                select(TenderMatch).where(
                    and_(
                        TenderMatch.organization_id == organization_id,
                        TenderMatch.tender_id.in_(tender_ids),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    existing_by_tender = {m.tender_id: m for m in existing_rows}

    tenders = (await db.execute(select(Tender).where(Tender.id.in_(tender_ids)))).scalars().all()

    created = 0
    for tender in tenders:
        existing = existing_by_tender.get(tender.id)
        if existing is not None and not rescore_existing:
            continue
        try:
            rec = await score_tender_for_firm(tender=tender, profile=profile)
        except Exception:
            logger.exception("scoring failed for tender=%s org=%s", tender.id, organization_id)
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
                    status="new",
                )
            )
        else:
            existing.match_score = rec.match_score
            existing.estimated_value_vnd = rec.estimated_value_vnd
            existing.competition_level = rec.competition_level.value
            existing.win_probability = rec.win_probability
            existing.recommended_bid = rec.recommended_bid
            existing.ai_recommendation = rec.model_dump(mode="json")
        created += 1

    await db.commit()
    return created


async def _embed_new_tenders(tender_ids: list[UUID]) -> None:
    """Best-effort embedding pass. Tenders live cross-tenant, so we embed under
    a zero-UUID org so retrieval can still scope by source_module='bidradar'.

    `embeddings` has RLS; the synthetic org means no real tenant's
    current_org_id would match on insert. Use the admin factory to bypass
    the policy for this cross-tenant write — retrieval later joins on
    source_module='bidradar', not organization_id."""
    if not tender_ids:
        return
    system_org = UUID("00000000-0000-0000-0000-000000000000")
    async with AdminSessionFactory() as session:
        tenders = (await session.execute(select(Tender).where(Tender.id.in_(tender_ids)))).scalars().all()
        for t in tenders:
            try:
                await embed_tender(
                    db=session,
                    organization_id=system_org,
                    tender_id=t.id,
                    title=t.title,
                    description=t.description,
                )
            except Exception:
                logger.exception("embed_tender failed for tender=%s", t.id)
        await session.commit()


# ------------------------------------------------------------
# Weekly digest
# ------------------------------------------------------------


async def send_weekly_digest_to_all_orgs(top_n: int = 5) -> dict:
    """For every org that has `settings.bidradar.digest_recipients` configured,
    pick the top N recommended matches from this week and email them."""
    now = datetime.now(UTC)
    week_start = (now - timedelta(days=now.weekday())).date()
    week_end = week_start + timedelta(days=6)
    week_start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=UTC)

    async with SessionFactory() as session:
        orgs = (await session.execute(select(Organization))).scalars().all()

    sent = 0
    skipped = 0
    for org in orgs:
        recipients = _digest_recipients(org)
        if not recipients:
            skipped += 1
            continue
        async with tenant_session(org.id) as db:
            top_stmt = (
                select(TenderMatch)
                .where(
                    and_(
                        TenderMatch.organization_id == org.id,
                        TenderMatch.created_at >= week_start_dt,
                        TenderMatch.recommended_bid.is_(True),
                    )
                )
                .order_by(TenderMatch.match_score.desc().nulls_last())
                .limit(top_n)
            )
            top_matches = (await db.execute(top_stmt)).scalars().all()
            if not top_matches:
                skipped += 1
                continue
            match_ids = [m.id for m in top_matches]

            try:
                await send_weekly_digest(
                    organization_id=org.id,
                    recipients=recipients,
                    match_ids=match_ids,
                )
            except Exception:
                logger.exception("digest send failed org=%s", org.id)
                continue

            db.add(
                TenderDigest(
                    id=uuid4(),
                    organization_id=org.id,
                    week_start=week_start,
                    week_end=week_end,
                    top_match_ids=match_ids,
                    sent_to=recipients,
                    sent_at=now,
                )
            )
            await db.commit()
            sent += 1

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "sent": sent,
        "skipped": skipped,
        "top_n": top_n,
    }


def _digest_recipients(org: Organization) -> list[str]:
    """Read digest recipients from `organizations.settings`.

    Layout: `{"bidradar": {"digest_recipients": ["a@firm.com", ...]}}`.
    """
    settings_json = org.settings or {}
    bidradar_cfg = settings_json.get("bidradar") if isinstance(settings_json, dict) else None
    if not isinstance(bidradar_cfg, dict):
        return []
    recipients = bidradar_cfg.get("digest_recipients") or []
    return [str(r) for r in recipients if r]
