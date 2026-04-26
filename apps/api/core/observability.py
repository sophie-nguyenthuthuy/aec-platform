"""Observability primitives: structured logging, request IDs, slow-query
detection, optional Sentry init.

Wired into the FastAPI app at startup via `setup_observability(app)` from
`main.py`. Designed so the module is dependency-light by default — `import
sentry_sdk` only happens when a DSN is configured, so dev/test runs don't
pay for an unused dependency.

Three pieces:

  * `RequestIDMiddleware` — generates a UUID per request, threads it into
    a contextvar so log records pick it up automatically, and echoes it
    back as the `X-Request-ID` response header. Honors an inbound header
    of the same name so a load balancer / API gateway can correlate
    upstream traces with this service's logs.

  * `setup_logging(settings)` — installs a single root handler with either
    a pretty single-line formatter (dev) or one-line-JSON (prod). Both
    formatters splice in the current `request_id` contextvar value, so
    every log line during a request is automatically tagged.

  * `install_slow_query_listener(engine, threshold_ms)` — registers
    SQLAlchemy `before_cursor_execute` / `after_cursor_execute` listeners
    that time every statement and emit a WARN when the elapsed time
    exceeds the threshold. Includes the SQL text (parameters elided to
    stay PII-safe) and the request_id contextvar so a slow query is
    traceable back to the inbound request that spawned it.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from core.config import Settings

# ---------- Request-ID context ----------

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generates (or accepts) an X-Request-ID per inbound request.

    Stores it in `request_id_var` for the duration of the request so log
    records, slow-query warnings, and any deeper instrumentation can pick
    it up without explicit threading.
    """

    HEADER = "X-Request-ID"

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(self.HEADER)
        rid = incoming or uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
            response.headers[self.HEADER] = rid
            return response
        finally:
            request_id_var.reset(token)


# ---------- Logging ----------


class _RequestIDFilter(logging.Filter):
    """Splices the current `request_id` contextvar onto every log record so
    formatters can render it without each call site needing to pass it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class _JsonFormatter(logging.Formatter):
    """One-line JSON per record. Suitable for shipping to any log
    aggregator (CloudWatch, GCP Logs, Loki, etc.). Keeps the field set
    small + stable so dashboards / parsers don't break on schema drift."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _pretty_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s %(levelname)-5s [%(request_id)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def setup_logging(settings: Settings) -> None:
    """Install a single root handler. Idempotent — safe to call twice
    (e.g. reloads under uvicorn --reload)."""
    root = logging.getLogger()
    # Wipe any pre-existing handlers (e.g. from prior reload) to avoid
    # duplicate log lines.
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    handler.addFilter(_RequestIDFilter())
    if settings.log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_pretty_formatter())

    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Quiet down libraries that otherwise spam INFO at every request boundary.
    for noisy in ("uvicorn.access", "httpx", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------- Slow-query detection ----------

logger = logging.getLogger("aec.slow_query")


def install_slow_query_listener(engine: Engine | AsyncEngine, threshold_ms: int) -> None:
    """Time every SQLAlchemy statement; emit a WARN if it exceeds threshold.

    Async engines hold a sync `engine.sync_engine` underneath — that's the
    one we attach to (the `before_cursor_execute` / `after_cursor_execute`
    events fire from the sync layer). The timestamp is stashed on the
    `connection.info` mutable dict so concurrent statements on different
    connections don't clobber each other.
    """
    target = engine.sync_engine if isinstance(engine, AsyncEngine) else engine

    @event.listens_for(target, "before_cursor_execute")
    def _before(_conn, _cursor, _statement, _params, context, _executemany):
        context._aec_query_start = time.perf_counter()

    @event.listens_for(target, "after_cursor_execute")
    def _after(_conn, _cursor, statement, _params, context, _executemany):
        start = getattr(context, "_aec_query_start", None)
        if start is None:
            return
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if elapsed_ms < threshold_ms:
            return
        # Truncate the SQL so a multi-page CTE doesn't blow up log volume.
        # Parameters are *not* logged — they may contain user data.
        sql_preview = " ".join(statement.split())[:240]
        logger.warning(
            "slow query: %.0fms (threshold %dms) — %s",
            elapsed_ms,
            threshold_ms,
            sql_preview,
        )


# ---------- Sentry ----------


def init_sentry(settings: Settings) -> None:
    """Lazy import + init. No-op when DSN is empty so dev/test don't pull
    the SDK in. Tracing sample rate is configurable so prod can dial it
    down (full tracing on every request is expensive)."""
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk  # type: ignore[import-not-found]
        from sentry_sdk.integrations.fastapi import FastApiIntegration  # type: ignore[import-not-found]
        from sentry_sdk.integrations.starlette import StarletteIntegration  # type: ignore[import-not-found]
    except ImportError:
        logging.getLogger(__name__).warning("SENTRY_DSN is set but sentry-sdk is not installed; skipping init")
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        # Don't ship request bodies to Sentry — they may contain PII.
        send_default_pii=False,
    )


# ---------- Wiring ----------


def setup_observability(app: FastAPI, settings: Settings) -> None:
    """One-stop wire-up. Call from `create_app()` after settings are
    resolved but before routers are mounted (so middleware sees every
    request, not just routed ones)."""
    setup_logging(settings)
    init_sentry(settings)
    app.add_middleware(RequestIDMiddleware)
    # Slow-query listener attaches to whichever engines the app uses.
    # Imported lazily to avoid a circular import at module load time
    # (db.session imports core.config which is fine; this would import
    # db.session at module top, dragging it into core's import graph).
    from db.session import _admin_engine, engine

    install_slow_query_listener(engine, settings.slow_query_ms)
    install_slow_query_listener(_admin_engine, settings.slow_query_ms)
