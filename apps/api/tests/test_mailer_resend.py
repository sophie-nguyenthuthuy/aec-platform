"""Tests for the Resend backend in services/mailer.py.

The mailer is the single chokepoint for every email surface (RFQ
dispatch, codeguard quota alerts, ops drift, invitations, daily
digests). When we add a new backend we want to be sure:

  * Backend selection follows the documented priority order
    (Resend → SMTP → no-op).
  * Resend HTTP 2xx → `delivered=True`, no exception leaks out.
  * Resend HTTP 4xx/5xx → `delivered=False, reason="resend_http_XXX"`,
    no exception leaks out.
  * Resend network failure → `delivered=False, reason="resend_network:*"`,
    no exception leaks out.
  * SMTP-only deploys keep working (legacy path).
  * Test/dev environments still get the `smtp_not_configured` no-op.

Network calls are mocked via `httpx.MockTransport` — Resend never gets
hit and tests stay hermetic.
"""

from __future__ import annotations

import httpx
import pytest

from core.config import get_settings


pytestmark = pytest.mark.asyncio


def _reset_settings_cache() -> None:
    """Pydantic settings are LRU-cached. Forcing a fresh read between tests
    lets monkeypatch.setenv take effect for `get_settings()` calls inside
    the mailer."""
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _resend_route_factory(captured: dict, *, status: int = 200, body: dict | None = None):
    """Build an httpx.MockTransport handler that:

      * records the incoming request payload into `captured`
      * returns the configured status + body
    """

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = request.read().decode("utf-8")
        return httpx.Response(status, json=body or {"id": "resend_test_id_123"})

    return handler


async def test_resend_preferred_when_api_key_set(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("RESEND_FROM", "send@aec-platform.vn")
    # Even with SMTP also configured, Resend should win.
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "smtp-user")
    _reset_settings_cache()

    captured: dict = {}
    transport = httpx.MockTransport(_resend_route_factory(captured, status=200))

    import services.mailer as mailer

    async def fake_client_ctx(*args, **kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    # Patch AsyncClient → return a client backed by our MockTransport
    real_async_client = httpx.AsyncClient

    def _patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(mailer.httpx, "AsyncClient", _patched_async_client)

    result = await mailer.send_mail(
        to="ops@example.com", subject="Test", text_body="hello world"
    )

    assert result["delivered"] is True
    assert result["reason"] is None
    assert "url" in captured and captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["authorization"] == "Bearer re_test_key"
    # Verify the JSON payload included all critical fields
    assert "ops@example.com" in captured["payload"]
    assert "send@aec-platform.vn" in captured["payload"]
    assert "Test" in captured["payload"]


async def test_resend_4xx_returns_failed_delivery(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_invalid_key")
    _reset_settings_cache()

    transport = httpx.MockTransport(
        _resend_route_factory({}, status=401, body={"name": "unauthorized"})
    )

    import services.mailer as mailer

    real_async_client = httpx.AsyncClient

    def _patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(mailer.httpx, "AsyncClient", _patched_async_client)

    result = await mailer.send_mail(
        to="ops@example.com", subject="Test", text_body="hello"
    )

    assert result["delivered"] is False
    assert result["reason"] == "resend_http_401"


async def test_resend_network_error_returns_failed_delivery(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    _reset_settings_cache()

    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS failure simulating an offline worker")

    transport = httpx.MockTransport(explode)

    import services.mailer as mailer

    real_async_client = httpx.AsyncClient

    def _patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(mailer.httpx, "AsyncClient", _patched_async_client)

    result = await mailer.send_mail(
        to="ops@example.com", subject="Test", text_body="hello"
    )

    assert result["delivered"] is False
    assert result["reason"] is not None
    assert result["reason"].startswith("resend_network:")


async def test_smtp_used_when_only_smtp_configured(monkeypatch):
    """Legacy path — customers without Resend keep working on SMTP."""
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    _reset_settings_cache()

    import services.mailer as mailer

    smtp_calls: list[tuple] = []

    def fake_sync(msg, settings):
        smtp_calls.append((msg["To"], msg["Subject"]))

    monkeypatch.setattr(mailer, "_send_sync", fake_sync)

    result = await mailer.send_mail(
        to="ops@example.com", subject="Test", text_body="hello"
    )

    assert result["delivered"] is True
    assert smtp_calls == [("ops@example.com", "Test")]


async def test_no_backend_configured_returns_skipped(monkeypatch):
    """The dev/test posture: neither Resend nor SMTP wired — log + no-op."""
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    _reset_settings_cache()

    from services.mailer import send_mail

    result = await send_mail(
        to="ops@example.com", subject="Test", text_body="hello"
    )

    assert result["delivered"] is False
    assert result["reason"] == "smtp_not_configured"
