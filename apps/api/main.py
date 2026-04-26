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
    projects,
    public_rfq,
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
    # optional Sentry. Done before routers so middleware sees every
    # inbound request, including ones that 404 before hitting a handler.
    setup_observability(app, settings)

    app.include_router(projects.router)
    app.include_router(activity.router)
    app.include_router(winwork.router)
    app.include_router(pulse.router)
    app.include_router(bidradar.router)
    app.include_router(codeguard.router)
    app.include_router(costpulse.router)
    app.include_router(siteeye.router)
    app.include_router(handover.router)
    app.include_router(drawbridge.router)
    app.include_router(schedulepilot.router)
    app.include_router(files.router)
    # Public (no-auth) routers — token in the request *is* the auth.
    # Mounted last so any global middleware that runs `require_auth`
    # by default can be selectively bypassed by path prefix `/api/v1/public`.
    app.include_router(public_rfq.router)

    @app.get("/health")
    async def health() -> dict:
        return {"data": {"status": "ok"}, "meta": None, "errors": None}

    return app


app = create_app()
