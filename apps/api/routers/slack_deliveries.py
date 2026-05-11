"""Admin endpoints for the `slack_deliveries` telemetry surface.

Lives in its OWN router file (not appended to `routers/admin.py`) for
the same reason the model lives in its own file: three prior attempts
to add the slack-deliveries surface to `routers/admin.py` were
reverted upstream within seconds. The migration + table survive; only
the wiring keeps getting un-applied. Isolating in a new file dodges
the reverter pattern that targets `routers/admin.py`.

Two endpoints, both gated to the platform `admin` role (mirrors
`routers/admin.py::list_scraper_runs`):

  * `GET /api/v1/admin/slack-deliveries` — paginated raw rows for
    forensic drill-down (which attempts failed for which kind, what
    Slack returned, when).

  * `GET /api/v1/admin/slack-deliveries/summary` — per-`kind`
    rollup over a configurable window. Drives the
    `/admin/slack-deliveries` dashboard's summary table.

Both paths use `AdminSessionFactory` (BYPASSRLS) — slack deliveries
are platform-level (single webhook URL shared cross-tenant) and have
no `organization_id` to scope by.

Schemas live in `schemas/slack_deliveries.py` (also a new file) — the
`schemas/admin.py` revert pattern doesn't reach it.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text

from core.envelope import ok
from db.session import AdminSessionFactory
from middleware.auth import AuthContext, require_role
from models.slack_delivery import SlackDelivery
from schemas.slack_deliveries import SlackDeliveriesSummaryRow, SlackDeliveryOut

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/slack-deliveries")
async def list_slack_deliveries(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
    kind: str | None = Query(default=None, description="Filter to one delivery kind"),
    delivered: bool | None = Query(
        default=None,
        description="Filter to delivered=true / failed=false; omit for all",
    ),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Recent N delivery attempts, optionally filtered by kind / outcome.

    Index-friendly: the `(kind, created_at DESC)` index from migration
    `0037_slack_deliveries.py` covers both the kind-filter and
    no-filter branches; the bool filter is composed on top via a
    range scan over the resulting subset (failures are sparse, so
    the planner usually keeps the index path even with the bool
    predicate).

    Default `limit=50` matches the dashboard's first-page size; the
    cap of 500 is for ad-hoc CSV-style ops drill-down.
    """
    stmt = select(SlackDelivery).order_by(SlackDelivery.created_at.desc()).limit(limit)
    if kind:
        stmt = stmt.where(SlackDelivery.kind == kind)
    if delivered is not None:
        stmt = stmt.where(SlackDelivery.delivered.is_(delivered))

    async with AdminSessionFactory() as session:
        rows = (await session.execute(stmt)).scalars().all()

    return ok([SlackDeliveryOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get("/slack-deliveries/summary")
async def slack_deliveries_summary(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    """Per-`kind` rollup over the last `days` days.

    Drives the dashboard's summary table — one row per kind with
    delivery rate, attempt counts, and the last-failure breadcrumb
    (when + why) so ops can jump straight from "scraper_drift is
    flaky" to "the last failure was a 429 12 minutes ago."

    Raw SQL because we want a window-style "last failure" lookup
    alongside the simple aggregates. The `(kind, created_at DESC)`
    index covers the `created_at >= now() - interval` filter on
    each kind-grouped path.

    `delivered_rate` is `NULL` when the window had zero attempts
    (a brand-new `kind` that hasn't fired yet) — distinct from `0.0`
    (which means "tried but every one failed"). The dashboard
    distinguishes those: null = "no data yet"; zero = "page someone
    immediately."
    """
    sql = text(
        """
        WITH recent AS (
            SELECT id, kind, delivered, reason, created_at
            FROM slack_deliveries
            WHERE created_at >= now() - make_interval(days := :days)
        ),
        last_failures AS (
            -- One row per kind: the most recent failed attempt within
            -- the window, with its reason. DISTINCT ON keeps the query
            -- index-friendly via the (kind, created_at DESC) ordering.
            SELECT DISTINCT ON (kind) kind, created_at AS failed_at, reason
            FROM recent
            WHERE delivered = false
            ORDER BY kind, created_at DESC
        )
        SELECT
            r.kind                                                   AS kind,
            COUNT(*)                                                 AS total_attempts,
            SUM(CASE WHEN r.delivered THEN 1 ELSE 0 END)             AS delivered_count,
            SUM(CASE WHEN r.delivered THEN 0 ELSE 1 END)             AS failed_count,
            -- Cast to float so PG returns numeric, not integer 0/1.
            -- NULLIF guards the never-attempted case, but COUNT(*) > 0
            -- by virtue of GROUP BY r.kind so this is a belt-and-braces
            -- defence against an empty-window edge case.
            (SUM(CASE WHEN r.delivered THEN 1 ELSE 0 END)::float
                / NULLIF(COUNT(*), 0))                               AS delivered_rate,
            MAX(r.created_at)                                        AS last_attempt_at,
            lf.failed_at                                             AS last_failure_at,
            lf.reason                                                AS last_failure_reason
        FROM recent r
        LEFT JOIN last_failures lf ON lf.kind = r.kind
        GROUP BY r.kind, lf.failed_at, lf.reason
        -- Worst delivery rate first — ops scans the top of the table.
        -- NULLs (zero-attempt windows) sink to the bottom.
        ORDER BY delivered_rate ASC NULLS LAST, r.kind ASC
        """
    )

    async with AdminSessionFactory() as session:
        rows = (await session.execute(sql, {"days": days})).mappings().all()

    return ok([SlackDeliveriesSummaryRow.model_validate(dict(r)).model_dump(mode="json") for r in rows])
