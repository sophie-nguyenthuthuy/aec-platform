from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.envelope import http_exception_handler, unhandled_exception_handler
from routers import (
    bidradar,
    codeguard,
    costpulse,
    drawbridge,
    files,
    handover,
    projects,
    pulse,
    siteeye,
    winwork,
)


def create_app() -> FastAPI:
    settings = get_settings()
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

    app.include_router(projects.router)
    app.include_router(winwork.router)
    app.include_router(pulse.router)
    app.include_router(bidradar.router)
    app.include_router(codeguard.router)
    app.include_router(costpulse.router)
    app.include_router(siteeye.router)
    app.include_router(handover.router)
    app.include_router(drawbridge.router)
    app.include_router(files.router)

    @app.get("/health")
    async def health() -> dict:
        return {"data": {"status": "ok"}, "meta": None, "errors": None}

    return app


app = create_app()
