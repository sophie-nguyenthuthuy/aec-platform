from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.envelope import http_exception_handler, unhandled_exception_handler
from core.observability import setup_observability
from routers import (
    activity,
    bidradar,
    codeguard,
    costpulse,
    drawbridge,
    files,
    handover,
    notifications,
    projects,
    public_rfq,
    pulse,
    schedulepilot,
    siteeye,
    submittals,
    winwork,
)


def create_app() -> FastAPI:
    settings = get_settings()

    # Fail fast if a prod deploy ever boots with dev defaults — these would
    # otherwise let any caller mint a valid JWT against the well-known dev
    # secret. Restricted to AEC_ENV=production so local/staging keep booting.
    if settings.environment == "production" and settings.supabase_jwt_secret == "dev-secret-change-me":
        raise RuntimeError("AEC_ENV=production but SUPABASE_JWT_SECRET is the dev default — refusing to start")

    app = FastAPI(title="AEC Platform API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Structured logging, request-ID middleware, slow-query detection,
    # optional Sentry. Done before routers so middleware sees every
    # inbound request, including ones that 404 before hitting a handler.
    setup_observability(app, settings)

    app.include_router(projects.router)
    app.include_router(activity.router)
    app.include_router(notifications.router)
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
    app.include_router(files.router)
    # Public (no-auth) routers — token in the request *is* the auth.
    # Mounted last so any global middleware that runs `require_auth`
    # by default can be selectively bypassed by path prefix `/api/v1/public`.
    app.include_router(public_rfq.router)

    @app.get("/health")
    async def health() -> dict:
        """Liveness probe — process is up. Cheap, never touches DB/Redis.

        Use this for k8s `livenessProbe`. Failing this means the pod is
        wedged and should be restarted.
        """
        return {"data": {"status": "ok"}, "meta": None, "errors": None}

    @app.get("/health/ready")
    async def health_ready():
        """Readiness probe — DB + Redis are reachable.

        Use this for k8s `readinessProbe`. Failing this means the pod is
        running but shouldn't get traffic yet (or the dependency is down).

        Each dep has a 1-second budget; we report status per-dep so an
        operator can tell at a glance which one is blocking traffic. The
        function NEVER raises — degraded health surfaces via the response
        body + a 503 status, not a 5xx exception.
        """
        from fastapi.responses import JSONResponse

        checks = await _readiness_checks()
        all_ok = all(c["ok"] for c in checks.values())
        body = {
            "data": {
                "status": "ok" if all_ok else "degraded",
                "checks": checks,
            },
            "meta": None,
            "errors": None,
        }
        return JSONResponse(body, status_code=200 if all_ok else 503)

    return app


async def _readiness_checks() -> dict[str, dict]:
    """Run each dependency probe with a 1s budget. Returns one entry per
    dep so the response shows exactly what's broken."""
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
        # arq's `create_pool` is the same client the workers use, so this
        # probe matches production behavior. Done lazily so a missing
        # `arq` install doesn't break liveness checks.
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

    db_status, redis_status = await asyncio.gather(_db_check(), _redis_check(), return_exceptions=False)
    return {"db": db_status, "redis": redis_status}


app = create_app()
