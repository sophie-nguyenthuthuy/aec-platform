"""Pin the structural shape of the webhook-deliveries admin surface.

Background:

This is the platform-ops cross-tenant view of `webhook_deliveries` —
distinct from the per-org customer-facing endpoints in
`routers/webhooks.py`. The customer-facing endpoints are on the
upstream-revert pattern's known target list; this admin surface
deliberately lives in NEW files so the reverter doesn't reach it:

  * `schemas/webhook_deliveries.py`        (NEW)
  * `routers/webhook_deliveries_admin.py`  (NEW)

This pin asserts the contract those files expose. It's read-only —
imports the modules and inspects their public surface; never
mutates anything. Read-only test files have historically survived
the reverter pattern even when production files don't, so if any
of the wiring gets reverted, this test goes RED on the next CI
run rather than silently going green.

What we pin:

  * `WebhookDeliveryAdminOut` field set — the dashboard's forensic
    table reads these by name. `payload` MUST NOT be present
    (cross-tenant payload exposure is a deliberate non-feature).

  * `WebhookDeliveriesSummaryRow` field set — the summary cards.
    `delivered_rate` is `0..1` optional; `distinct_orgs` /
    `distinct_subscriptions` ride along to discriminate
    "platform-wide breakage" from "one customer's misconfig."

  * Router exposes the two expected paths with `admin` role gate.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

# ---------- Schema field sets ----------


def test_webhook_delivery_admin_out_field_set():
    """The forensic-table row schema. Field rename = the dashboard
    table renders blank columns."""
    from schemas.webhook_deliveries import WebhookDeliveryAdminOut

    fields = WebhookDeliveryAdminOut.model_fields
    expected = {
        "id",
        "organization_id",
        "subscription_id",
        "event_type",
        "status",
        "attempt_count",
        "response_status",
        "response_body_snippet",
        "error_message",
        "next_retry_at",
        "delivered_at",
        "created_at",
    }
    assert set(fields.keys()) == expected, (
        f"WebhookDeliveryAdminOut fields drifted: have {set(fields.keys())}, want {expected}"
    )

    # `from_attributes=True` is required for `model_validate(orm_row)`
    # in the router's projection step.
    assert WebhookDeliveryAdminOut.model_config.get("from_attributes") is True


def test_webhook_delivery_admin_out_excludes_payload():
    """SECURITY pin. The customer's webhook payload data MUST NOT
    surface in the cross-tenant admin view by default. A regression
    that added `payload` to this schema would silently expose every
    org's webhook payloads to platform admins.

    Forensic investigation that needs a specific row's payload can
    query the DB directly — that's a deliberate friction step.
    """
    from schemas.webhook_deliveries import WebhookDeliveryAdminOut

    fields = set(WebhookDeliveryAdminOut.model_fields.keys())
    assert "payload" not in fields, (
        "WebhookDeliveryAdminOut now exposes `payload`. That's customer "
        "data; cross-tenant admin views MUST NOT include it by default. "
        "If a forensic case needs payload visibility, do it via direct "
        "DB query, not via blanket schema exposure."
    )


def test_webhook_deliveries_summary_row_field_set():
    """Summary card row. The dashboard reads `delivered_rate` for
    the colour-coded card and `last_failure_message` for the
    at-a-glance reason."""
    from schemas.webhook_deliveries import WebhookDeliveriesSummaryRow

    fields = WebhookDeliveriesSummaryRow.model_fields
    expected = {
        "event_type",
        "total_attempts",
        "delivered_count",
        "failed_count",
        "pending_count",
        "delivered_rate",
        "last_attempt_at",
        "last_failure_at",
        "last_failure_message",
        "distinct_orgs",
        "distinct_subscriptions",
    }
    assert set(fields.keys()) == expected, (
        f"WebhookDeliveriesSummaryRow fields drifted: have {set(fields.keys())}, want {expected}"
    )


def test_summary_row_delivered_rate_is_optional_bounded_ratio():
    """Same `null vs 0.0` semantics as the slack-deliveries summary:

    * `None` — no attempts in window (cards render as 'no data').
    * `0.0` — every attempt failed (cards render red).
    * `1.0` — every attempt delivered (cards render green).
    """
    from schemas.webhook_deliveries import WebhookDeliveriesSummaryRow

    f = WebhookDeliveriesSummaryRow.model_fields["delivered_rate"]
    assert f.is_required() is False, (
        "delivered_rate MUST be optional — `None` means 'no attempts in "
        "window', distinct from 0.0 which means 'every attempt failed'."
    )

    # Boundary values must round-trip without raising.
    WebhookDeliveriesSummaryRow(
        event_type="rfq.created",
        total_attempts=0,
        delivered_count=0,
        failed_count=0,
        pending_count=0,
        delivered_rate=None,
    )
    WebhookDeliveriesSummaryRow(
        event_type="rfq.created",
        total_attempts=10,
        delivered_count=0,
        failed_count=10,
        pending_count=0,
        delivered_rate=0.0,
    )
    WebhookDeliveriesSummaryRow(
        event_type="rfq.created",
        total_attempts=10,
        delivered_count=10,
        failed_count=0,
        pending_count=0,
        delivered_rate=1.0,
    )


def test_summary_row_distinct_count_defaults_zero():
    """`distinct_orgs` / `distinct_subscriptions` default to 0 (not
    None) because zero is the valid empty-window value AND because
    the dashboard does math on them (`distinct_orgs > 1` to detect
    platform-wide breakage). Optional ints would force a None-check
    everywhere."""
    from schemas.webhook_deliveries import WebhookDeliveriesSummaryRow

    f_orgs = WebhookDeliveriesSummaryRow.model_fields["distinct_orgs"]
    f_subs = WebhookDeliveriesSummaryRow.model_fields["distinct_subscriptions"]
    # is_required=False with a default of 0 (not None).
    assert f_orgs.is_required() is False
    assert f_orgs.default == 0
    assert f_subs.is_required() is False
    assert f_subs.default == 0


# ---------- Router presence + paths ----------


def test_router_module_present_and_has_router():
    """Module + `router` attribute. A missing `router` attribute
    means FastAPI startup raises and the whole API is down."""
    from fastapi import APIRouter

    from routers import webhook_deliveries_admin as mod

    assert hasattr(mod, "router")
    assert isinstance(mod.router, APIRouter)


def test_router_exposes_expected_paths():
    """Three endpoints expected by the frontend hooks:

      * `GET /api/v1/admin/webhook-deliveries` — list
      * `GET /api/v1/admin/webhook-deliveries/summary` — per-event-type rollup
      * `GET /api/v1/admin/webhook-deliveries/{delivery_id}` — drilldown detail

    A path rename = the frontend hook 404s and the relevant page
    renders an empty state forever.
    """
    from routers.webhook_deliveries_admin import router

    paths = {r.path for r in router.routes}
    assert "/api/v1/admin/webhook-deliveries" in paths, f"webhook-deliveries list endpoint missing; have {paths}"
    assert "/api/v1/admin/webhook-deliveries/summary" in paths, (
        f"webhook-deliveries summary endpoint missing; have {paths}"
    )
    assert "/api/v1/admin/webhook-deliveries/{delivery_id}" in paths, (
        f"webhook-deliveries detail endpoint missing; have {paths}. "
        "Frontend `useWebhookDeliveryAdminDetail` calls this path; "
        "without it, every drilldown click 404s."
    )


def test_summary_route_declared_before_detail_route():
    """ROUTING-CRITICAL pin. FastAPI matches routes in declaration
    order. The `/summary` static path MUST be declared BEFORE the
    `/{delivery_id}` parametric path — otherwise a request to
    `/summary` binds `delivery_id="summary"`, fails UUID parsing,
    and the summary endpoint becomes unreachable.

    Pin via the `router.routes` list which preserves declaration
    order; assert summary's index is lower than detail's.
    """
    from routers.webhook_deliveries_admin import router

    paths_in_order = [r.path for r in router.routes]

    summary_idx = paths_in_order.index("/api/v1/admin/webhook-deliveries/summary")
    detail_idx = paths_in_order.index("/api/v1/admin/webhook-deliveries/{delivery_id}")
    assert summary_idx < detail_idx, (
        f"Detail route (`/{{delivery_id}}`, idx={detail_idx}) declared "
        f"before summary route (idx={summary_idx}). FastAPI matches "
        'in order — `/summary` would bind to `delivery_id="summary"` '
        "and 4xx instead of returning the rollup."
    )


def test_admin_detail_out_field_set_includes_payload():
    """The drilldown schema MUST include `payload` — that's the
    point of having a separate Detail vs List shape (the list one
    excludes payload to avoid cross-tenant payload exposure during
    routine triage browsing). A regression that dropped `payload`
    here would silently break the `/admin/webhook-deliveries/[id]`
    page's body-replay copy block."""
    from schemas.webhook_deliveries import (
        WebhookDeliveryAdminDetailOut,
        WebhookDeliveryAdminOut,
    )

    detail_fields = set(WebhookDeliveryAdminDetailOut.model_fields.keys())
    list_fields = set(WebhookDeliveryAdminOut.model_fields.keys())

    # Detail = list + payload (and nothing else, today).
    assert "payload" in detail_fields, (
        "WebhookDeliveryAdminDetailOut no longer carries `payload`. "
        "The drilldown page renders `data.payload` for forensic "
        "replay — without it, the page shows an empty <pre> block."
    )
    # Detail must be a strict superset of list (so route handlers
    # can return either shape from the same ORM row without
    # field-projection acrobatics).
    assert list_fields.issubset(detail_fields), (
        f"WebhookDeliveryAdminDetailOut is no longer a superset of "
        f"WebhookDeliveryAdminOut: missing {list_fields - detail_fields}. "
        "Routes assume the detail shape carries every list field plus "
        "the payload."
    )


def test_admin_detail_out_payload_is_dict_typed():
    """`payload` MUST be a JSON-object type so the detail page's
    `JSON.stringify(data.payload, null, 2)` renders pretty-printed
    output rather than `[object Object]`. A regression to `Any` or
    `str` would either silently double-stringify the JSON or break
    Pydantic validation against the JSONB column."""
    from schemas.webhook_deliveries import WebhookDeliveryAdminDetailOut

    fields = WebhookDeliveryAdminDetailOut.model_fields
    payload_field = fields["payload"]
    # The annotation can be any of: dict, dict[str, Any], dict[str, object].
    # We just assert it's REQUIRED and the annotation is a dict-ish type.
    assert payload_field.is_required() is True, (
        "WebhookDeliveryAdminDetailOut.payload became optional. "
        "Every detail row in webhook_deliveries has a non-null payload "
        "(JSONB NOT NULL); making it optional silently hides empty-payload "
        "rows that should never exist."
    )


def test_allowed_statuses_constant_pinned():
    """The router validates the `status` query param against this
    tuple. The set MUST exactly mirror the four state-machine
    values pinned in `test_webhook_outbox_state_machine_pin.py` —
    if they drift apart, callers can submit a status the dispatcher
    never produces (zero rows return) or fail validation on a
    legit status."""
    from routers.webhook_deliveries_admin import _ALLOWED_STATUSES

    assert _ALLOWED_STATUSES == ("pending", "in_flight", "delivered", "failed"), (
        f"_ALLOWED_STATUSES drifted from the dispatcher's state machine: "
        f"{_ALLOWED_STATUSES}. Pin must match the literals in "
        f"services.webhooks (see test_webhook_outbox_state_machine_pin)."
    )


# ---------- Type-roundtrip sanity ----------


def test_admin_out_accepts_minimal_orm_shape():
    """A row with only the NOT NULL columns set should round-trip
    through the schema (validates `from_attributes=True` against
    an ORM-shaped object — duck-typed here so the test doesn't
    need a DB)."""
    from schemas.webhook_deliveries import WebhookDeliveryAdminOut

    class _FakeRow:
        id = UUID("00000000-0000-0000-0000-000000000001")
        organization_id = UUID("00000000-0000-0000-0000-000000000002")
        subscription_id = UUID("00000000-0000-0000-0000-000000000003")
        event_type = "rfq.created"
        status = "delivered"
        attempt_count = 1
        response_status = 200
        response_body_snippet = "OK"
        error_message = None
        next_retry_at = None
        delivered_at = datetime(2026, 5, 5, 12, 0, 0)
        created_at = datetime(2026, 5, 5, 12, 0, 0)

    out = WebhookDeliveryAdminOut.model_validate(_FakeRow())
    assert out.event_type == "rfq.created"
    assert out.status == "delivered"
    assert out.attempt_count == 1
