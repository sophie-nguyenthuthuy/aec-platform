"""Celery task definitions.

The worker shares environment and data access with the API — DATABASE_URL, REDIS_URL,
ANTHROPIC_API_KEY etc. must be set the same way. Tasks here are thin wrappers around
service-level functions so they can also be called in-process during tests.
"""

from __future__ import annotations

import asyncio
import logging
import os

from celery import Celery
from celery.schedules import crontab

log = logging.getLogger(__name__)

BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

app = Celery("aec_worker", broker=BROKER_URL, backend=BROKER_URL)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_prefetch_multiplier=2,
    broker_connection_retry_on_startup=True,
)


def _run_async(coro):
    """Run an async coroutine inside a sync Celery task.

    Celery's prefork worker has no running event loop, so `asyncio.run()`
    is the right tool — it builds a fresh loop, runs the coroutine to
    completion, and closes the loop. The previous implementation called
    `asyncio.get_event_loop()`, which Python 3.12+ deprecates outside an
    active loop, and had inverted recovery logic (it tried `asyncio.run`
    when a loop *was* running, which would crash with "asyncio.run()
    cannot be called from a running event loop").
    """
    return asyncio.run(coro)


@app.task(name="winwork.send_proposal_email", bind=True, max_retries=3, default_retry_delay=30)
def send_proposal_email(self, organization_id: str, proposal_id: str, payload: dict) -> dict:
    """Stub email task. Swap in AWS SES / SMTP client when transport is ready."""
    log.info("send_proposal_email org=%s proposal=%s", organization_id, proposal_id)
    # Integration point: render proposal, deliver via SES, update `sent_at`.
    return {"status": "sent", "proposal_id": proposal_id}


@app.task(name="files.process_upload", bind=True, max_retries=2)
def process_upload(self, file_id: str) -> dict:
    """Entry point for downstream file processing (OCR, embedding, classification)."""
    log.info("process_upload file=%s", file_id)
    return {"status": "done", "file_id": file_id}


@app.task(name="embeddings.backfill")
def backfill_embeddings(organization_id: str, source_module: str) -> dict:
    log.info("backfill_embeddings org=%s module=%s", organization_id, source_module)
    return {"status": "queued", "org": organization_id, "module": source_module}


# ------------------------------------------------------------
# BIDRADAR tasks
# ------------------------------------------------------------

_BIDRADAR_SOURCES = [
    "mua-sam-cong.gov.vn",
    "philgeps.gov.ph",
    "egp.go.th",
    "eproc.lkpp.go.id",
    "gebiz.gov.sg",
]


@app.task(name="bidradar.scrape_source", bind=True, max_retries=2, default_retry_delay=120)
def bidradar_scrape_source(self, source: str, max_pages: int = 5) -> dict:
    """Scrape one tender source, upsert tenders, and score for every firm profile."""
    from services.bidradar_jobs import scrape_and_score_for_all_orgs

    try:
        result = _run_async(scrape_and_score_for_all_orgs(source=source, max_pages=max_pages))
    except Exception as exc:
        log.exception("bidradar.scrape_source failed for %s", source)
        raise self.retry(exc=exc) from exc
    return result


@app.task(name="bidradar.scrape_all")
def bidradar_scrape_all(max_pages: int = 5) -> dict:
    """Fan-out: enqueue one scrape task per supported source."""
    for src in _BIDRADAR_SOURCES:
        bidradar_scrape_source.delay(src, max_pages)
    return {"enqueued": _BIDRADAR_SOURCES, "max_pages": max_pages}


@app.task(name="bidradar.weekly_digest")
def bidradar_weekly_digest(top_n: int = 5) -> dict:
    """Send the weekly digest to every org with digest recipients configured."""
    from services.bidradar_jobs import send_weekly_digest_to_all_orgs

    return _run_async(send_weekly_digest_to_all_orgs(top_n=top_n))


# ------------------------------------------------------------
# Celery Beat schedule
# ------------------------------------------------------------

app.conf.beat_schedule = {
    "bidradar-scrape-daily-0430-ict": {
        "task": "bidradar.scrape_all",
        # 04:30 Asia/Ho_Chi_Minh → 21:30 UTC (prev day). Use UTC for portability.
        "schedule": crontab(hour=21, minute=30),
        "kwargs": {"max_pages": 5},
    },
    "bidradar-weekly-digest-monday-0700-ict": {
        "task": "bidradar.weekly_digest",
        # Mon 07:00 Asia/Ho_Chi_Minh → Mon 00:00 UTC
        "schedule": crontab(day_of_week="mon", hour=0, minute=0),
        "kwargs": {"top_n": 5},
    },
}
