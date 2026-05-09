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


# ---------- Per-project RBAC (api_keys.project_ids) ---------------------
#
# Pinned because every layer of this feature has been rolled back at
# least once during development. Without all four pieces, a
# project-scoped key either silently grants org-wide access (the field
# is dark) or 403s every legitimate request (the field exists but the
# handler doesn't read it).


def test_auth_context_has_api_key_project_ids():
    """`AuthContext.api_key_project_ids` is the in-memory copy of the
    api_keys.project_ids row column. `require_project_scope` reads it
    on every gated request — silently rolling it back means the
    dependency falls back to "all projects" and the partner gets
    org-wide access from a key meant to be project-scoped."""
    from middleware.auth import AuthContext

    fields = {f.name for f in AuthContext.__dataclass_fields__.values()}
    assert "api_key_project_ids" in fields, (
        "AuthContext.api_key_project_ids has been rolled back. "
        "Re-apply: `api_key_project_ids: tuple[UUID, ...] = ()` "
        "on the dataclass."
    )

    # Default must be empty tuple — that's the back-compat sentinel
    # meaning "all projects". Anything else changes the security
    # posture for every existing AuthContext callsite.
    from uuid import UUID

    ctx = AuthContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        organization_id=UUID("00000000-0000-0000-0000-000000000002"),
        role="member",
        email="x@y.z",
    )
    assert ctx.api_key_project_ids == (), "default api_key_project_ids must be () — empty = 'all projects'"


def test_mint_key_accepts_project_ids_parameter():
    """`mint_key(..., project_ids=[...])` is the only way the API gets
    a project-scoped key into the DB. If the parameter disappears,
    the field exists in the request body but never lands in the row,
    and the partner's "scoped key" silently has org-wide access."""
    from services.api_keys import mint_key

    sig = inspect.signature(mint_key)
    assert "project_ids" in sig.parameters, (
        "services.api_keys.mint_key has lost its `project_ids` parameter. "
        "Re-apply: `project_ids: list[UUID] | None = None` kwarg + "
        "INSERT bound param + RETURNING column."
    )


def test_verify_key_returning_includes_project_ids():
    """Without `project_ids` in the RETURNING clause, `_api_key_auth`
    reads None → AuthContext.api_key_project_ids stays at the default
    () → `require_project_scope` falls back to "all projects" → the
    project-scoped key effectively has org-wide access."""
    import services.api_keys as svc

    src = inspect.getsource(svc.verify_key)
    assert "project_ids" in src, (
        "services.api_keys.verify_key is missing `project_ids` in its "
        "RETURNING clause. Re-apply with the `mode, project_ids` columns."
    )


def test_api_key_create_payload_has_project_ids_field():
    """`ApiKeyCreate.project_ids` is the wire-level field. Without it
    the partner's UI passes the list but pydantic strips it before the
    handler ever sees it."""
    from routers.api_keys import ApiKeyCreate

    fields = ApiKeyCreate.model_fields
    assert "project_ids" in fields, (
        "routers.api_keys.ApiKeyCreate.project_ids has been rolled back. "
        "Re-apply: `project_ids: list[UUID] = Field(default_factory=list)`."
    )


def test_create_api_key_passes_project_ids_to_service():
    """The handler must thread `project_ids=payload.project_ids` into
    `mint_key`. If the kwarg is dropped, the field exists on the wire
    but every key is silently minted with no per-project scoping."""
    from routers import api_keys as router_module

    src = inspect.getsource(router_module.create_api_key)
    assert "project_ids=payload.project_ids" in src, (
        "routers.api_keys.create_api_key is no longer passing "
        "`project_ids=` to mint_key. Re-apply the kwarg in the call."
    )


def test_require_project_scope_dependency_exists():
    """`middleware.api_key_auth.require_project_scope` is the gate
    that reads `auth.api_key_project_ids` and 403s requests outside
    the allowlist. Without this dependency, project-scoped keys are
    purely cosmetic — the column is set, but no route reads it."""
    from middleware.api_key_auth import require_project_scope

    # The dependency factory should accept the param name and return
    # a callable. Smoke-test the shape; the actual gate logic lives
    # in the closure and is exercised by test_api_keys.py.
    dep = require_project_scope("project_id")
    assert callable(dep), (
        "require_project_scope() should return a callable dependency. "
        "Re-apply the factory in middleware/api_key_auth.py."
    )


def test_has_project_access_helper_exists():
    """`services.api_keys.has_project_access` is the pure helper that
    `require_project_scope` calls. Pinned separately so a refactor that
    inlines the check into the dependency without preserving the helper
    breaks here, not at the next test that imports it."""
    from services.api_keys import has_project_access

    # Empty allowlist = "all projects" (back-compat sentinel).
    assert has_project_access([], "any-uuid") is True
    # Non-empty = closed allowlist.
    assert has_project_access(["a"], "a") is True
    assert has_project_access(["a"], "b") is False


# ---------- routers.slack_deliveries: telemetry surface ----------------
#
# The slack_deliveries router lives in its own file specifically to
# dodge the rollback pattern that targets routers/admin.py — see
# `tests/test_slack_deliveries_surface_pin.py` for the full history.
# That separate file pins the model / schema / router / service shape;
# the assertion below pins the missing piece — whether the router is
# actually MOUNTED in main.py and the routes are reachable.


def test_slack_deliveries_router_mounted():
    """If main.py loses the import or the include_router line, every
    other layer is in place but the dashboard 404s with no obvious
    cause."""
    from main import app

    paths = {route.path for route in app.routes}
    for required in (
        "/api/v1/admin/slack-deliveries",
        "/api/v1/admin/slack-deliveries/summary",
    ):
        assert required in paths, (
            f"FastAPI app is missing route {required!r}. The likely "
            "cause is `from routers import slack_deliveries as "
            "slack_deliveries_router` or "
            "`app.include_router(slack_deliveries_router.router)` "
            "having been rolled back from apps/api/main.py."
        )


def test_webhook_deliveries_admin_router_mounted():
    """Sister to slack_deliveries — `routers/webhook_deliveries_admin.py`
    is the cross-tenant platform-ops view of webhook outbox health.
    Lives in its own file (same dodge-the-admin.py-rollback rationale)
    so the assertion here is "the router survived being mounted in
    main.py." The frontend admin dashboard at
    `/admin/webhook-deliveries` 404s if any route disappears.

    The third route (`/{delivery_id}`) drives the drilldown page —
    the list view's row click links straight to it, so a revert
    breaks navigation without obvious failure (the row stays visible
    but the link 404s)."""
    from main import app

    paths = {route.path for route in app.routes}
    for required in (
        "/api/v1/admin/webhook-deliveries",
        "/api/v1/admin/webhook-deliveries/summary",
        "/api/v1/admin/webhook-deliveries/{delivery_id}",
    ):
        assert required in paths, (
            f"FastAPI app is missing route {required!r}. The likely "
            "cause is `from routers import webhook_deliveries_admin "
            "as webhook_deliveries_admin_router` or "
            "`app.include_router(webhook_deliveries_admin_router.router)` "
            "having been rolled back from apps/api/main.py."
        )


def test_cron_admin_router_mounted():
    """`GET /api/v1/admin/crons` is the in-process registry exposed
    to the `/admin/crons` dashboard. Lives in its own router file
    (same dodge-the-admin.py-rollback rationale as slack_deliveries
    and webhook_deliveries_admin). Without this route the dashboard
    404s — the page renders the error banner cleanly, but ops loses
    the registry view they came for.

    The drilldown route (`/{cron_name}/runs`) is the per-cron
    history. Pinned alongside so a revert that drops one or both
    is caught immediately."""
    from main import app

    paths = {route.path for route in app.routes}
    for required in (
        "/api/v1/admin/crons",
        "/api/v1/admin/crons/{cron_name}/runs",
    ):
        assert required in paths, (
            f"FastAPI app is missing route {required!r}. The likely "
            "cause is `from routers import cron_admin as "
            "cron_admin_router` or "
            "`app.include_router(cron_admin_router.router)` having "
            "been rolled back from apps/api/main.py."
        )


def test_cron_telemetry_wrapper_preserves_metadata():
    """`cron_telemetry_wrap` must preserve `__name__`, `__module__`,
    `__doc__` on the wrapped coroutine — otherwise `routers.cron_admin
    .list_crons` reads the wrapper's metadata (`wrapper`, no docstring)
    instead of the actual cron's, and the dashboard renders every
    row as "wrapper" with no description.

    Pin both the metadata-preservation contract and the cron_name
    convention (`cron:<func_name>`) so the dashboard's join key
    stays aligned with arq's CronJob.name."""
    from services.cron_telemetry import _cron_name_for, cron_telemetry_wrap

    async def example_cron(ctx: dict) -> None:
        """Doc line that the dashboard should render."""

    wrapped = cron_telemetry_wrap(example_cron)
    assert wrapped.__name__ == "example_cron", (
        "cron_telemetry_wrap dropped __name__ — dashboard would render 'wrapper' for every cron."
    )
    assert wrapped.__doc__ == example_cron.__doc__, (
        "cron_telemetry_wrap dropped __doc__ — dashboard description column would be empty for every cron."
    )
    assert _cron_name_for(example_cron) == "cron:example_cron", (
        "cron_name convention drifted from arq's CronJob.name shape — the dashboard's last_run join key won't match."
    )


def test_stuck_cron_detection_helper_exists():
    """`services.cron_alerts.check_stuck_crons` is the watchdog half
    that surfaces silent-hang failures (status='running' past 3× p95).
    `cron_telemetry.latest_run_per_cron` returns the same `stuck`
    flag for the dashboard. Both must be present — a revert that
    drops one or the other creates a confusing UX where the dashboard
    flags a stuck cron but Slack stays silent (or vice versa).

    Pin the helper signatures and the constants
    (`_STUCK_MULTIPLIER`, `_BASELINE_WINDOW_DAYS`) so tuning either
    is a deliberate code-review decision."""
    from services.cron_alerts import (
        _BASELINE_WINDOW_DAYS,
        _MIN_SAMPLES_FOR_BASELINE,
        _STUCK_MULTIPLIER,
        _is_stuck,
        check_stuck_crons,
    )

    assert callable(check_stuck_crons), (
        "services.cron_alerts.check_stuck_crons rolled back. The "
        "watchdog calls this every 5 min; without it stuck crons "
        "never produce Slack alerts."
    )

    # Tuning constants — pin so a "let's try 5×" PR triggers a
    # review pause. Each has a documented rationale in the module.
    assert _STUCK_MULTIPLIER == 3.0
    assert _BASELINE_WINDOW_DAYS == 7
    assert _MIN_SAMPLES_FOR_BASELINE == 3

    # `_is_stuck` decision rule — sanity check the three guards
    # listed in its docstring (no baseline → False; insufficient
    # samples → False; otherwise compare elapsed vs multiplier × p95).
    assert _is_stuck({"elapsed_ms": 60_000, "sample_count": None, "p95_ms": None}) is False, (
        "no baseline must skip the check, not flag stuck"
    )
    assert _is_stuck({"elapsed_ms": 60_000, "sample_count": 1, "p95_ms": 1000}) is False, (
        "below MIN_SAMPLES_FOR_BASELINE must skip the check"
    )
    assert _is_stuck({"elapsed_ms": 4000, "sample_count": 10, "p95_ms": 1000}) is True, (
        "elapsed > 3× p95 with sufficient samples must flag stuck"
    )
    assert _is_stuck({"elapsed_ms": 2000, "sample_count": 10, "p95_ms": 1000}) is False, (
        "elapsed < 3× p95 must not flag stuck (false-alarm risk)"
    )


def test_cron_failure_watchdog_registered():
    """The watchdog cron MUST be in `WorkerSettings.cron_jobs`. Without
    it, `cron_runs` rows accumulate but nothing surfaces failures to
    Slack — ops only finds out about a failing cron by manually
    checking `/admin/crons`. The 5-min cadence must also match
    `services.cron_alerts._FRESH_FAILURE_WINDOW_MINUTES` to prevent
    drift between the window and the watchdog's tick."""
    from services.cron_alerts import _FRESH_FAILURE_WINDOW_MINUTES
    from workers.queue import WorkerSettings, cron_failure_watchdog_cron

    # Find the watchdog by coroutine identity (the wrapper's
    # `__wrapped__` points back at the original cron). Walk the
    # registry rather than asserting a position so reordering
    # cron_jobs doesn't break this test.
    found = None
    for entry in WorkerSettings.cron_jobs:
        coro = entry.coroutine
        unwrapped = getattr(coro, "__wrapped__", coro)
        if unwrapped is cron_failure_watchdog_cron:
            found = entry
            break

    assert found is not None, (
        "cron_failure_watchdog_cron is not registered in "
        "WorkerSettings.cron_jobs. Without it, cron_runs failures "
        "never reach Slack."
    )
    # Cadence sanity: minute={0,5,...,55} = every 5 min. Pin the
    # length so a refactor that bumps to 10-min ticks fails this
    # test until `_FRESH_FAILURE_WINDOW_MINUTES` is updated to match.
    expected_count = 60 // _FRESH_FAILURE_WINDOW_MINUTES
    assert isinstance(found.minute, set), (
        "cron_failure_watchdog_cron should use a minute={...} schedule (every-N-minutes), not a single int."
    )
    assert len(found.minute) == expected_count, (
        f"cron_failure_watchdog_cron tick rate ({len(found.minute)} per hour) "
        f"doesn't match cron_alerts._FRESH_FAILURE_WINDOW_MINUTES "
        f"({_FRESH_FAILURE_WINDOW_MINUTES} min → {expected_count}/hr). Update "
        "both in lockstep — mismatch causes either dropped alerts or "
        "double-alerts."
    )


def test_idempotent_route_class_applied():
    """The platform's idempotency infrastructure (`IdempotentRoute` +
    `services.idempotency`) ships with `/docs/api#idempotency`
    promising "routes currently accepting this header will be listed
    when the feature reaches GA." This pins the GA list — three
    routers carry `route_class=IdempotentRoute` so every
    POST/PATCH/DELETE on them honors the `Idempotency-Key` header.

    A revert that drops the route_class kwarg would silently fall
    back to the default APIRoute — partners' retries would create
    duplicate keys / subscriptions / projects without any visible
    failure mode. Pin loudly so the regression goes red at commit time.
    """
    from middleware.idempotency_route import IdempotentRoute
    from routers import api_keys as api_keys_router_module
    from routers import projects as projects_router_module
    from routers import webhooks as webhooks_router_module

    # Each router exposes its routes with the configured
    # `route_class`. Walking the routes is more reliable than
    # introspecting the `APIRouter()` constructor kwargs (which
    # FastAPI doesn't expose post-init).
    expected_routers = {
        "api_keys": api_keys_router_module.router,
        "projects": projects_router_module.router,
        "webhooks": webhooks_router_module.router,
    }
    for name, router in expected_routers.items():
        # Every POST/PATCH/DELETE route on these routers should be an
        # IdempotentRoute instance. GETs are also wrapped (the route
        # class applies to all methods) but the dispatch() handler
        # in IdempotentRoute short-circuits for GETs.
        for route in router.routes:
            if not hasattr(route, "methods"):
                continue
            assert isinstance(route, IdempotentRoute), (
                f"routers.{name}.router has a non-IdempotentRoute "
                f"({type(route).__name__}) at {route.path!r} — "
                "`route_class=IdempotentRoute` was rolled back from "
                f"the APIRouter() call in routers/{name}.py."
            )


def test_external_metrics_documented_for_validator():
    """`core.metrics.EXTERNAL_METRIC_NAMES` documents the gauges
    emitted by `routers/ops.py::_build_metrics_text` (DB-driven
    per-scrape gauges that don't go through the registry). The
    Prometheus rule validator merges this set so alert expressions
    referencing `aec_webhook_*` / `aec_api_key_calls_total` /
    `aec_audit_events_total` resolve cleanly. A revert that drops
    a name here makes the validator reject the alerts file even
    though Prometheus would happily serve it."""
    from core.metrics import EXTERNAL_METRIC_NAMES

    # Pin the names the alerts.yml currently references. Adding a
    # new alert requires registering its metric here; removing one
    # requires removing the corresponding alert rule. Both forces
    # a deliberate edit rather than silent drift.
    expected = frozenset(
        {
            "aec_webhook_deliveries_total",
            "aec_webhook_outbox_lag_seconds",
            "aec_webhook_outbox_pending",
            "aec_api_key_calls_total",
            "aec_search_queries_total",
            "aec_audit_events_total",
        }
    )
    assert expected == EXTERNAL_METRIC_NAMES, (
        f"core.metrics.EXTERNAL_METRIC_NAMES drifted from "
        f"`routers/ops.py::_build_metrics_text` output. Expected "
        f"{sorted(expected)}, got {sorted(EXTERNAL_METRIC_NAMES)}. "
        "If you added a DB-driven gauge to the ops router, list it "
        "here so alerts.yml expressions can reference it; if you "
        "removed one, also drop the matching alert rule."
    )


def test_cron_runs_in_retention_policies():
    """`cron_runs` must be in the retention registry — without it the
    table grows unbounded (webhook_drain fires every minute → 1.4k
    rows/day → ~500k rows/year per replica). 30d is the agreed TTL
    in the migration's docstring; pin it so a future "raise to 365"
    edit gets a code-review pause."""
    from services.retention import RETENTION_POLICIES

    cron_runs_policy = next((p for p in RETENTION_POLICIES if p.table == "cron_runs"), None)
    assert cron_runs_policy is not None, (
        "services.retention.RETENTION_POLICIES is missing the cron_runs "
        "entry. Without it the nightly prune skips the table and rows "
        "accumulate forever."
    )
    assert cron_runs_policy.age_column == "started_at"
    assert cron_runs_policy.default_days == 30, (
        f"cron_runs retention drifted: expected 30d, got "
        f"{cron_runs_policy.default_days}d. See migration 0042 docstring."
    )


def test_webhook_delivery_admin_detail_schema_includes_payload():
    """`WebhookDeliveryAdminDetailOut` extends the list shape with
    `payload`. The drilldown page renders this as pretty-printed JSON.
    A revert that drops the field shows an empty `<pre>` block —
    visually subtle, easy to miss in code review."""
    from schemas.webhook_deliveries import WebhookDeliveryAdminDetailOut

    fields = WebhookDeliveryAdminDetailOut.model_fields
    assert "payload" in fields, (
        "schemas.webhook_deliveries.WebhookDeliveryAdminDetailOut.payload "
        "rolled back. Re-apply: `payload: dict[str, object]` on the "
        "subclass."
    )
    # And the inherited fields from the base class — pin them too so a
    # refactor that turns the subclass into a stand-alone class without
    # the inheritance break loudly here, not at the page render.
    for inherited in ("id", "subscription_id", "event_type", "status"):
        assert inherited in fields, (
            f"WebhookDeliveryAdminDetailOut lost inherited field "
            f"{inherited!r} — the subclass should inherit from "
            "WebhookDeliveryAdminOut."
        )


# ---------- routers.audit: actor-enrichment join ----------------------


def test_audit_event_schema_has_separate_actor_columns():
    """`AuditEventOut` exposes `actor_email` (humans) and
    `actor_api_key_name` (api-key actors) as TWO distinct fields, not
    a single coalesced `api_key:<name>` string. The audit page renders
    them with different styling — collapsing them forces the frontend
    to parse a prefix to tell them apart."""
    from schemas.audit import AuditEventOut

    fields = AuditEventOut.model_fields
    assert "actor_email" in fields, (
        "schemas.audit.AuditEventOut.actor_email rolled back. Re-apply as a separate column from actor_api_key_name."
    )
    assert "actor_api_key_name" in fields, (
        "schemas.audit.AuditEventOut.actor_api_key_name rolled back. "
        "Without it the audit page can't render api-key actors with "
        "the 'key' badge."
    )


def test_audit_router_joins_users_and_api_keys():
    """The list query LEFT JOINs to both users and api_keys so each
    audit row carries the human label its actor needs. A revert that
    loses either join renders the corresponding actor type as a raw
    UUID in the dashboard."""
    from routers import audit as audit_router

    src = inspect.getsource(audit_router.list_audit_events)
    assert "LEFT JOIN users u" in src, (
        "routers/audit.py is missing `LEFT JOIN users u` — every human actor will render as raw actor_user_id UUID."
    )
    assert "LEFT JOIN api_keys ak" in src, (
        "routers/audit.py is missing `LEFT JOIN api_keys ak` — every "
        "api-key actor will render as raw actor_api_key_id UUID."
    )


# ---------- services.webhooks: event catalog -----------------------


def test_event_types_route_registered():
    """`GET /api/v1/webhooks/event-types` is the public catalog
    endpoint that drives the `/docs/webhooks/events` partner-docs
    page. Public (no auth) on purpose — partners evaluating the
    platform read this before getting an API key."""
    from main import app

    paths = {route.path for route in app.routes}
    assert "/api/v1/webhooks/event-types" in paths, (
        "GET /api/v1/webhooks/event-types rolled back from "
        "routers/webhooks.py. Re-apply the @router.get decorator + "
        "the sorted list comprehension over EVENT_CATALOG."
    )


def test_retention_admin_surface():
    """Pin the retention dashboard backend (cycle O3):

    * `GET /api/v1/admin/retention/status` is the read endpoint
      the `/admin/retention` page calls. Frontend's
      `useRetentionStatus()` hook breaks if it disappears.
    * `POST /api/v1/admin/retention/run` is the on-demand prune
      button. Removing it leaves the button rendering but every
      click 404s with no obvious cause.
    * `services.retention.collect_stats(session)` is the
      per-table stats helper. The router calls this; pin the
      callable so a refactor that renames it surfaces here.
    * `services.retention.RETENTION_POLICIES` is the registry
      the dashboard table is keyed off. Empty registry would
      render an empty table without any indication of why.
    """
    from main import app
    from services.retention import RETENTION_POLICIES, collect_stats, run_retention_cron

    paths = {route.path for route in app.routes}
    for required in (
        "/api/v1/admin/retention/status",
        "/api/v1/admin/retention/run",
    ):
        assert required in paths, (
            f"FastAPI app is missing route {required!r}. The /admin/retention dashboard 404s if the route disappears."
        )

    assert callable(collect_stats), (
        "services.retention.collect_stats rolled back. The "
        "/admin/retention/status endpoint depends on this helper "
        "to project per-table TTL + overdue counts."
    )
    assert callable(run_retention_cron), (
        "services.retention.run_retention_cron rolled back. The "
        "/admin/retention/run endpoint depends on this to fire "
        "the prune synchronously."
    )

    assert len(RETENTION_POLICIES) > 0, (
        "services.retention.RETENTION_POLICIES is empty. The "
        "dashboard renders an empty table; nightly cron prunes "
        "nothing — every managed table grows unbounded."
    )
    # Pin the table set: a refactor that drops a policy makes that
    # table grow unbounded silently. Each entry's presence is also
    # safety-net'd by the per-table assertions in the cron tests
    # but the set here is the cheapest signal-of-shrink.
    expected_tables = {
        "audit_events",
        "webhook_deliveries",
        "search_queries",
        "import_jobs",
        "api_key_calls",
        "codeguard_quota_audit_log",
        "cron_runs",
    }
    actual_tables = {p.table for p in RETENTION_POLICIES}
    missing = expected_tables - actual_tables
    assert not missing, (
        f"RETENTION_POLICIES dropped these tables: {sorted(missing)}. "
        "The cron will stop pruning them and storage will grow "
        "unbounded. Re-apply the RetentionPolicy entries."
    )


def test_cron_run_now_surface():
    """Pin the manual-run-cron surface (cycle O2):

    * `POST /api/v1/admin/crons/{cron_name}/run` is the admin-
      gated route that lets an operator fire one cron now from
      the dashboard. The `/admin/crons/[name]` "Run now" button
      breaks if this disappears.

    * `workers.queue.run_cron_by_name_job` is the arq job target.
      Registered in `WorkerSettings.functions` so the pool can
      enqueue by name. Without it, the router enqueues but the
      worker can't dispatch — every manual run fails silently
      with `JobExecutionFailed`.

    * `services.audit.record(action="admin.cron.run_now", ...)`
      is the audit row tying the actor to the cron_runs row by
      timestamp. Pinned via the AuditAction Literal so a typo
      at the call site fails typecheck rather than dropping the
      audit silently.

    * `cron_admin` router carries `route_class=IdempotentRoute`
      so a double-click on the dashboard button doesn't enqueue
      two jobs when the operator includes an Idempotency-Key.
    """
    from main import app
    from middleware.idempotency_route import IdempotentRoute
    from routers import cron_admin
    from workers.queue import WorkerSettings, run_cron_by_name_job

    paths = {route.path for route in app.routes}
    assert "/api/v1/admin/crons/{cron_name}/run" in paths, (
        "POST /api/v1/admin/crons/{cron_name}/run rolled back from "
        "routers/cron_admin.py. Re-apply the @router.post handler + "
        "the call to pool.enqueue_job('run_cron_by_name_job', name)."
    )

    assert run_cron_by_name_job in WorkerSettings.functions, (
        "workers.queue.run_cron_by_name_job is not in "
        "WorkerSettings.functions. Without registration the worker "
        "can't dispatch the manual-run job — every click silently "
        "fails worker-side."
    )

    # The cron_admin router must apply IdempotentRoute so the
    # /run POST honours `Idempotency-Key` headers. Same defense-in-
    # depth check as the existing `test_idempotent_route_class_applied`
    # but scoped to this router so a revert that drops only this
    # one is caught directly.
    has_post_routes = False
    for route in cron_admin.router.routes:
        if hasattr(route, "methods") and route.methods and "POST" in route.methods:
            has_post_routes = True
            assert isinstance(route, IdempotentRoute), (
                f"routers.cron_admin has a POST route ({route.path!r}) "
                "that isn't an IdempotentRoute — `route_class=IdempotentRoute` "
                "was rolled back from the APIRouter() call."
            )
    assert has_post_routes, "cron_admin router has no POST routes registered — the /run handler is missing."


def test_webhook_secret_rotation_surface():
    """Pin the secret-rotation surface (cycle O1):

    * `services.webhooks.rotate_secret` exists and returns a string
      (the new secret) — partner UI's `useRotateWebhookSecret`
      breaks if the helper disappears or stops returning the
      secret in-band.
    * `_previous_secret_active` is the dispatcher's grace-window
      decision rule. Without it `_deliver_one` falls back to
      emitting only the primary signature even mid-rotation —
      receivers running on the old secret silently start failing
      before their grace ends.
    * `POST /api/v1/webhooks/{webhook_id}/rotate-secret` is the
      admin-gated route. Frontend's
      `/settings/webhooks/[id]` "Rotate secret" button breaks if
      this disappears.
    * `DEFAULT_ROTATION_GRACE_SECONDS` is 24h. A revert that
      drops it to a shorter window would silently shorten every
      customer's rollover; pin the operational contract.
    """
    import inspect as _inspect

    from main import app
    from services.webhooks import (
        DEFAULT_ROTATION_GRACE_SECONDS,
        _previous_secret_active,
        rotate_secret,
    )

    assert callable(rotate_secret), (
        "services.webhooks.rotate_secret rolled back. Without the "
        "service helper the router's POST handler 500s and the "
        "/settings/webhooks/[id] rotate button breaks."
    )
    sig = _inspect.signature(rotate_secret)
    for kw in ("subscription_id", "organization_id", "grace_seconds"):
        assert kw in sig.parameters, (
            f"rotate_secret lost the `{kw}` parameter. Re-apply the kwarg + the bound param in the UPDATE statement."
        )

    assert callable(_previous_secret_active), (
        "_previous_secret_active rolled back — without it the "
        "dispatcher can't decide whether to emit the second "
        "signature, and rotated subscriptions either always emit "
        "(security risk past expiry) or never emit (defeats the "
        "grace window's purpose)."
    )

    assert DEFAULT_ROTATION_GRACE_SECONDS == 24 * 60 * 60, (
        f"DEFAULT_ROTATION_GRACE_SECONDS drifted from 24h "
        f"({DEFAULT_ROTATION_GRACE_SECONDS}s). Operationally the "
        "customer expects a predictable 24h grace; a change here "
        "shortens or lengthens every rotation across every tenant."
    )

    paths = {route.path for route in app.routes}
    assert "/api/v1/webhooks/{webhook_id}/rotate-secret" in paths, (
        "POST /api/v1/webhooks/{webhook_id}/rotate-secret rolled back "
        "from routers/webhooks.py. Re-apply the @router.post decorator "
        "+ the call to services.webhooks.rotate_secret + the audit "
        "record(action='webhooks.subscription.rotate_secret')."
    )


def test_webhook_event_catalog_in_sync_with_registry():
    """Every event in `_KNOWN_EVENT_TYPES` must have a catalog entry,
    and vice versa. Drift means partners see "(no description)" for
    a real event OR see a documented event the platform never fires.
    Both regressions are quiet — pin them both directions."""
    from services.webhooks import _KNOWN_EVENT_TYPES, EVENT_CATALOG

    registry = set(_KNOWN_EVENT_TYPES)
    catalog = set(EVENT_CATALOG.keys())

    missing_from_catalog = registry - catalog
    extra_in_catalog = catalog - registry

    assert not missing_from_catalog, (
        f"Events in _KNOWN_EVENT_TYPES without an EVENT_CATALOG entry: "
        f"{sorted(missing_from_catalog)}. Add a description + "
        f"payload_sample for each in services/webhooks.py."
    )
    assert not extra_in_catalog, (
        f"Events documented in EVENT_CATALOG that aren't in "
        f"_KNOWN_EVENT_TYPES: {sorted(extra_in_catalog)}. Either add "
        f"to the registry or remove from the catalog."
    )

    # Every entry must have both keys — partial entries would render
    # as missing fields on the docs page, easy to overlook in code
    # review.
    for event_type, meta in EVENT_CATALOG.items():
        assert "description" in meta and meta["description"], f"EVENT_CATALOG[{event_type!r}] missing/empty description"
        assert "payload_sample" in meta and isinstance(meta["payload_sample"], dict), (
            f"EVENT_CATALOG[{event_type!r}] payload_sample must be a "
            "dict (use {} explicitly for events with no payload)."
        )
