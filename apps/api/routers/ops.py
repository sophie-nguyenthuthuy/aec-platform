"""Operational endpoints — health probes + Prometheus scrape target.

Three endpoints:

  * `GET /healthz` — pure liveness. Returns 200 if the process can
    serve a request. No DB, no Redis. k8s/ECS rolling deploys gate
    on this for the "is the worker alive" question.

  * `GET /readyz` — readiness. Pings Postgres + Redis. Returns 200
    only when BOTH reachable; 503 with a per-dependency status JSON
    otherwise. Load balancers gate on this for the "should this
    worker get traffic" question.

  * `GET /metrics?token=<value>` — Prometheus scrape target. Emits
    text-format gauges for the things ops actually pages on:
    webhook outbox lag, api-key call rate, audit volume. Token-gated
    via `AEC_METRICS_TOKEN`; unset means open (dev path).

Why we emit Prometheus text by hand instead of using
`prometheus_client.generate_latest()`:

  * Our metric source is the database (point-in-time aggregates from
    rollup tables). `prometheus_client` collectors are sync; our DB
    is async via asyncpg. Mixing them via `asyncio.run` on the scrape
    path is fragile.
  * The text format is trivial — three lines per metric. Emitting it
    by hand avoids the cross-protocol bridge.
  * Prometheus scrapes every 15-60s; running 6 SELECTs per scrape is
    cheap on indexes we already have.

Process-level metrics (open FDs, GC, RSS) are intentionally NOT here
in v1. Those are best collected by a sidecar or by adopting
`prometheus_fastapi_instrumentator` later. The metrics that move
during an incident — webhook lag, error rates — are application-level
and live in this endpoint.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import text

from core.config import get_settings
from db.session import AdminSessionFactory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["ops"])


# ---------- Health probes ----------


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness — process can serve a request. No external deps.
    Mounted at the root (no /api/v1 prefix) so cluster probe configs
    can use the conventional path."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    """Readiness — Postgres + Redis reachable. Returns 503 with a
    per-dependency breakdown if either fails. Cluster LBs gate on
    the status code; the body lets a human debugging quickly tell
    "Redis flaked" from "DB flaked"."""
    pg_ok = False
    redis_ok = False
    pg_error: str | None = None
    redis_error: str | None = None

    # Postgres: a `SELECT 1` is the cheapest no-op the DB will run.
    try:
        async with AdminSessionFactory() as session:
            await session.execute(text("SELECT 1"))
        pg_ok = True
    except Exception as exc:
        pg_error = str(exc)[:200]
        logger.warning("readyz: postgres unreachable (%s)", exc)

    # Redis: arq's create_pool with a quick PING. Lazy import so the
    # module loads cleanly in tests where redis isn't running.
    try:
        from arq.connections import RedisSettings, create_pool

        pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        await pool.ping()
        # arq's pool doesn't expose close cleanly across versions —
        # the in-process leak is bounded by the number of probe
        # calls per restart, which is small.
        redis_ok = True
    except Exception as exc:
        redis_error = str(exc)[:200]
        logger.warning("readyz: redis unreachable (%s)", exc)

    body: dict[str, object] = {
        "postgres": {"ok": pg_ok, "error": pg_error},
        "redis": {"ok": redis_ok, "error": redis_error},
    }
    if not (pg_ok and redis_ok):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return body


# ---------- Metrics ----------
#
# `/metrics` is the canonical Prometheus scrape target. It emits TWO
# bodies concatenated:
#
#   1. `core.metrics.render()` — the in-process counters/histograms
#      maintained by `RequestMetricsMiddleware` and the codeguard
#      cap-check (`http_requests_total`, `http_request_duration_seconds`,
#      `arq_queue_depth`, `codeguard_quota_*`).
#
#   2. `_build_metrics_text()` — point-in-time DB-driven gauges over
#      the last 5 minutes (webhook outbox lag/pending, api-key calls
#      by success, search and audit volume). These are computed per
#      scrape because the source-of-truth lives in Postgres rollup
#      tables; running 6 SELECTs per scrape is cheap on the indexes
#      we already have.
#
# Token gating via `AEC_METRICS_TOKEN`. Unset = open (dev path); set
# means the endpoint requires `?token=<value>` and returns 401 on a
# mismatch. The token check is defense-in-depth — production deploys
# also network-allowlist the scraper at the LB.


@router.get("/metrics")
async def metrics(token: Annotated[str | None, Query()] = None) -> Response:
    """Prometheus exposition. Token-gated when `AEC_METRICS_TOKEN` is
    set (prod); open otherwise (dev). The body is the in-process
    metric registry concatenated with DB-driven gauges — one scrape,
    one round trip, no second endpoint to wire into Prometheus."""
    from core.metrics import _sample_queue_depth, render

    settings = get_settings()
    expected = settings.metrics_token
    if expected and token != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing_or_invalid_metrics_token")

    # Update the queue-depth gauge before rendering so the value
    # reflects the moment of read, not a stale cron snapshot.
    await _sample_queue_depth()
    in_process = render()
    db_gauges = await _build_metrics_text()
    # `render()` already ends in a newline; `_build_metrics_text` does
    # the same. Concatenate as-is — Prometheus parses the joined text
    # as one exposition document.
    return Response(
        content=in_process + db_gauges,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


async def _build_metrics_text() -> str:
    """Run the gauge queries and emit Prometheus text format.

    All gauges are point-in-time over the last 5 minutes — the
    canonical Prometheus rate window. Longer windows would smooth
    incident spikes; shorter would alias against the scrape interval.
    """
    lines: list[str] = []

    async with AdminSessionFactory() as session:
        # Webhook outbox state — three labels for the three statuses.
        wh_status_rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT status, COUNT(*) AS n
                        FROM webhook_deliveries
                        WHERE created_at > NOW() - INTERVAL '5 minutes'
                        GROUP BY status
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
        lines.append("# HELP aec_webhook_deliveries_total Webhook deliveries created in the last 5 minutes.")
        lines.append("# TYPE aec_webhook_deliveries_total gauge")
        seen_statuses = set()
        for row in wh_status_rows:
            status_label = _escape_label(row["status"])
            seen_statuses.add(row["status"])
            lines.append(f'aec_webhook_deliveries_total{{status="{status_label}"}} {int(row["n"])}')
        # Pad missing statuses with 0 so a flatlined dashboard reads
        # "0 failed in 5min" instead of "no data".
        for s in ("pending", "delivered", "failed"):
            if s not in seen_statuses:
                lines.append(f'aec_webhook_deliveries_total{{status="{s}"}} 0')

        # Outbox lag — oldest pending row's age in seconds. The single
        # most operationally useful gauge: tells ops "are we behind".
        lag_row = (
            (
                await session.execute(
                    text(
                        """
                        SELECT
                            EXTRACT(EPOCH FROM NOW() - MIN(created_at))::float AS age_seconds,
                            COUNT(*) AS pending_count
                        FROM webhook_deliveries
                        WHERE status = 'pending'
                        """
                    )
                )
            )
            .mappings()
            .one()
        )
        lines.append("# HELP aec_webhook_outbox_lag_seconds Age of the oldest pending webhook delivery.")
        lines.append("# TYPE aec_webhook_outbox_lag_seconds gauge")
        lines.append(f"aec_webhook_outbox_lag_seconds {float(lag_row['age_seconds'] or 0)}")
        lines.append("# HELP aec_webhook_outbox_pending Pending webhook deliveries (not yet attempted or in retry).")
        lines.append("# TYPE aec_webhook_outbox_pending gauge")
        lines.append(f"aec_webhook_outbox_pending {int(lag_row['pending_count'] or 0)}")

        # API-key calls — split by success bool. The rollup table is
        # already minute-bucketed, so a 5-min sum is one query.
        api_calls_rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT success, COALESCE(SUM(count), 0) AS n
                        FROM api_key_calls
                        WHERE minute_bucket > NOW() - INTERVAL '5 minutes'
                        GROUP BY success
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
        lines.append("# HELP aec_api_key_calls_total API-key auth calls in the last 5 minutes.")
        lines.append("# TYPE aec_api_key_calls_total gauge")
        seen_success = set()
        for row in api_calls_rows:
            label = "true" if row["success"] else "false"
            seen_success.add(bool(row["success"]))
            lines.append(f'aec_api_key_calls_total{{success="{label}"}} {int(row["n"])}')
        for needed in (True, False):
            if needed not in seen_success:
                label = "true" if needed else "false"
                lines.append(f'aec_api_key_calls_total{{success="{label}"}} 0')

        # Search query rate — useful for catching a bot that's
        # hammering /search.
        search_row = (
            (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) AS n
                        FROM search_queries
                        WHERE created_at > NOW() - INTERVAL '5 minutes'
                        """
                    )
                )
            )
            .mappings()
            .one()
        )
        lines.append("# HELP aec_search_queries_total Search queries logged in the last 5 minutes.")
        lines.append("# TYPE aec_search_queries_total gauge")
        lines.append(f"aec_search_queries_total {int(search_row['n'] or 0)}")

        # Audit-event rate — non-zero is good; sudden zero on a busy
        # platform means the audit hook is broken.
        audit_row = (
            (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) AS n
                        FROM audit_events
                        WHERE created_at > NOW() - INTERVAL '5 minutes'
                        """
                    )
                )
            )
            .mappings()
            .one()
        )
        lines.append("# HELP aec_audit_events_total Audit events written in the last 5 minutes.")
        lines.append("# TYPE aec_audit_events_total gauge")
        lines.append(f"aec_audit_events_total {int(audit_row['n'] or 0)}")

    # Trailing newline — the spec is loose but Prometheus's parser
    # is happier with one and some scrapers complain without.
    return "\n".join(lines) + "\n"


def _escape_label(value: str) -> str:
    """Prometheus label values escape `\\`, `"`, and newlines. Status
    strings are bounded to a small set, but this helper is here so
    a future label off user-controlled data doesn't break the parse."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
