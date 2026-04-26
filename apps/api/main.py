from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.envelope import http_exception_handler, unhandled_exception_handler
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
    assistant,
    bidradar,
    changeorder,
    codeguard,
    costpulse,
    drawbridge,
    files,
    handover,
    me,
    notifications,
    projects,
    pulse,
    schedulepilot,
    siteeye,
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
    # optional Sentry init. Done before routers so middleware sees every
    # inbound request, including ones that 404 before hitting a handler.
    setup_observability(app, settings)

    app.include_router(me.router)
    app.include_router(projects.router)
    app.include_router(activity.router)
    app.include_router(notifications.router)
    app.include_router(assistant.router)
    app.include_router(winwork.router)
    app.include_router(pulse.router)
    app.include_router(bidradar.router)
    app.include_router(codeguard.router)
    app.include_router(costpulse.router)
    app.include_router(siteeye.router)
    app.include_router(handover.router)
    app.include_router(drawbridge.router)
    app.include_router(schedulepilot.router)
    app.include_router(changeorder.router)
    app.include_router(files.router)

    @app.get("/health")
    async def health() -> dict:
        """Liveness probe — process is up. Cheap, never touches DB/Redis."""
        return {"data": {"status": "ok"}, "meta": None, "errors": None}

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
