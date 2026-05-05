"""Snapshot tests for the integrator-platform surface.

This is the cousin of `test_codeguard_surface_snapshot.py`, applied to a
different cluster of code. It pins the exact set of fields, parameters,
and registered routes that the API-key + sandbox + ops surfaces depend
on — every one of which has been silently rolled back by an aggressive
external linter / reformat pass mid-session, multiple times.

What this test catches at commit time (via the pre-commit hook in
`.pre-commit-config.yaml`):

  * `core.config.Settings.metrics_token` field disappears.
  * `middleware.auth.AuthContext.api_key_mode` / `api_key_id` fields
    disappear.
  * `services.api_keys.mint_key(..., mode=...)` parameter disappears,
    or `KEY_MODES` constant disappears.
  * `services.api_keys.verify_key` `RETURNING` drops the `mode` column.
  * `routers.api_keys.ApiKeyCreate.mode` field disappears, or the
    `create_api_key` handler stops passing `mode=` to `mint_key`.
  * `routers.ops` stops being included in the FastAPI app, or the
    `/healthz`, `/readyz`, `/metrics` routes go missing.
  * `routers.webhooks` stops exposing `GET /deliveries/dead-letter`.
  * `routers.admin` stops exposing `GET /api-keys/top` or
    `GET /api-keys/{id}/usage`.
  * `schemas.webhooks.WebhookDeliveryOut` drops `subscription_id`.

Each of these has been a real failure in this codebase. The fix is the
same in every case — re-apply the field/route/parameter — but the cost
of finding the regression late (after multiple rounds of "why is this
test failing?") is high. Pin them all here so the very next commit goes
red and the rollback is fixed before the broken state propagates.

How to extend: when adding a new field/route to the integrator surface
that you want guarded, add an assertion below + the file-pattern to
the pre-commit `files:` regex.
"""

from __future__ import annotations

import inspect

# ---------- Settings -----------------------------------------------------


def test_settings_has_metrics_token_field():
    """`Settings.metrics_token` gates `/metrics` in production. Without
    it, the route either errors at boot or (worse) silently serves
    open without the AEC_METRICS_TOKEN gate, leaking ops data."""
    from core.config import Settings

    fields = Settings.model_fields
    assert "metrics_token" in fields, (
        "core.config.Settings.metrics_token has been rolled back. "
        "Re-apply: `metrics_token: str | None = Field(default=None, "
        "validation_alias='AEC_METRICS_TOKEN')`."
    )
    field = fields["metrics_token"]
    assert field.default is None, "metrics_token should default to None (open in dev)"


# ---------- AuthContext --------------------------------------------------


def test_auth_context_has_api_key_mode_and_id():
    """`AuthContext.api_key_mode` flows from the api_keys row → handlers
    that branch on `is_test_mode(auth)`. Default 'live' for user-JWT
    callers. `api_key_id` is the api_keys.id when role=='api_key'."""
    from middleware.auth import AuthContext

    fields = {f.name for f in AuthContext.__dataclass_fields__.values()}
    assert "api_key_mode" in fields, (
        "AuthContext.api_key_mode has been rolled back. Re-apply: `api_key_mode: str = 'live'` on the dataclass."
    )
    assert "api_key_id" in fields, (
        "AuthContext.api_key_id has been rolled back. Re-apply: `api_key_id: UUID | None = None` on the dataclass."
    )

    # Smoke-test the constructor with positional + default kwargs to
    # catch a refactor that reorders the fields and breaks every existing
    # `AuthContext(...)` callsite.
    from uuid import UUID

    ctx = AuthContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        organization_id=UUID("00000000-0000-0000-0000-000000000002"),
        role="member",
        email="x@y.z",
    )
    assert ctx.api_key_mode == "live", "default api_key_mode must be 'live'"
    assert ctx.api_key_id is None, "default api_key_id must be None"


# ---------- services.api_keys -------------------------------------------


def test_mint_key_accepts_mode_parameter():
    """`mint_key(..., mode='live'|'test')` is the only way the sandbox
    layer differentiates partner test traffic from real traffic. If the
    parameter disappears, sandbox keys stop working without any
    immediate visible failure (the row defaults to 'live' DB-side)."""
    from services.api_keys import mint_key

    sig = inspect.signature(mint_key)
    assert "mode" in sig.parameters, (
        "services.api_keys.mint_key has lost its `mode` parameter. "
        "Re-apply: `mode: str = 'live'` kwarg + KEY_MODES validation + "
        "INSERT bound param + RETURNING column."
    )
    assert sig.parameters["mode"].default == "live", "mint_key.mode default must be 'live' for backward compat"


def test_key_modes_constant_present():
    """`KEY_MODES` is the closed vocabulary the service-side check uses.
    Mirrors the DB CHECK constraint from migration 0033_api_keys_mode."""
    from services.api_keys import KEY_MODES

    assert frozenset({"live", "test"}) == KEY_MODES, (
        f"services.api_keys.KEY_MODES drifted: expected {{'live','test'}}, "
        f"got {set(KEY_MODES)}. Sync with migration 0033 + the DB CHECK."
    )


def test_verify_key_returning_includes_mode():
    """Without `mode` in the RETURNING clause, `_api_key_auth` reads
    None → AuthContext.api_key_mode falls back to 'live' → test-mode
    keys silently route to real org data. Pin the SQL string."""
    import services.api_keys as svc

    src = inspect.getsource(svc.verify_key)
    assert "name, prefix, mode" in src or "name,\n                      prefix,\n                      mode" in src, (
        "services.api_keys.verify_key is missing `mode` in its RETURNING "
        "clause. Re-apply: `RETURNING id, organization_id, scopes, "
        "rate_limit_per_minute, name, prefix, mode`."
    )


# ---------- routers.api_keys --------------------------------------------


def test_api_key_create_payload_has_mode_field():
    """`ApiKeyCreate.mode` is the wire-level field. Pydantic regex
    enforces the closed vocabulary on the wire so a typo from a partner
    (e.g. 'staging') gets a 422 before the service layer."""
    from routers.api_keys import ApiKeyCreate

    fields = ApiKeyCreate.model_fields
    assert "mode" in fields, (
        "routers.api_keys.ApiKeyCreate.mode has been rolled back. "
        "Re-apply: `mode: str = Field(default='live', pattern='^(live|test)$')`."
    )


def test_create_api_key_passes_mode_to_service():
    """The handler must thread `mode=payload.mode` into `mint_key`. If
    the kwarg is dropped, the field exists on the wire but every key
    is silently minted as 'live'."""
    from routers import api_keys as router_module

    src = inspect.getsource(router_module.create_api_key)
    assert "mode=payload.mode" in src, (
        "routers.api_keys.create_api_key is no longer passing `mode=` "
        "to mint_key. Re-apply the kwarg in the mint_key call."
    )


# ---------- main.py: ops router included --------------------------------


def test_ops_router_is_mounted_in_app():
    """`/healthz`, `/readyz`, `/metrics` come from `routers.ops`. A
    rollback that drops `app.include_router(ops_router.router)` from
    main.py is invisible until a k8s probe fails (or Prometheus scrape
    returns 404 in prod). Pin by walking the live route table."""
    from main import app

    paths = {route.path for route in app.routes}
    for required in ("/healthz", "/readyz", "/metrics"):
        assert required in paths, (
            f"FastAPI app is missing route {required!r}. The likely cause is "
            "`from routers import ops as ops_router` or "
            "`app.include_router(ops_router.router)` having been rolled back "
            "from apps/api/main.py."
        )


# ---------- routers.webhooks: dead-letter + subscription_id -------------


def test_webhook_delivery_schema_has_subscription_id():
    """`WebhookDeliveryOut.subscription_id` is what the dead-letter
    dashboard uses to link each row back to its subscription page."""
    from schemas.webhooks import WebhookDeliveryOut

    fields = WebhookDeliveryOut.model_fields
    assert "subscription_id" in fields, (
        "schemas.webhooks.WebhookDeliveryOut.subscription_id has been rolled back. Re-apply on the BaseModel."
    )


def test_dead_letter_route_registered():
    """`GET /api/v1/webhooks/deliveries/dead-letter` is the cross-
    subscription failed-delivery feed. The frontend's
    `useDeadLetterDeliveries` hook breaks if this disappears."""
    from main import app

    paths = {(list(route.methods)[0], route.path) for route in app.routes if hasattr(route, "methods")}
    assert ("GET", "/api/v1/webhooks/deliveries/dead-letter") in paths, (
        "GET /api/v1/webhooks/deliveries/dead-letter has been rolled back "
        "from routers/webhooks.py. Re-apply the @router.get decorator + "
        "the org-scoped status='failed' SELECT."
    )


# ---------- routers.admin: api-keys usage telemetry --------------------


def test_admin_api_keys_top_route_registered():
    """`GET /api/v1/admin/api-keys/top` drives the cross-org usage
    leaderboard at `/admin/api-usage`. Frontend's `useTopApiKeys` hook
    breaks if this is dropped."""
    from main import app

    paths = {route.path for route in app.routes}
    assert "/api/v1/admin/api-keys/top" in paths, (
        "GET /api/v1/admin/api-keys/top has been rolled back from "
        "routers/admin.py. Re-apply the admin-gated handler that calls "
        "services.api_keys.usage_top_keys."
    )


def test_admin_api_key_usage_route_registered():
    """Per-key drilldown for the leaderboard. `useApiKeyUsage` hook
    depends on this."""
    from main import app

    paths = {route.path for route in app.routes}
    assert "/api/v1/admin/api-keys/{key_id}/usage" in paths, (
        "GET /api/v1/admin/api-keys/{key_id}/usage has been rolled back "
        "from routers/admin.py. Re-apply with services.api_keys.usage_for_key."
    )
