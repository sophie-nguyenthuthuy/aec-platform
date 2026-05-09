from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings, validate_prod_settings
from core.envelope import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from core.observability import setup_observability

# Register every ORM model up-front so SQLAlchemy can sort FK deps at flush time.
# Today this is also achieved indirectly because `routers/projects.py` imports
# from every module's models — but we don't want that to be load-bearing. If
# someone refactors `projects.py` and drops a model import, the next handler
# that flushes a row whose FK target wasn't loaded will blow up with
# `NoReferencedTableError` (the exact bug that hit `workers/queue.py`).
from models import register_all as _register_all_models  # noqa: E402

_register_all_models()

from routers import (  # noqa: E402
    activity,
    admin,
    assistant,
    audit,
    bidradar,
    changeorder,
    codeguard,
    costpulse,
    dailylog,
    drawbridge,
    files,
    handover,
    inbox,
    invitations,
    me,
    notifications,
    onboarding,
    org,
    orgs,
    projects,
    public_rfq,
    pulse,
    punchlist,
    schedulepilot,
    search,
    siteeye,
    submittals,
    webhooks,
    winwork,
)
from routers import activity_stream as activity_stream_router  # noqa: E402
from routers import api_keys as api_keys_router  # noqa: E402
from routers import cron_admin as cron_admin_router  # noqa: E402
from routers import exports as exports_router  # noqa: E402
from routers import imports as imports_router  # noqa: E402
from routers import ops as ops_router  # noqa: E402
from routers import slack_deliveries as slack_deliveries_router  # noqa: E402
from routers import webhook_deliveries_admin as webhook_deliveries_admin_router  # noqa: E402


def create_app() -> FastAPI:
    settings = get_settings()

    # Fail fast if a prod deploy ever boots with dev defaults. The full
    # rule list (JWT secret, CORS, web URLs, metrics token, Ray Serve
    # endpoint) lives in `core.config.validate_prod_settings` so each
    # rule is unit-testable in isolation. We list ALL issues in one
    # error rather than failing on the first — operators triaging a
    # boot failure can then fix everything in one redeploy instead of
    # "fix one, redeploy, fix the next, redeploy."
    issues = validate_prod_settings(settings)
    if issues:
        bullet_list = "\n  - ".join(issues)
        raise RuntimeError(
            "AEC_ENV=production but the following dev defaults / unsafe "
            f"settings would ship — refusing to start:\n  - {bullet_list}\n"
            "Fix all of the above in your env / manifest, then redeploy."
        )

    app = FastAPI(title="AEC Platform API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(HTTPException, http_exception_handler)
    # 422 envelope shape: TS client unwraps `errors[].field` for form-
    # field-level highlighting. Without this, FastAPI's default 422
    # body (`{"detail": [...]}`) doesn't match the envelope contract
    # and every form submission with a validation error lands in the
    # generic-error toast bucket.
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Structured logging, request-ID middleware, slow-query detection,
    # optional Sentry init. Done before routers so middleware sees every
    # inbound request, including ones that 404 before hitting a handler.
    setup_observability(app, settings)

    app.include_router(me.router)
    app.include_router(inbox.router)
    app.include_router(org.router)
    app.include_router(orgs.router)
    app.include_router(invitations.router)
    app.include_router(projects.router)
    app.include_router(activity.router)
    # SSE activity stream — separate router (not part of `routers/activity.py`)
    # so the GET /api/v1/activity/stream endpoint's ticket-based auth
    # doesn't bleed into the polled feed's Bearer-only contract.
    app.include_router(activity_stream_router.router)
    app.include_router(notifications.router)
    app.include_router(assistant.router)
    app.include_router(audit.router)
    app.include_router(search.router)
    app.include_router(webhooks.router)
    app.include_router(onboarding.router)
    app.include_router(imports_router.router)
    app.include_router(exports_router.router)
    app.include_router(api_keys_router.router)
    app.include_router(winwork.router)
    app.include_router(pulse.router)
    app.include_router(bidradar.router)
    app.include_router(codeguard.router)
    app.include_router(costpulse.router)
    app.include_router(siteeye.router)
    app.include_router(handover.router)
    app.include_router(drawbridge.router)
    app.include_router(schedulepilot.router)
    app.include_router(submittals.router)
    app.include_router(dailylog.router)
    app.include_router(changeorder.router)
    app.include_router(punchlist.router)
    app.include_router(files.router)
    # Cross-module admin / ops endpoints (gated by `admin` role).
    app.include_router(admin.router)
    # Slack-deliveries admin surface — separate router so the
    # `routers/admin.py` revert pattern doesn't take it offline.
    app.include_router(slack_deliveries_router.router)
    # Webhook-deliveries admin surface — same revert-avoidance
    # rationale; cross-tenant view of `webhook_deliveries` for the
    # platform admin dashboard.
    app.include_router(webhook_deliveries_admin_router.router)
    # Cron-job registry — `/admin/crons`. In-process read of
    # `WorkerSettings.cron_jobs`; no DB needed.
    app.include_router(cron_admin_router.router)
    # Public (no-auth) routers — token in the request *is* the auth.
    # Mounted last so any global middleware that runs `require_auth`
    # by default can be selectively bypassed by path prefix.
    app.include_router(public_rfq.router)
    # Ops surface — /healthz, /readyz, /metrics. Concatenates
    # core.metrics.render() with DB-driven gauges in one scrape.
    app.include_router(ops_router.router)

    @app.get("/health")
    async def health() -> dict:
        """Liveness probe — process is up. Cheap, never touches DB/Redis.
        A duplicate `/healthz` lives in routers/ops.py for k8s-style
        probe path conventions."""
        return {"data": {"status": "ok"}, "meta": None, "errors": None}

    # `/metrics` lives in routers/ops.py — single scrape, both surfaces.

    @app.get("/health/ready")
    async def health_ready():
        """Readiness probe — DB + Redis are reachable. 503 when degraded
        so a load balancer pulls the pod out of rotation."""
        from fastapi.responses import JSONResponse

        checks = await _readiness_checks()
        all_ok = all(c["ok"] for c in checks.values())
        body = {
            "data": {"status": "ok" if all_ok else "degraded", "checks": checks},
            "meta": None,
            "errors": None,
        }
        return JSONResponse(body, status_code=200 if all_ok else 503)

    return app


async def _readiness_checks() -> dict[str, dict]:
    """Run each dependency probe with a 1s budget. Reports per-dep
    so an operator can tell at a glance which one is blocking traffic."""
    import asyncio

    from sqlalchemy import text

    from db.session import engine

    async def _db_check() -> dict:
        try:
            async with engine.connect() as conn:
                await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=1.0)
            return {"ok": True}
        except TimeoutError:
            return {"ok": False, "error": "timeout (>1s)"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def _redis_check() -> dict:
        try:
            from arq.connections import RedisSettings, create_pool

            settings = get_settings()
            pool = await asyncio.wait_for(
                create_pool(RedisSettings.from_dsn(settings.redis_url)),
                timeout=1.0,
            )
            try:
                await asyncio.wait_for(pool.ping(), timeout=1.0)
                return {"ok": True}
            finally:
                closer = getattr(pool, "aclose", None) or pool.close
                await closer()
        except TimeoutError:
            return {"ok": False, "error": "timeout (>1s)"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    db_status, redis_status = await asyncio.gather(_db_check(), _redis_check())
    return {"db": db_status, "redis": redis_status}


app = create_app()
