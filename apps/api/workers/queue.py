"""Arq-based job queue. Routers enqueue via `enqueue()` instead of
`asyncio.create_task` so jobs survive request lifecycles and deploys.

Run the worker:
    arq workers.queue.WorkerSettings
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings, create_pool
from arq.cron import cron

from core.config import get_settings

# Register every ORM model so SQLAlchemy can sort FK deps at flush time.
# Without this, drawbridge_ingest_job blows up at commit because its handler
# only imports drawbridge models — but Document.project_id FK references
# core.Project, which would otherwise never be registered.
from models import register_all as _register_all_models

_register_all_models()

logger = logging.getLogger(__name__)

_REDIS: Any | None = None


async def get_pool():
    global _REDIS
    if _REDIS is None:
        _REDIS = await create_pool(_redis_settings())
    return _REDIS


def _redis_settings() -> RedisSettings:
    url = get_settings().redis_url
    return RedisSettings.from_dsn(url)


# ---------- Enqueue helpers ----------


async def enqueue_photo_analysis(
    *,
    organization_id: UUID,
    project_id: UUID,
    photo_ids: list[UUID],
) -> str:
    pool = await get_pool()
    job = await pool.enqueue_job(
        "photo_analysis_job",
        str(organization_id),
        str(project_id),
        [str(p) for p in photo_ids],
    )
    assert job is not None
    return job.job_id


async def enqueue_weekly_report(
    *,
    organization_id: UUID,
    project_id: UUID,
    week_start: date,
    week_end: date,
) -> str:
    pool = await get_pool()
    job = await pool.enqueue_job(
        "weekly_report_job",
        str(organization_id),
        str(project_id),
        week_start.isoformat(),
        week_end.isoformat(),
    )
    assert job is not None
    return job.job_id


async def enqueue_drawbridge_ingest(
    *,
    organization_id: UUID,
    document_id: UUID,
    storage_key: str,
    mime_type: str,
) -> str:
    pool = await get_pool()
    job = await pool.enqueue_job(
        "drawbridge_ingest_job",
        str(organization_id),
        str(document_id),
        storage_key,
        mime_type,
    )
    assert job is not None
    return job.job_id


async def enqueue_rfq_dispatch(
    *,
    organization_id: UUID,
    rfq_id: UUID,
) -> str:
    pool = await get_pool()
    job = await pool.enqueue_job(
        "rfq_dispatch_job",
        str(organization_id),
        str(rfq_id),
    )
    assert job is not None
    return job.job_id


# ---------- Job handlers ----------


async def photo_analysis_job(ctx: dict, organization_id: str, project_id: str, photo_ids: list[str]) -> dict:
    import asyncio

    from ml.pipelines.siteeye import _aggregate_progress, run_photo_analysis

    org = UUID(organization_id)
    proj = UUID(project_id)
    ids = [UUID(p) for p in photo_ids]

    await asyncio.gather(
        *(run_photo_analysis(organization_id=org, project_id=proj, photo_id=pid) for pid in ids),
        return_exceptions=True,
    )
    await _aggregate_progress(organization_id=org, project_id=proj)
    return {"analyzed": len(ids)}


async def weekly_report_job(
    ctx: dict,
    organization_id: str,
    project_id: str,
    week_start: str,
    week_end: str,
) -> dict:
    from ml.pipelines.siteeye import generate_weekly_report

    report = await generate_weekly_report(
        organization_id=UUID(organization_id),
        project_id=UUID(project_id),
        week_start=date.fromisoformat(week_start),
        week_end=date.fromisoformat(week_end),
    )
    return {"report_id": str(report.id)}


async def drawbridge_ingest_job(
    ctx: dict,
    organization_id: str,
    document_id: str,
    storage_key: str,
    mime_type: str,
) -> dict:
    from ml.pipelines.drawbridge import _ingest_document

    org = UUID(organization_id)
    doc = UUID(document_id)
    await _ingest_document(
        organization_id=org,
        document_id=doc,
        storage_key=storage_key,
        mime_type=mime_type,
    )
    return {"document_id": document_id, "status": "ingested"}


async def rfq_dispatch_job(ctx: dict, organization_id: str, rfq_id: str) -> dict:
    from services.rfq_dispatch import dispatch_rfq

    return await dispatch_rfq(organization_id=UUID(organization_id), rfq_id=UUID(rfq_id))


async def price_alerts_evaluate_job(ctx: dict) -> dict:
    from services.price_alerts import evaluate_price_alerts

    return await evaluate_price_alerts()


async def scrape_prices_job(ctx: dict, slug: str) -> dict:
    """Scrape + normalise + persist one province's price list."""
    from services.price_scrapers import get_scraper, run_scraper

    return await run_scraper(get_scraper(slug))


async def scrape_all_prices_job(ctx: dict) -> dict:
    """Fan-out entrypoint for the monthly cron. Enqueues one job per slug.

    Sequential runs would serialise per-site latency; fanning out via the
    pool lets workers pace themselves while still being polite to each DOC.
    Covers MOC + Hanoi + HCMC + the 61 generic-province configs (64 total).
    """
    from services.price_scrapers import all_slugs

    pool = await get_pool()
    slugs = all_slugs()
    for slug in slugs:
        await pool.enqueue_job("scrape_prices_job", slug)
    return {"enqueued": slugs}


# ---------- Cron ----------


async def weekly_report_cron(ctx: dict) -> dict:
    """Generate weekly reports for every project that had activity this past week."""
    from datetime import timedelta

    from sqlalchemy import text

    # Cross-tenant discovery query: we need every (org, project) pair that
    # uploaded photos this week, regardless of tenant. `site_photos` has
    # RLS (tenant_isolation_site_photos). Under `aec_app` (NOBYPASSRLS) a
    # regular SessionFactory would return zero rows and the cron would
    # silently schedule nothing. AdminSessionFactory (superuser) is the
    # correct escape hatch for this batch-discovery read.
    from db.session import AdminSessionFactory

    today = date.today()
    week_start = today - timedelta(days=today.weekday() + 7)
    week_end = week_start + timedelta(days=6)

    async with AdminSessionFactory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT organization_id, project_id
                    FROM site_photos
                    WHERE taken_at >= :start AND taken_at < (CAST(:end AS date) + INTERVAL '1 day')
                    """
                ),
                {"start": week_start, "end": week_end},
            )
        ).all()

    pool = await get_pool()
    for org_id, project_id in rows:
        await pool.enqueue_job(
            "weekly_report_job",
            str(org_id),
            str(project_id),
            week_start.isoformat(),
            week_end.isoformat(),
        )
    return {"projects_queued": len(rows), "week_start": week_start.isoformat()}


async def daily_activity_digest_cron(ctx: dict) -> dict:
    """Send the per-user daily activity digest.

    Cross-tenant by design — this enumerates every (user, organization)
    pair that has any project_watches and dispatches one email each.
    Runs under `AdminSessionFactory` (BYPASSRLS) for the same reason as
    `weekly_report_cron`: under aec_app the discovery query would return
    zero rows.

    Empty-digest skip: a user with watches but zero events in the last
    24h gets *no* email — better silence than spam.
    """
    from db.session import AdminSessionFactory
    from services.notifications import dispatch_daily_digests

    async with AdminSessionFactory() as session:
        return await dispatch_daily_digests(session)


async def rfq_deadlines_cron(ctx: dict) -> dict:
    """Auto-expire RFQ slots whose deadline has passed.

    Why this exists: without it, an RFQ past its deadline silently sits
    as `sent`/`responded` forever. Buyers see slot status `dispatched`
    on suppliers who never quoted and have no idea whether to chase
    them. The cron runs daily and:

      * For each open RFQ (status NOT IN ('closed', 'expired')) whose
        `deadline + 1 day` is in the past:
        * Flips per-supplier slots whose status is `dispatched` /
          `bounced` to `expired` (they had their chance; the buyer
          shouldn't see them as still-pending).
        * If NO supplier responded with a quote, flips RFQ status to
          `expired` so the buyer's inbox doesn't carry deadweight.
        * If at least one supplier responded, leaves status as
          `responded` — the buyer can still accept a quote.

    The `+ 1 day` grace is for late submissions: a supplier in a
    different timezone might respond at 23:59 their time and have it
    arrive after our 00:00 UTC clock cutoff.

    Cross-tenant by design — runs under `AdminSessionFactory` for the
    same reason `weekly_report_cron` does. The mutations only touch
    RFQs whose deadline has already passed; tenant isolation isn't a
    correctness concern here.
    """
    from datetime import timedelta

    from sqlalchemy import text as sql_text

    from db.session import AdminSessionFactory

    cutoff = date.today() - timedelta(days=1)
    expired_slots = 0
    expired_rfqs = 0

    async with AdminSessionFactory() as session:
        # Pull RFQs we might need to mutate. The (status, deadline)
        # combination is bounded — most RFQs close within their
        # deadline, so the result set is small even at year+ runtime.
        rows = (
            (
                await session.execute(
                    sql_text(
                        """
                        SELECT id, status, sent_to, responses, deadline
                        FROM rfqs
                        WHERE status NOT IN ('closed', 'expired')
                          AND deadline IS NOT NULL
                          AND deadline < :cutoff
                        """
                    ),
                    {"cutoff": cutoff},
                )
            )
            .mappings()
            .all()
        )

        for row in rows:
            responses = list(row["responses"] or [])
            mutated = False
            any_responded = False
            for entry in responses:
                if not isinstance(entry, dict):
                    continue
                status = entry.get("status")
                if status == "responded":
                    any_responded = True
                elif status in ("dispatched", "bounced", None):
                    entry["status"] = "expired"
                    expired_slots += 1
                    mutated = True

            new_rfq_status = row["status"]
            if not any_responded:
                new_rfq_status = "expired"
                expired_rfqs += 1

            if mutated or new_rfq_status != row["status"]:
                await session.execute(
                    sql_text(
                        """
                        UPDATE rfqs
                        SET status = :status, responses = :responses
                        WHERE id = :id
                        """
                    ).bindparams(
                        sql_bindparam("responses", type_=_JSONB()),
                    ),
                    {"id": row["id"], "status": new_rfq_status, "responses": responses},
                )
        await session.commit()

    logger.info(
        "rfq_deadlines_cron: expired %d slot(s) across %d closed RFQ(s)",
        expired_slots,
        expired_rfqs,
    )
    return {"expired_slots": expired_slots, "expired_rfqs": expired_rfqs}


def sql_bindparam(*args, **kwargs):
    """Local re-export so the cron body doesn't import sqlalchemy at module level.

    Keeps the import lazy (the cron body runs once a day) and the import
    statement physically next to the call site for readability.
    """
    from sqlalchemy import bindparam

    return bindparam(*args, **kwargs)


def _JSONB():
    """Same lazy-import rationale as `sql_bindparam` above."""
    from sqlalchemy.dialects.postgresql import JSONB

    return JSONB


# ---------- Worker settings ----------


class WorkerSettings:
    redis_settings = _redis_settings()
    functions = [
        photo_analysis_job,
        weekly_report_job,
        rfq_dispatch_job,
        price_alerts_evaluate_job,
        drawbridge_ingest_job,
        scrape_prices_job,
        scrape_all_prices_job,
    ]
    cron_jobs = [
        # Every Monday 06:00 UTC (~13:00 ICT) generate reports for the prior week.
        cron(weekly_report_cron, weekday="mon", hour=6, minute=0),
        # Nightly 22:00 UTC (~05:00 ICT) — evaluate CostPulse price alerts.
        cron(price_alerts_evaluate_job, hour=22, minute=0),
        # 2nd of each month 01:00 UTC (~08:00 ICT) — most provinces have
        # published the prior month's bulletin by then. Fan-out enqueues
        # one `scrape_prices_job` per registered province.
        cron(scrape_all_prices_job, day=2, hour=1, minute=0),
        # Every day 00:00 UTC (~07:00 ICT) — push activity digest emails
        # to every user who has watched at least one project. Empty
        # digests are skipped so a quiet day produces zero email noise.
        cron(daily_activity_digest_cron, hour=0, minute=0),
        # Every day 01:00 UTC (~08:00 ICT) — auto-expire RFQ slots whose
        # deadline (+1 day grace) has passed. Without this, the buyer's
        # inbox carries dispatched-but-never-quoted slots forever and
        # status filters lose their meaning.
        cron(rfq_deadlines_cron, hour=1, minute=0),
    ]
    max_jobs = 8
    job_timeout = 900  # 15 min — weekly report with PDF rendering can be slow
    keep_result = 3600
