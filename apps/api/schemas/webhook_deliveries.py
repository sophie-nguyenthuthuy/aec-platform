"""Pydantic schemas for the platform-admin webhook-deliveries surface.

Lives in its OWN file (not `schemas/admin.py` or `schemas/webhooks.py`)
so the upstream-revert pattern targeting either of those doesn't take
this surface offline. The matching admin router
(`routers/webhook_deliveries_admin.py`) imports from here directly;
no re-export through `schemas/admin.py`.

Distinct from `schemas/webhooks.py`: those models are the per-org
customer-facing webhook subscription endpoints. THIS file is the
cross-tenant platform-ops view used by `/admin/webhook-deliveries`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WebhookDeliveryAdminOut(BaseModel):
    """One row from `webhook_deliveries`, projected for the admin
    forensic table. Mirrors `models.webhooks.WebhookDelivery` but
    with two ergonomics:

      * `payload` is intentionally NOT included — admin telemetry
        view, not a debugging-by-payload-replay tool. The payload
        is the customer's data and shouldn't show up in cross-tenant
        ops surfaces by default.

      * `response_body_snippet` IS included — that's what tells ops
        "Slack returned `channel_not_found`" or "buyer-side webhook
        returned 502 Bad Gateway."
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    subscription_id: UUID
    event_type: str
    status: str  # "pending" | "in_flight" | "delivered" | "failed"
    attempt_count: int
    response_status: int | None = None
    response_body_snippet: str | None = None
    error_message: str | None = None
    next_retry_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime


class WebhookDeliveryAdminDetailOut(WebhookDeliveryAdminOut):
    """One delivery's full detail, including the customer payload.

    Distinct from `WebhookDeliveryAdminOut` because the LIST endpoint
    deliberately omits `payload` (cross-tenant ops shouldn't browse
    every row's payload by default — too easy to expose customer
    data while skimming a 50-row table). The DETAIL endpoint includes
    it because an admin drilling into ONE specific failed delivery
    has a legitimate forensic need: "what did we actually send?
    why did the receiver reject it?"

    Same fields as the list shape PLUS:
      * `payload` — the JSON body that went to the receiver. Used
        to copy-paste into curl for a manual replay.
    """

    payload: dict[str, object]


class WebhookDeliveriesSummaryRow(BaseModel):
    """Per-`event_type` rollup for the platform admin dashboard.

    Cross-tenant: the row groups by event-type alone, NOT by
    `(organization_id, event_type)`. Rationale: when a buyer-side
    webhook receiver starts 502'ing, it usually breaks for ALL
    orgs subscribed to that event type (the receiver is the same
    URL pattern); the per-event-type rollup surfaces that pattern
    immediately. Per-org drill-down lives behind the row's
    "view rows" link in the UI.

    `delivered_rate` is `None` when the window had zero attempts
    (no data) — distinct from `0.0` (every attempt failed). The
    frontend renders these differently.
    """

    event_type: str
    total_attempts: int
    delivered_count: int
    failed_count: int
    pending_count: int
    delivered_rate: float | None = Field(default=None, ge=0, le=1)
    last_attempt_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_message: str | None = None
    distinct_orgs: int = 0
    distinct_subscriptions: int = 0
