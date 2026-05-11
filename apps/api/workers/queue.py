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
from services.cron_telemetry import cron_telemetry_wrap as _telemetry

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


async def retention_prune_cron(ctx: dict) -> dict:
    """Daily prune of unbounded growth tables — see services.retention.

    Runs at 03:00 UTC (~10:00 ICT) so it lands during the quietest
    customer-facing window. The job is bounded by
    `_MAX_PRUNE_ROWS_PER_RUN` per table per run; a backed-up tenant
    catches up over multiple days, never blocking inserts.

    Cross-tenant: `AdminSessionFactory` (BYPASSRLS) so we see all
    orgs' rows. The age filter is the per-table predicate; org
    isolation isn't a correctness concern here because we're deleting
    by `created_at`, not exposing rows back to a user.
    """
    from db.session import AdminSessionFactory
    from services.retention import run_retention_cron

    async with AdminSessionFactory() as session:
        summaries = await run_retention_cron(session)
    total = sum(s.get("deleted_count", 0) for s in summaries)
    logger.info("retention_prune_cron: deleted %d rows across %d tables: %s", total, len(summaries), summaries)
    return {"deleted_total": total, "tables": summaries}


async def webhook_drain_cron(ctx: dict) -> dict:
    """Drain the webhook outbox: pick due deliveries, sign + POST,
    mark delivered or schedule retry.

    Cross-tenant by design — uses `AdminSessionFactory` because the
    discovery query needs to see every org's pending deliveries. The
    delivery rows themselves carry `organization_id`, so per-tenant
    health metrics stay possible without re-querying.

    Runs every minute (see WorkerSettings.cron_jobs). The minute
    cadence is the floor on retry latency for a flaky receiver — if
    we ever need sub-minute end-to-end, switch to a per-event
    `pool.enqueue_job("webhook_deliver_one", delivery_id)` plus this
    cron as a safety net for stuck rows.
    """
    from db.session import AdminSessionFactory
    from services.webhooks import drain_pending

    async with AdminSessionFactory() as session:
        return await drain_pending(session)


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
        #
        # `organization_id` joins the audit emit below — each affected
        # RFQ gets a `costpulse.rfq.slots_expired` row attributed to
        # its tenant so admins see the auto-expiry trail per-org.
        rows = (
            (
                await session.execute(
                    sql_text(
                        """
                        SELECT id, organization_id, status, sent_to, responses, deadline
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

        # Lazy import — keeps the cron module load cheap and avoids a
        # cycle (audit imports webhooks, which imports the cron-side
        # `enqueue_event`).
        from services.audit import record as audit_record

        for row in rows:
            responses = list(row["responses"] or [])
            mutated = False
            any_responded = False
            row_expired_slots = 0
            for entry in responses:
                if not isinstance(entry, dict):
                    continue
                status = entry.get("status")
                if status == "responded":
                    any_responded = True
                elif status in ("dispatched", "bounced", None):
                    entry["status"] = "expired"
                    expired_slots += 1
                    row_expired_slots += 1
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
                # Audit the auto-expiry. `auth=None` because the cron
                # is the actor — there's no human at the keyboard. The
                # before/after diff captures only the fields that
                # changed (status + count of expired slots) so the row
                # stays small and PII-free.
                await audit_record(
                    session,
                    organization_id=row["organization_id"],
                    auth=None,
                    action="costpulse.rfq.slots_expired",
                    resource_type="rfq",
                    resource_id=row["id"],
                    before={"status": row["status"]},
                    after={
                        "status": new_rfq_status,
                        "expired_slot_count": row_expired_slots,
                    },
                )
        await session.commit()

    logger.info(
        "rfq_deadlines_cron: expired %d slot(s) across %d closed RFQ(s)",
        expired_slots,
        expired_rfqs,
    )
    return {"expired_slots": expired_slots, "expired_rfqs": expired_rfqs}


async def codeguard_quota_reconcile_cron(ctx: dict) -> dict:
    """Weekly drift check between codeguard_org_usage and SUM(codeguard_user_usage).

    Sets the `codeguard_quota_drift_rows` gauge to the count of (org,
    period) rows where the two tables diverge by more than 1000 tokens
    (combined input + output). The `CodeguardQuotaUsageDrift` alert
    fires on a sustained nonzero value.

    FULL OUTER JOIN so an (org, period) present in only one side
    still contributes to the drift count — both asymmetries (org_usage
    missing user totals, OR user totals missing org row) indicate
    attribution loss worth alerting on.

    Cross-tenant: AdminSessionFactory (BYPASSRLS) so the SUM() sees
    every org's rows. Weekly cadence (not daily): drift is an
    attribution-loss signal, not a hot-path correctness check.
    """
    # cron-mutex: read-only gauge publisher. Two replicas computing
    # the same COUNT and calling `.set(same_value)` is genuinely
    # idempotent — no advisory lock needed.
    from sqlalchemy import text as sql_text

    from core.metrics import codeguard_quota_drift_rows
    from db.session import AdminSessionFactory

    threshold_tokens = 1000

    async with AdminSessionFactory() as session:
        result = await session.execute(
            sql_text(
                """
                WITH user_totals AS (
                    SELECT organization_id, period_start,
                           SUM(input_tokens)  AS u_in,
                           SUM(output_tokens) AS u_out
                    FROM codeguard_user_usage
                    GROUP BY organization_id, period_start
                )
                SELECT COUNT(*) AS drift_rows
                FROM codeguard_org_usage o
                FULL OUTER JOIN user_totals u
                  ON  o.organization_id = u.organization_id
                  AND o.period_start    = u.period_start
                WHERE
                    ABS(
                        COALESCE(o.input_tokens, 0)  - COALESCE(u.u_in, 0)
                      + COALESCE(o.output_tokens, 0) - COALESCE(u.u_out, 0)
                    ) > :threshold
                """
            ),
            {"threshold": threshold_tokens},
        )
        drift_rows = int(result.scalar_one() or 0)

    # Set explicitly on every run (including clean=0) so the gauge
    # distinguishes "clean" from "metric never published" — the
    # latter would look like the cron stopped firing.
    codeguard_quota_drift_rows.set(drift_rows)
    logger.info(
        "codeguard_quota_reconcile_cron: drift_rows=%d (threshold=%d tokens)",
        drift_rows,
        threshold_tokens,
    )
    return {"drift_rows": drift_rows, "threshold_tokens": threshold_tokens}


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


# ---------- Cron-failure watchdog ----------


async def run_cron_by_name_job(ctx: dict, cron_name: str) -> dict:
    """Execute one cron NOW, on demand, by its registered name.

    Powers the `POST /admin/crons/{name}/run` endpoint (cycle O2). An
    operator triaging "did this cron actually do anything?" can fire
    it without waiting for the next schedule tick.

    Why a separate arq job rather than a direct in-process await:

      * The cron's coroutine in `WorkerSettings.cron_jobs` is already
        wrapped via `cron_telemetry_wrap` — running it through arq
        means the wrapper writes a `cron_runs` row (status running →
        succeeded/failed) just like a scheduled tick. The dashboard
        + watchdog then see the manual run in the same shape as a
        natural one. Awaiting in-process bypasses the wrapper.

      * arq enforces `job_timeout` (15 min) and `max_jobs` so a stuck
        manual run can't pin an event-loop thread for hours. The HTTP
        request returns the moment the job is enqueued; the operator
        watches the result on the drilldown page (which polls every
        30s).

      * Worker-side execution keeps the API process free of the
        cron's side effects (DB writes, S3 uploads, downstream HTTP).

    Idempotency / safety:

      * Repeated POSTs with the same `Idempotency-Key` cache the same
        job_id (via `IdempotentRoute` on the admin router). Without
        the header, every click enqueues a fresh job — which IS the
        correct behaviour: an operator deliberately "running it
        again" should run it again.

      * Concurrent runs of the same cron are technically possible
        (manual + scheduled tick overlapping). Each cron's body is
        responsible for its own concurrency safety — most of ours
        use SELECT ... FOR UPDATE SKIP LOCKED or are read-only
        gauge writers, so a duplicate run is at worst inefficient.

    Lookup by `name`:

      * `cron_name` matches the value in
        `WorkerSettings.cron_jobs[i].name` — the same value the
        dashboard renders. Operators paste it from the URL.
      * Unknown names raise so the JobResult log carries the
        diagnostic; arq's retry policy doesn't apply (the lookup
        deterministically fails on every retry).
    """
    target = None
    for entry in WorkerSettings.cron_jobs:
        if entry.name == cron_name:
            target = entry
            break
    if target is None:
        raise ValueError(f"unknown cron_name: {cron_name!r}")
    # `target.coroutine` is the already-_telemetry-wrapped coroutine
    # arq uses on the schedule. Awaiting it here threads through the
    # exact same telemetry path — `cron_runs` row writes, error
    # truncation, duration timing — as a natural tick.
    return await target.coroutine(ctx)


async def cron_failure_watchdog_cron(ctx: dict) -> dict:
    """Every 5 minutes, alert Slack on fresh `cron_runs` failures
    AND on cron runs stuck in `running` past 3× their rolling p95.

    Two concerns rolled into one cron because:
      * Both fire at the same 5-minute cadence; splitting them into
        two crons doubles arq scheduling overhead for no benefit.
      * Both write to the same Slack channel via the same
        `record_delivery_attempt` path; failures of one shouldn't
        block the other from running, so we run them sequentially
        with independent try/except.

    Cadence (5 min) MUST match
    `services.cron_alerts._FRESH_FAILURE_WINDOW_MINUTES`. Otherwise
    the watchdog's window doesn't tile cleanly with the schedule —
    failures fall between the cracks (window < cadence) or get
    re-alerted (window > cadence).

    Returns the merged summary so arq's JobResult log carries both
    counts.
    """
    from services.cron_alerts import check_failing_crons, check_stuck_crons

    # Run both in sequence, catching independently. Either failing
    # shouldn't prevent the other from emitting alerts.
    failures: dict = {}
    stuck: dict = {}
    try:
        failures = await check_failing_crons()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("cron_watchdog: failure check raised: %s", exc)
        failures = {"error": str(exc)}
    try:
        stuck = await check_stuck_crons()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("cron_watchdog: stuck check raised: %s", exc)
        stuck = {"error": str(exc)}

    return {"failures": failures, "stuck": stuck}


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
        # Operator-triggered manual cron run (cycle O2). Registered
        # in `functions` rather than `cron_jobs` because it's an
        # arq-job-by-name target, not a scheduled task.
        run_cron_by_name_job,
    ]
    cron_jobs = [
        # Every cron is wrapped via `_telemetry(...)` so each invocation
        # writes a row to `cron_runs` (status running → succeeded/failed,
        # duration_ms, error_message). The wrapper preserves __name__ /
        # __module__ / __doc__ so the `/admin/crons` dashboard still
        # reads the underlying function metadata.
        # Every Monday 06:00 UTC (~13:00 ICT) generate reports for the prior week.
        cron(_telemetry(weekly_report_cron), weekday="mon", hour=6, minute=0),
        # Nightly 22:00 UTC (~05:00 ICT) — evaluate CostPulse price alerts.
        cron(_telemetry(price_alerts_evaluate_job), hour=22, minute=0),
        # 2nd of each month 01:00 UTC (~08:00 ICT) — most provinces have
        # published the prior month's bulletin by then. Fan-out enqueues
        # one `scrape_prices_job` per registered province.
        cron(_telemetry(scrape_all_prices_job), day=2, hour=1, minute=0),
        # Every day 00:00 UTC (~07:00 ICT) — push activity digest emails
        # to every user who has watched at least one project. Empty
        # digests are skipped so a quiet day produces zero email noise.
        cron(_telemetry(daily_activity_digest_cron), hour=0, minute=0),
        # Every day 01:00 UTC (~08:00 ICT) — auto-expire RFQ slots whose
        # deadline (+1 day grace) has passed. Without this, the buyer's
        # inbox carries dispatched-but-never-quoted slots forever and
        # status filters lose their meaning.
        cron(_telemetry(rfq_deadlines_cron), hour=1, minute=0),
        # Every minute — drain the webhook outbox. A 1-minute floor
        # bounds retry latency for transient receiver failures. Idempotent
        # via `SELECT … FOR UPDATE SKIP LOCKED` so two workers running
        # concurrently won't double-deliver.
        cron(_telemetry(webhook_drain_cron), minute={i for i in range(60)}),
        # Daily 03:00 UTC (~10:00 ICT) — prune unbounded telemetry
        # tables (audit_events, search_queries, import_jobs,
        # delivered/failed webhook_deliveries) per `RETENTION_POLICIES`.
        # Capped at 10k rows per table per run so a backed-up tenant
        # catches up over multiple days without locking up the table.
        cron(_telemetry(retention_prune_cron), hour=3, minute=0),
        # Every Monday 04:00 UTC (~11:00 ICT) — reconcile codeguard
        # org-level vs per-user usage. Sets `codeguard_quota_drift_rows`;
        # `CodeguardQuotaUsageDrift` alerts on sustained nonzero values.
        # Weekly: drift is attribution loss, not hot-path correctness.
        cron(_telemetry(codeguard_quota_reconcile_cron), weekday="mon", hour=4, minute=0),
        # Every 5 minutes — scan `cron_runs` for failures freshly
        # written in the last 5 minutes, post one Slack message per
        # affected cron. The 5-min cadence MUST match
        # `services.cron_alerts._FRESH_FAILURE_WINDOW_MINUTES` —
        # mismatched values either drop alerts (cadence > window) or
        # double-alert (cadence < window).
        #
        # Self-wrapped via `_telemetry` so the watchdog ITSELF shows
        # up in `/admin/crons`. If the alerter is failing, ops sees
        # the watchdog row red and can fall back to checking the
        # registry manually.
        cron(_telemetry(cron_failure_watchdog_cron), minute={i for i in range(0, 60, 5)}),
    ]
    max_jobs = 8
    job_timeout = 900  # 15 min — weekly report with PDF rendering can be slow
    keep_result = 3600
