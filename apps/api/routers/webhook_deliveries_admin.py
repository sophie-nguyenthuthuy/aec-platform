"""Platform-admin endpoints for cross-tenant webhook delivery telemetry.

Distinct from `routers/webhooks.py` — that router serves per-org
customer-facing endpoints (`POST /api/v1/webhooks/subscriptions`,
`GET /api/v1/webhooks/deliveries` for one org's deliveries). THIS
router is the platform-ops view: cross-tenant, admin-role-gated,
read-only.

Lives in its OWN file (not appended to `routers/admin.py`) for the
same reason the model lives in its own file: the revert pattern
targets `routers/admin.py` specifically, and a separate router
file dodges that.

Two endpoints, both gated to the `admin` role and using
`AdminSessionFactory` for cross-tenant visibility:

  * `GET /api/v1/admin/webhook-deliveries` — paginated raw rows
    for forensic drill-down. Filters: `event_type`, `status`
    (pending/in_flight/delivered/failed), `organization_id`,
    `subscription_id`. The status filter is the most-used —
    "show me only failures across the platform" is the primary
    triage view.

  * `GET /api/v1/admin/webhook-deliveries/summary` — per-event-type
    rollup over a configurable window. Drives the dashboard's
    summary cards.

Schemas live in `schemas/webhook_deliveries.py` (also a new file).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text

from core.envelope import ok
from db.session import AdminSessionFactory
from middleware.auth import AuthContext, require_role
from models.webhooks import WebhookDelivery
from schemas.webhook_deliveries import (
    WebhookDeliveriesSummaryRow,
    WebhookDeliveryAdminDetailOut,
    WebhookDeliveryAdminOut,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# Allowed status values — pinned here so a typo on the query string
# fails fast rather than returning zero rows silently. Mirrors the
# state-machine constants pinned in
# `tests/test_webhook_outbox_state_machine_pin.py`.
_ALLOWED_STATUSES = ("pending", "in_flight", "delivered", "failed")


@router.get("/webhook-deliveries")
async def list_webhook_deliveries(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
    event_type: str | None = Query(
        default=None,
        description="Filter to one event type (e.g. 'rfq.created')",
    ),
    status: str | None = Query(
        default=None,
        description=f"Filter to one status: one of {_ALLOWED_STATUSES}",
    ),
    organization_id: UUID | None = Query(
        default=None,
        description="Filter to one organization (cross-tenant drill-down)",
    ),
    subscription_id: UUID | None = Query(
        default=None,
        description="Filter to one subscription (per-receiver health view)",
    ),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Recent N webhook deliveries across all orgs, optionally filtered.

    Index-friendly: the `(status, next_retry_at)` index from migration
    0025 covers the `WHERE status = ...` branch (the most common
    triage filter). Other filters compose on top via range scans
    over the resulting subset.

    `payload` is NOT returned — admin telemetry view shouldn't expose
    customer payload data cross-tenant by default. If a forensic
    investigation needs the payload, query the row by id directly
    against the DB.
    """
    # Validate status against the allowed set so a typo (`Failed`,
    # `pending_retry`) returns 400 rather than zero rows silently.
    if status is not None and status not in _ALLOWED_STATUSES:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=(f"Invalid status {status!r}; must be one of {_ALLOWED_STATUSES}"),
        )

    stmt = select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(limit)
    if event_type:
        stmt = stmt.where(WebhookDelivery.event_type == event_type)
    if status:
        stmt = stmt.where(WebhookDelivery.status == status)
    if organization_id:
        stmt = stmt.where(WebhookDelivery.organization_id == organization_id)
    if subscription_id:
        stmt = stmt.where(WebhookDelivery.subscription_id == subscription_id)

    async with AdminSessionFactory() as session:
        rows = (await session.execute(stmt)).scalars().all()

    return ok([WebhookDeliveryAdminOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get("/webhook-deliveries/summary")
async def webhook_deliveries_summary(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
    days: int = Query(default=7, ge=1, le=90),
):
    """Per-event-type rollup over the last `days` days.

    Drives the dashboard's summary cards. Sorted by delivery rate
    ASC NULLS LAST so the event types in the worst shape surface
    first.

    `distinct_orgs` and `distinct_subscriptions` ride along so ops
    can tell "every org's webhook is broken" (high distinct count)
    apart from "one customer's receiver is misconfigured" (count=1).

    Raw SQL because we need:
      * Multiple conditional aggregates (`SUM(CASE WHEN ... THEN 1)`).
      * `DISTINCT ON (event_type)` for the last-failure breadcrumb.
      * `COUNT(DISTINCT org_id)` for the platform-vs-tenant
        discriminator.

    The `(status, next_retry_at)` index covers the bulk filter; the
    `(organization_id, created_at)` index covers the time-window
    side. Both already exist (migration 0025).

    `delivered_rate` is `NULL` when the window had zero attempts
    for that event type. Distinct from `0.0` (every attempt failed).
    """
    sql = text(
        """
        WITH recent AS (
            SELECT id, event_type, status, organization_id,
                   subscription_id, error_message, response_status,
                   created_at
            FROM webhook_deliveries
            WHERE created_at >= now() - make_interval(days := :days)
        ),
        last_failures AS (
            -- One row per event_type: the most recent failed
            -- attempt within the window. DISTINCT ON keeps it
            -- index-friendly via the (event_type, created_at DESC)
            -- ordering on the resulting heap.
            SELECT DISTINCT ON (event_type)
                event_type,
                created_at AS failed_at,
                error_message
            FROM recent
            WHERE status = 'failed'
            ORDER BY event_type, created_at DESC
        )
        SELECT
            r.event_type                                              AS event_type,
            COUNT(*)                                                  AS total_attempts,
            SUM(CASE WHEN r.status = 'delivered' THEN 1 ELSE 0 END)   AS delivered_count,
            SUM(CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END)      AS failed_count,
            SUM(CASE WHEN r.status IN ('pending', 'in_flight') THEN 1 ELSE 0 END)
                                                                      AS pending_count,
            -- delivered_rate: delivered / (delivered + failed). We
            -- exclude pending/in_flight from the denominator so a
            -- backlog of unsent rows doesn't depress the rate.
            -- NULL when (delivered + failed) is zero — "no data"
            -- as distinct from "0% delivered."
            (
                SUM(CASE WHEN r.status = 'delivered' THEN 1 ELSE 0 END)::float
                / NULLIF(
                    SUM(
                        CASE WHEN r.status IN ('delivered', 'failed') THEN 1 ELSE 0 END
                    ),
                    0
                )
            )                                                         AS delivered_rate,
            MAX(r.created_at)                                         AS last_attempt_at,
            lf.failed_at                                              AS last_failure_at,
            lf.error_message                                          AS last_failure_message,
            COUNT(DISTINCT r.organization_id)                         AS distinct_orgs,
            COUNT(DISTINCT r.subscription_id)                         AS distinct_subscriptions
        FROM recent r
        LEFT JOIN last_failures lf ON lf.event_type = r.event_type
        GROUP BY r.event_type, lf.failed_at, lf.error_message
        ORDER BY delivered_rate ASC NULLS LAST, r.event_type ASC
        """
    )

    async with AdminSessionFactory() as session:
        rows = (await session.execute(sql, {"days": days})).mappings().all()

    return ok([WebhookDeliveriesSummaryRow.model_validate(dict(r)).model_dump(mode="json") for r in rows])


# ----------------------------------------------------------------------
# Detail endpoint — MUST be declared AFTER `/summary` above.
#
# FastAPI matches routes in declaration order. If we put `/{delivery_id}`
# first, a `GET /api/v1/admin/webhook-deliveries/summary` request would
# bind `delivery_id="summary"` and try to UUID-parse it (4xx surface
# instead of the intended summary endpoint). Pinning the order is part
# of the contract — see `tests/test_webhook_deliveries_admin_surface_pin.py`.
# ----------------------------------------------------------------------


@router.get("/webhook-deliveries/{delivery_id}")
async def get_webhook_delivery_detail(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
    delivery_id: UUID,
):
    """One delivery's full forensic detail — payload, latest response,
    retry breadcrumb. Drives the `/admin/webhook-deliveries/[id]`
    drilldown page.

    Distinct from the list endpoint specifically because of `payload`:
    cross-tenant ops shouldn't see every customer's payload while
    skimming a 50-row triage table, but an admin investigating ONE
    specific failed delivery has a legitimate need ("what did we
    actually send the receiver?"). Concentrating payload exposure
    in the by-id path means:

      * The list query stays cheap (no JSONB deserialisation per row).
      * The audit trail of "who looked at which payload" is implicit
        in the URL pattern — easy to grep in access logs.

    404 with `webhook_delivery_not_found` so the frontend's drilldown
    can render its retention-prune copy ("row may have been pruned
    after 30 days"). The literal string is matched by the frontend's
    `notFound` discriminator (`msg.includes("not_found")`) — pin so
    a refactor doesn't silently break the friendly empty state.
    """
    from fastapi import HTTPException

    async with AdminSessionFactory() as session:
        row = await session.get(WebhookDelivery, delivery_id)

    if row is None:
        raise HTTPException(status_code=404, detail="webhook_delivery_not_found")

    return ok(WebhookDeliveryAdminDetailOut.model_validate(row).model_dump(mode="json"))
