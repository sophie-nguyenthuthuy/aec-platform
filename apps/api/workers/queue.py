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

async def photo_analysis_job(
    ctx: dict, organization_id: str, project_id: str, photo_ids: list[str]
) -> dict:
    import asyncio

    from apps.ml.pipelines.siteeye import _aggregate_progress, run_photo_analysis

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
    from apps.ml.pipelines.siteeye import generate_weekly_report

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
    from apps.ml.pipelines.drawbridge import _ingest_document

    org = UUID(organization_id)
    doc = UUID(document_id)
    await _ingest_document(
        organization_id=org,
        document_id=doc,
        storage_key=storage_key,
        mime_type=mime_type,
    )
    return {"document_id": document_id, "status": "ingested"}


async def rfq_dispatch_job(
    ctx: dict, organization_id: str, rfq_id: str
) -> dict:
    from services.rfq_dispatch import dispatch_rfq

    return await dispatch_rfq(
        organization_id=UUID(organization_id), rfq_id=UUID(rfq_id)
    )


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
    """
    from services.price_scrapers import SCRAPERS

    pool = await get_pool()
    for slug in SCRAPERS:
        await pool.enqueue_job("scrape_prices_job", slug)
    return {"enqueued": list(SCRAPERS.keys())}


# ---------- Cron ----------

async def weekly_report_cron(ctx: dict) -> dict:
    """Generate weekly reports for every project that had activity this past week."""
    from datetime import timedelta

    from sqlalchemy import text

    from db.session import SessionFactory

    today = date.today()
    week_start = today - timedelta(days=today.weekday() + 7)
    week_end = week_start + timedelta(days=6)

    async with SessionFactory() as session:
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
    ]
    max_jobs = 8
    job_timeout = 900  # 15 min — weekly report with PDF rendering can be slow
    keep_result = 3600
