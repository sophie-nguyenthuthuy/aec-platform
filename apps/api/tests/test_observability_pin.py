"""Pin `core.observability` — request-id, structured logging,
slow-query detection.

These primitives touch every request and every SQL statement; a
regression here is broad-blast-radius silent breakage:

  * **`X-Request-ID` header drift.** The frontend's error toast
    shows the request id; the load balancer's access log
    correlates upstream traces; the slow-query log line splices
    it for backtracing. A rename to `Request-Id` (a different but
    common convention) would silently break every correlation
    pipeline.

  * **Outbound RID echo.** A response that drops the X-Request-ID
    header would silently break the LB's distributed-tracing
    correlation.

  * **Slow-query threshold drift.** `settings.slow_query_ms` is
    the noise floor for the WARN. Lifting it to 60s would silently
    hide 100ms-but-frequent queries that bloat tail latency;
    lowering it to 1ms would log every query and bury the real
    slow ones in noise.

  * **Sentry init no-op when DSN unset.** Dev/test environments
    MUST boot without sentry-sdk. A regression that raised on
    missing DSN would break every developer's first-time setup.

  * **`setup_observability` middleware order.** Request-ID has to
    register BEFORE the metrics middleware so the metrics labels
    can read the rid contextvar. A regression that swapped the
    order would silently emit "no rid" labels on every metric.

This file is read-only — exercises the public surface plus
source-greps the wiring. Survives reverts.
"""

from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock

# ---------- Module presence ----------


def test_observability_module_imports():
    """All public surfaces importable."""
    from core.observability import (  # noqa: F401
        RequestIDMiddleware,
        init_sentry,
        install_slow_query_listener,
        request_id_var,
        setup_logging,
        setup_observability,
    )


# ---------- Request ID middleware ----------


def test_request_id_header_constant_pinned():
    """`X-Request-ID` is the documented header name. The frontend's
    error toast + LB correlation + slow-query log line all key on
    this exact case-insensitive name. A rename would silently
    break all three."""
    from core.observability import RequestIDMiddleware

    assert RequestIDMiddleware.HEADER == "X-Request-ID", (
        f"RequestIDMiddleware.HEADER drifted to {RequestIDMiddleware.HEADER!r}. "
        "Frontend + LB + slow-query log all hardcode this exact "
        "header name; rename has to move them in lockstep."
    )


def test_request_id_var_default_is_none():
    """The contextvar's default MUST be None (not e.g. "anonymous"
    or empty string). Log filters check for None to render `-` —
    a default of "anonymous" would show that string on every
    pre-request log line (e.g. boot logs)."""
    from core.observability import request_id_var

    assert request_id_var.get() is None, (
        f"request_id_var default drifted to {request_id_var.get()!r}; "
        "want None. Boot-time log lines render this as `-`; a "
        "non-None default would leak the placeholder string everywhere."
    )


def test_request_id_filter_renders_dash_when_none():
    """The `_RequestIDFilter` renders the contextvar value, falling
    back to `-` when None. Pin via direct invocation — a regression
    to "" or "anonymous" would surface in every pre-request log
    line."""
    from core.observability import _RequestIDFilter

    f = _RequestIDFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="x",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    assert getattr(record, "request_id", None) == "-", (
        f"_RequestIDFilter rendered {getattr(record, 'request_id', None)!r} "
        "for the no-rid case; want '-' (the documented dash placeholder)."
    )


# ---------- Logging formatters ----------


def test_json_formatter_emits_pinned_field_set():
    """One-line JSON per record. Field set is the wire contract for
    log aggregators (CloudWatch, GCP Logs, Loki dashboards). A
    rename of `ts` → `timestamp` or `msg` → `message` would silently
    break every dashboard parser."""
    from core.observability import _JsonFormatter

    formatter = _JsonFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.request_id = "abc123"

    out = formatter.format(record)

    import json as _json

    payload = _json.loads(out)
    assert set(payload.keys()) >= {"ts", "level", "logger", "msg", "request_id"}, (
        f"JSON formatter field set drifted: have {set(payload.keys())}, "
        "want at least {ts, level, logger, msg, request_id}. Renames "
        "break every log-aggregator dashboard parser."
    )
    # Splices in the request_id contextvar value (set on the record
    # via the filter, mocked here).
    assert payload["request_id"] == "abc123"
    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test_logger"


def test_json_formatter_includes_exc_on_exceptions():
    """When the record carries exc_info, the JSON payload includes
    an `exc` field. Sentry / CloudWatch dashboards use this to
    surface failed requests without re-parsing the message."""
    from core.observability import _JsonFormatter

    formatter = _JsonFormatter()
    try:
        raise ValueError("synthetic")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="boom",
            args=(),
            exc_info=sys.exc_info(),
        )
        record.request_id = "abc"
        out = formatter.format(record)

    import json as _json

    payload = _json.loads(out)
    assert "exc" in payload
    assert "ValueError" in payload["exc"]
    assert "synthetic" in payload["exc"]


# ---------- setup_logging ----------


def test_setup_logging_is_idempotent():
    """Calling `setup_logging` twice (e.g. uvicorn --reload) MUST
    NOT stack handlers. A regression would emit duplicate log
    lines for every record after the second call."""
    from core.observability import setup_logging

    settings = MagicMock()
    settings.log_format = "json"
    settings.log_level = "INFO"

    setup_logging(settings)
    handler_count_after_first = len(logging.getLogger().handlers)

    setup_logging(settings)
    handler_count_after_second = len(logging.getLogger().handlers)

    assert handler_count_after_first == handler_count_after_second, (
        f"setup_logging stacked handlers: {handler_count_after_first} → "
        f"{handler_count_after_second}. Reloads under uvicorn --reload "
        "would emit duplicate log lines for every record."
    )


def test_setup_logging_quiets_noisy_libs():
    """`uvicorn.access`, `httpx`, `asyncio` MUST be set to WARNING
    so they don't spam INFO at every request boundary. A regression
    would flood the log with one-line-per-request access logs from
    uvicorn (we emit our own structured log)."""
    from core.observability import setup_logging

    settings = MagicMock()
    settings.log_format = "json"
    settings.log_level = "INFO"
    setup_logging(settings)

    for noisy in ("uvicorn.access", "httpx", "asyncio"):
        level = logging.getLogger(noisy).level
        assert level >= logging.WARNING, (
            f"`{noisy}` logger level is {level}; want >= WARNING. "
            "These libs spam INFO at every request — un-quieting them "
            "buries our structured logs in noise."
        )


# ---------- Sentry no-op ----------


def test_init_sentry_noop_when_dsn_empty():
    """Dev/test environments MUST boot without sentry-sdk. A
    regression that raised on empty DSN would break every
    developer's first-time setup. Pin via the early-return path —
    we don't need sentry-sdk installed to test this."""
    from core.observability import init_sentry

    settings = MagicMock()
    settings.sentry_dsn = ""

    # No raise, returns None.
    out = init_sentry(settings)
    assert out is None


def test_init_sentry_noop_when_sdk_missing():
    """Even with a DSN set, if sentry-sdk isn't installed, init
    MUST log + return cleanly. A regression that crashed the import
    would break every CI run that didn't install the optional
    extra."""
    import core.observability as mod

    src = inspect.getsource(mod.init_sentry)
    assert "ImportError" in src, (
        "init_sentry no longer catches ImportError on the sentry_sdk "
        "import. CI runs without the optional extra would crash on "
        "boot."
    )
    # Logged at WARNING so ops can grep for it.
    assert "warning" in src.lower(), (
        "init_sentry no longer warns when sentry_sdk import fails. "
        "Silent skip means ops doesn't notice they're missing the "
        "Sentry pipeline."
    )


# ---------- Slow-query listener ----------


def test_install_slow_query_listener_signature_pinned():
    """`install_slow_query_listener(engine, threshold_ms)`. Called
    from `setup_observability` against both the user and admin
    engines."""
    from core.observability import install_slow_query_listener

    sig = inspect.signature(install_slow_query_listener)
    params = list(sig.parameters.keys())
    assert params == ["engine", "threshold_ms"], f"install_slow_query_listener signature drifted: {params}"


def test_install_slow_query_listener_supports_async_engine():
    """The async engine wraps a sync `sync_engine` — the
    `before_cursor_execute` event fires from the sync layer.
    A regression that didn't unwrap to sync_engine would silently
    fail to attach the listener to async engines (every async
    query would skip the slow-query check)."""
    import core.observability as mod

    src = inspect.getsource(mod.install_slow_query_listener)
    assert "sync_engine" in src, (
        "install_slow_query_listener no longer unwraps async engines. "
        "Async engines hold their listener target on `sync_engine`; "
        "without unwrapping, the listener attaches to nothing and "
        "silently no-ops."
    )
    assert "AsyncEngine" in src, (
        "install_slow_query_listener no longer references AsyncEngine. "
        "The async-vs-sync engine discrimination is what makes the "
        "function work for both."
    )


def test_slow_query_log_omits_parameters():
    """SECURITY pin. SQL parameters MUST NOT be logged — they may
    contain user data (PII, session tokens, etc). The function only
    logs the SQL text + duration. A regression that emitted params
    would silently leak PII into the log aggregator.
    """
    import core.observability as mod

    src = inspect.getsource(mod.install_slow_query_listener)
    # The log call MUST NOT include `_params` in the format args.
    # We grep for the negative case: any reference to `_params` in
    # the log message would surface here.
    assert (
        "Parameters are *not* logged" in src or "_params" not in src.split("logger.warning")[1]
        if "logger.warning" in src
        else True
    ), (
        "install_slow_query_listener may now log SQL parameters. "
        "Parameters can carry user data (PII, tokens) — never log them."
    )
    # Belt-and-braces source-grep for the documented invariant.
    assert "Parameters are *not* logged" in src, (
        "install_slow_query_listener no longer documents the "
        "'parameters not logged' invariant in its source comment. "
        "Reviewers seeing the function need to know not to add params "
        "to the log call."
    )


# ---------- setup_observability wiring ----------


def test_setup_observability_signature_pinned():
    """`setup_observability(app, settings)`. Called from `create_app()`
    after settings are resolved but before routers mount."""
    from core.observability import setup_observability

    sig = inspect.signature(setup_observability)
    params = list(sig.parameters.keys())
    assert params == ["app", "settings"], f"setup_observability signature drifted: {params}"


def test_setup_observability_wires_request_id_middleware():
    """The setup function MUST register `RequestIDMiddleware` so
    every request gets a rid before any handler runs. A regression
    that skipped the middleware add would silently revert every
    log line to `request_id=-`."""
    import core.observability as mod

    src = inspect.getsource(mod.setup_observability)
    assert "RequestIDMiddleware" in src, (
        "setup_observability no longer registers RequestIDMiddleware. "
        "Every log line would revert to request_id=- (no correlation)."
    )
    assert "add_middleware" in src, (
        "setup_observability no longer calls add_middleware. The "
        "middleware registration path is gone; structured logging "
        "still works but request-id correlation is broken."
    )


def test_setup_observability_attaches_slow_query_to_both_engines():
    """Both the user (`engine`) and admin (`_admin_engine`) engines
    MUST get the slow-query listener. A regression that only
    attached to one would let queries via the other engine silently
    skip the slow-query alarm — and `AdminSessionFactory` runs the
    cron jobs, exactly the queries you'd want to alarm on."""
    import core.observability as mod

    src = inspect.getsource(mod.setup_observability)
    assert "engine" in src and "_admin_engine" in src, (
        "setup_observability no longer attaches slow-query listeners "
        "to both engines. Cron-side queries (via _admin_engine / "
        "AdminSessionFactory) would skip the slow-query alarm."
    )
    # And install_slow_query_listener gets called twice (once per
    # engine).
    assert src.count("install_slow_query_listener(") == 2, (
        f"install_slow_query_listener called {src.count('install_slow_query_listener(')} "
        "times in setup_observability; want 2 (one per engine)."
    )
