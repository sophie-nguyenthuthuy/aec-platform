"""Slim app exposing only the Pulse router for smoke testing."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from core.envelope import http_exception_handler, unhandled_exception_handler
from routers import pulse


def create_app() -> FastAPI:
    app = FastAPI(title="AEC Pulse Smoke", version="0.0.1")
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(pulse.router)

    @app.get("/health")
    async def health() -> dict:
        return {"data": {"status": "ok"}, "meta": None, "errors": None}

    return app


app = create_app()
