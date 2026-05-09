"""Tests for Sentry init (`core.observability::init_sentry`) + the
LLM-span tracing wrapper (`core.llm_tracing::llm_span`).

Why this exists: the Sentry init path is gated on `SENTRY_DSN` being
set. Dev/test runs leave the DSN empty so the SDK is never invoked,
which means a regression in `init_sentry` would silently ship to prod
without any local signal. Pinning the call shape here keeps the
contract honest: when DSN is set, `sentry_sdk.init` is invoked exactly
once with the expected args, regardless of how the surrounding wiring
gets refactored.

The tests stub `sentry_sdk` entirely — no real Sentry project, no
network call. The point is to verify the code path, not the SDK.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------- init_sentry ----------


def test_init_sentry_noops_when_dsn_unset(monkeypatch):
    """No DSN → don't even import sentry_sdk. Verifying we don't accidentally
    pay the SDK import cost just because Settings exposes the field."""
    from core.config import Settings
    from core.observability import init_sentry

    settings = Settings(_env_file=None)
    settings.sentry_dsn = None

    # If the function tries to import sentry_sdk we want to know — patch
    # `__import__` to raise, then verify init_sentry returns cleanly.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    imported: list[str] = []

    def tracking_import(name, *args, **kwargs):
        if name.startswith("sentry_sdk"):
            imported.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", tracking_import)
    init_sentry(settings)
    assert imported == [], f"sentry_sdk imported despite DSN unset: {imported}"


def test_init_sentry_invokes_sdk_with_expected_args(monkeypatch):
    """DSN set → sentry_sdk.init called once with our settings."""
    fake_sdk = types.ModuleType("sentry_sdk")
    fake_sdk.init = MagicMock()  # type: ignore[attr-defined]
    fake_fastapi = types.ModuleType("sentry_sdk.integrations.fastapi")
    fake_starlette = types.ModuleType("sentry_sdk.integrations.starlette")
    fake_fastapi.FastApiIntegration = MagicMock(return_value="fastapi-integration")  # type: ignore[attr-defined]
    fake_starlette.StarletteIntegration = MagicMock(return_value="starlette-integration")  # type: ignore[attr-defined]
    fake_integrations = types.ModuleType("sentry_sdk.integrations")

    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations", fake_integrations)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.fastapi", fake_fastapi)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.starlette", fake_starlette)

    from core.config import Settings
    from core.observability import init_sentry

    settings = Settings(_env_file=None)
    settings.sentry_dsn = "https://abc@o0.ingest.sentry.io/1"
    settings.environment = "production"
    settings.sentry_traces_sample_rate = 0.05

    init_sentry(settings)

    fake_sdk.init.assert_called_once()
    kwargs = fake_sdk.init.call_args.kwargs
    assert kwargs["dsn"] == "https://abc@o0.ingest.sentry.io/1"
    assert kwargs["environment"] == "production"
    assert kwargs["traces_sample_rate"] == 0.05
    # PII guard — we never want to leak request bodies to Sentry.
    assert kwargs["send_default_pii"] is False
    # Both integrations registered so middleware errors get traced.
    assert "starlette-integration" in kwargs["integrations"]
    assert "fastapi-integration" in kwargs["integrations"]


def test_init_sentry_warns_and_continues_when_sdk_missing(monkeypatch, caplog):
    """DSN set but sentry-sdk not importable → log a warning, don't crash.
    Mirrors what happens if a slim deploy strips the SDK from requirements."""
    # Force ImportError on the sentry_sdk import inside init_sentry.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def blocking_import(name, *args, **kwargs):
        if name.startswith("sentry_sdk"):
            raise ImportError("synthetic — sentry-sdk not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocking_import)

    from core.config import Settings
    from core.observability import init_sentry

    settings = Settings(_env_file=None)
    settings.sentry_dsn = "https://abc@o0.ingest.sentry.io/1"

    with caplog.at_level("WARNING"):
        init_sentry(settings)

    msgs = [r.message for r in caplog.records]
    assert any("sentry-sdk" in m and "not installed" in m for m in msgs), msgs


# ---------- llm_span ----------


async def test_llm_span_is_noop_when_sentry_sdk_missing(monkeypatch):
    """SDK not installed → context manager yields a no-op span and runs
    the body normally. Tags / status calls don't crash."""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "sentry_sdk":
            raise ImportError("synthetic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocking_import)

    from core.llm_tracing import llm_span

    async with llm_span("test.op", model="m", extra={"k": "v"}) as span:
        # The placeholder span exposes the same surface as a real one;
        # calling these must not raise.
        span.set_tag("a", "b")
        span.set_data("k", "v")
        span.set_status("ok")


async def test_llm_span_emits_span_when_sdk_initialized(monkeypatch):
    """SDK installed and Hub has a client → start_span is called with
    op='ai.llm' and tags get applied. Body runs normally."""
    span_obj = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=span_obj)
    cm.__exit__ = MagicMock(return_value=False)

    fake_sdk = types.ModuleType("sentry_sdk")
    fake_sdk.start_span = MagicMock(return_value=cm)  # type: ignore[attr-defined]
    fake_sdk.Hub = types.SimpleNamespace(current=types.SimpleNamespace(client=object()))  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)

    from core.llm_tracing import llm_span

    async with llm_span("winwork.scope", model="claude-sonnet-4-6", extra={"org_id": "o1"}) as span:
        assert span is span_obj

    fake_sdk.start_span.assert_called_once()
    call_kwargs = fake_sdk.start_span.call_args.kwargs
    assert call_kwargs["op"] == "ai.llm"
    assert call_kwargs["description"] == "winwork.scope"

    # Tags applied: model, operation, and the extra dict (with prefix).
    tag_keys = [c.args[0] for c in span_obj.set_tag.call_args_list]
    assert "llm.model" in tag_keys
    assert "llm.operation" in tag_keys
    assert "llm.org_id" in tag_keys


async def test_llm_span_marks_internal_error_on_exception(monkeypatch):
    """A raised exception inside the context body bubbles up after the
    span is marked `internal_error` with the exception string."""
    span_obj = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=span_obj)
    cm.__exit__ = MagicMock(return_value=False)

    fake_sdk = types.ModuleType("sentry_sdk")
    fake_sdk.start_span = MagicMock(return_value=cm)  # type: ignore[attr-defined]
    fake_sdk.Hub = types.SimpleNamespace(current=types.SimpleNamespace(client=object()))  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)

    from core.llm_tracing import llm_span

    with pytest.raises(RuntimeError, match="boom"):
        async with llm_span("test.op", model="m"):
            raise RuntimeError("boom")

    span_obj.set_status.assert_called_with("internal_error")
    span_obj.set_data.assert_called_with("error", "boom")
