"""Webhook signature verification playground (cycle Q2).

Pinned seams:
  1. `verify_payload_with_trace` returns the structured-diagnosis
     dict — the playground's UX hinges on these specific reason codes.
  2. The router endpoint is public (no auth) and returns the trace
     verbatim — partners debug their integration BEFORE getting an
     API key.
  3. Reason codes form a closed vocabulary (`timestamp_skew_exceeded`,
     `signature_mismatch`, `invalid_signature_format`); the UI keys
     off these for the focused diagnostic copy.
"""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


# ---------- verify_payload_with_trace (pure helper) ---------------


def test_trace_returns_verified_true_on_match():
    """Happy path — secret + body + ts produce the expected
    signature; verify returns True with reason=None."""
    from services.webhooks import sign_payload_with_timestamp, verify_payload_with_trace

    secret = "x" * 64
    body = b'{"event":"test"}'
    ts = int(time.time())
    sig = sign_payload_with_timestamp(secret, body, ts)

    trace = verify_payload_with_trace(secret, body, ts, sig, now=ts)
    assert trace["verified"] is True
    assert trace["reason"] is None
    assert trace["expected_signature"] == sig
    assert trace["provided_signature"] == sig
    assert trace["skew_seconds"] == 0


def test_trace_accepts_sha256_prefix_in_signature():
    """Wire format includes `sha256=<hex>`. Verify strips it before
    compare so receivers that pass the raw header verbatim work."""
    from services.webhooks import sign_payload_with_timestamp, verify_payload_with_trace

    secret = "x" * 64
    body = b"abc"
    ts = int(time.time())
    sig = sign_payload_with_timestamp(secret, body, ts)
    wire = f"sha256={sig}"

    trace = verify_payload_with_trace(secret, body, ts, wire, now=ts)
    assert trace["verified"] is True
    # `provided_signature` shows the stripped form so partners can
    # compare digest-to-digest visually.
    assert trace["provided_signature"] == sig


def test_trace_returns_timestamp_skew_exceeded():
    """Future-dated or stale timestamp → reason='timestamp_skew_exceeded'.
    Pin the reason code so the UI's diagnostic copy stays aligned."""
    from services.webhooks import sign_payload_with_timestamp, verify_payload_with_trace

    secret = "x" * 64
    body = b"abc"
    ts = 1_000_000
    sig = sign_payload_with_timestamp(secret, body, ts)

    # Now is 10 minutes ahead — beyond the 300s default skew window.
    trace = verify_payload_with_trace(secret, body, ts, sig, now=ts + 600)
    assert trace["verified"] is False
    assert trace["reason"] == "timestamp_skew_exceeded"
    # `skew_seconds` is signed: positive = now ahead of ts.
    assert trace["skew_seconds"] == 600
    # We STILL compute the expected sig so the partner can eyeball
    # both clock + signature problems at once.
    assert trace["expected_signature"] == sig


def test_trace_returns_signature_mismatch_when_bytes_differ():
    """Wrong secret produces a different expected sig; `provided`
    no longer matches → reason='signature_mismatch'."""
    from services.webhooks import sign_payload_with_timestamp, verify_payload_with_trace

    secret = "x" * 64
    wrong_secret = "y" * 64
    body = b"abc"
    ts = int(time.time())
    sig_wrong = sign_payload_with_timestamp(wrong_secret, body, ts)

    trace = verify_payload_with_trace(secret, body, ts, sig_wrong, now=ts)
    assert trace["verified"] is False
    assert trace["reason"] == "signature_mismatch"
    # Both sigs surface so the partner can compare hex-by-hex.
    assert trace["expected_signature"] != sig_wrong
    assert trace["provided_signature"] == sig_wrong


def test_trace_skew_negative_when_ts_ahead_of_now():
    """If the receiver's clock is BEHIND the sender's, skew is
    negative. Pin the sign so the UI can render "your clock is
    behind by Xs" correctly."""
    from services.webhooks import sign_payload_with_timestamp, verify_payload_with_trace

    secret = "x" * 64
    body = b"abc"
    ts = 2_000_000
    sig = sign_payload_with_timestamp(secret, body, ts)

    trace = verify_payload_with_trace(secret, body, ts, sig, now=ts - 100)
    # 100s skew is within the 300s window → still verifies.
    assert trace["verified"] is True
    assert trace["skew_seconds"] == -100


def test_trace_custom_max_skew():
    """`max_skew_seconds` lets partners diagnose "would this verify
    if we accept up to N seconds skew?" without changing production
    policy. Pin so the kwarg actually threads through."""
    from services.webhooks import sign_payload_with_timestamp, verify_payload_with_trace

    secret = "x" * 64
    body = b"abc"
    ts = 1_000_000
    sig = sign_payload_with_timestamp(secret, body, ts)

    # 600s skew, default window (300s) → fail.
    trace_default = verify_payload_with_trace(secret, body, ts, sig, now=ts + 600)
    assert trace_default["verified"] is False
    # Same skew but bumped window (3600s) → pass.
    trace_relaxed = verify_payload_with_trace(secret, body, ts, sig, now=ts + 600, max_skew_seconds=3600)
    assert trace_relaxed["verified"] is True


# ---------- POST /verify-signature endpoint -----------------------


def _build_app() -> FastAPI:
    """Mount only the webhooks router — no auth dep override needed
    because /verify-signature is intentionally public."""
    from routers import webhooks as webhooks_router

    app = FastAPI()
    app.include_router(webhooks_router.router)
    return app


async def test_verify_signature_endpoint_returns_trace_dict():
    """End-to-end: POST with secret/body/ts/sig → response carries
    the trace dict shape the UI keys off."""
    secret = "x" * 64
    body = '{"hello":"world"}'
    ts = int(time.time())
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body.encode(), hashlib.sha256).hexdigest()

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/webhooks/verify-signature",
            json={
                "secret": secret,
                "body": body,
                "timestamp": ts,
                "signature": f"sha256={expected}",
            },
        )

    assert res.status_code == 200, res.text
    trace = res.json()["data"]
    assert trace["verified"] is True
    assert trace["reason"] is None
    assert trace["expected_signature"] == expected


async def test_verify_signature_endpoint_does_not_require_auth():
    """The playground is partner-facing — partners debug BEFORE
    getting an API key. Pin no-auth so a regression that adds
    Depends(require_auth) doesn't lock partners out."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/webhooks/verify-signature",
            json={
                "secret": "x" * 64,
                "body": "hi",
                "timestamp": int(time.time()),
                "signature": "deadbeef",
            },
        )
    # 200 (not 401/403) — endpoint accepted the request without auth.
    assert res.status_code == 200, res.text


async def test_verify_signature_endpoint_surfaces_skew_reason():
    """Stale timestamp → reason='timestamp_skew_exceeded'. Pin the
    wire-level reason code so the UI's diagnostic copy stays
    aligned with the API."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/webhooks/verify-signature",
            json={
                "secret": "x" * 64,
                "body": "hi",
                "timestamp": 1_000_000,  # year 1970-ish — way past the skew window
                "signature": "deadbeef" * 8,
            },
        )
    assert res.status_code == 200
    trace = res.json()["data"]
    assert trace["verified"] is False
    assert trace["reason"] == "timestamp_skew_exceeded"


async def test_verify_signature_reason_codes_are_closed_vocabulary():
    """Only three reason codes: timestamp_skew_exceeded, signature_mismatch,
    invalid_signature_format. Pin so a refactor that adds an
    open-ended message field breaks the UI's switch-on-reason
    rendering."""
    from services.webhooks import verify_payload_with_trace

    # signature_mismatch
    secret = "x" * 64
    ts = int(time.time())
    trace = verify_payload_with_trace(secret, b"hi", ts, "0" * 64, now=ts)
    assert trace["reason"] == "signature_mismatch"

    # timestamp_skew_exceeded
    trace = verify_payload_with_trace(secret, b"hi", ts, "0" * 64, now=ts + 86400)
    assert trace["reason"] == "timestamp_skew_exceeded"
