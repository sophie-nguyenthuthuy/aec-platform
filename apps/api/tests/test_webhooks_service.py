"""Service-level tests for the webhook outbox + dispatcher.

We isolate the SQL behind a `FakeAsyncSession` and the HTTP delivery
behind a `MagicMock(httpx.AsyncClient)` so the tests run without
Postgres or the network. Three layers of coverage:

  * Pure helpers (`generate_secret`, `sign_payload`) — verify the
    signature is HMAC-SHA256 hex of the body and reproducible.

  * `enqueue_event` — produces one delivery row per matching
    subscription and returns the count. Empty subscription list → 0.

  * `drain_pending` — picks due rows, marks `in_flight`, calls
    `_deliver_one` (mocked), and transitions to `delivered` on 2xx
    or schedules a retry / permanent fail otherwise.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
SUB_ID = UUID("33333333-3333-3333-3333-333333333333")


# ---------- FakeAsyncSession (queue-based execute results) ----------


class FakeAsyncSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.mappings.return_value.all.return_value = []
        r.scalars.return_value.all.return_value = []
        return r


# ---------- Pure helpers ----------


def test_generate_secret_is_64_hex_chars():
    """32 random bytes hex-encoded = 64 chars. Two calls produce
    different secrets (sanity)."""
    from services.webhooks import generate_secret

    a = generate_secret()
    b = generate_secret()
    assert len(a) == 64
    assert all(c in "0123456789abcdef" for c in a)
    assert a != b


def test_sign_payload_matches_hmac_sha256_hex():
    """The signature shape is the contract — receivers use
    `hmac.compare_digest(local_hmac(body), header)` to verify, so the
    digest format must stay HMAC-SHA256-hex."""
    from services.webhooks import sign_payload

    secret = "deadbeef" * 8  # 64 chars, valid shape
    body = b'{"event":"test"}'
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert sign_payload(secret, body) == expected


def test_sign_payload_deterministic():
    """Same inputs → same signature. Receivers depend on this for
    replay verification."""
    from services.webhooks import sign_payload

    secret = "abc123"
    body = b"x"
    assert sign_payload(secret, body) == sign_payload(secret, body)


# ---------- enqueue_event ----------


async def test_enqueue_event_zero_subscriptions_returns_zero():
    from services.webhooks import enqueue_event

    session = FakeAsyncSession()
    # Default execute() returns empty scalars → no subscriptions match
    n = await enqueue_event(
        session,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        event_type="handover.defect.reported",
        payload={},
    )
    assert n == 0
    # Only the discovery query fires; no INSERT.
    assert len(session.calls) == 1


async def test_enqueue_event_inserts_one_row_per_subscription():
    from services.webhooks import enqueue_event

    session = FakeAsyncSession()
    # Discovery returns 3 subscriptions
    sub_ids = [uuid4(), uuid4(), uuid4()]
    discovery = MagicMock()
    discovery.scalars.return_value.all.return_value = sub_ids
    session.push(discovery)

    n = await enqueue_event(
        session,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        event_type="pulse.change_order.approve",
        payload={"co_id": str(uuid4())},
    )
    assert n == 3
    # 1 discovery + 3 INSERTs = 4 execute calls total
    assert len(session.calls) == 4
    # Each INSERT has the same org + event_type bound
    for _stmt, params in session.calls[1:]:
        assert params["org"] == str(ORG_ID)
        assert params["event_type"] == "pulse.change_order.approve"
        assert "id" in params
        assert "sub" in params


async def test_enqueue_event_warns_on_unknown_type_but_still_enqueues(caplog):
    """A typo at the call site shouldn't break the request. We log a
    warning and proceed (subscriptions filter on event_type at delivery
    time anyway)."""
    import logging

    from services.webhooks import enqueue_event

    session = FakeAsyncSession()
    # No subscribers → no INSERTs but the warning should fire.
    caplog.set_level(logging.WARNING, logger="services.webhooks")
    n = await enqueue_event(
        session,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        event_type="totally.made.up",
        payload={},
    )
    assert n == 0
    assert any("unknown type" in r.message for r in caplog.records)


# ---------- drain_pending: empty queue ----------


async def test_drain_pending_empty_returns_zeros():
    from services.webhooks import drain_pending

    session = FakeAsyncSession()
    # Default execute returns empty mappings → no due rows.
    result = await drain_pending(session)  # type: ignore[arg-type]
    assert result == {"picked": 0, "delivered": 0, "failed": 0, "retried": 0}


# ---------- drain_pending: success path ----------


def _due_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": uuid4(),
        "subscription_id": SUB_ID,
        "organization_id": ORG_ID,
        "event_type": "handover.defect.reported",
        "payload": {"defect_id": str(uuid4())},
        "attempt_count": 0,
        "url": "https://example.com/hook",
        "secret": "abc" * 22 + "ab",  # 64 chars
        "failure_count": 0,
    }
    base.update(overrides)
    return base


async def test_drain_pending_marks_delivered_on_2xx(monkeypatch):
    from services.webhooks import drain_pending

    session = FakeAsyncSession()
    # 1 due row.
    due = MagicMock()
    due.mappings.return_value.all.return_value = [_due_row()]
    session.push(due)

    # Stub `httpx.AsyncClient.post` via a context-manager-aware mock.
    sent = []

    async def fake_post(url, content, headers):
        sent.append({"url": url, "headers": dict(headers), "body_len": len(content)})
        res = MagicMock()
        res.status_code = 200
        res.text = "ok"
        return res

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, content, headers):
            return await fake_post(url, content, headers)

    import services.webhooks as svc

    monkeypatch.setattr(svc, "httpx", MagicMock(AsyncClient=lambda **_: _FakeClient()))

    result = await drain_pending(session)  # type: ignore[arg-type]
    assert result["picked"] == 1
    assert result["delivered"] == 1
    assert result["failed"] == 0
    assert result["retried"] == 0

    # Headers carry the signature + event metadata.
    assert sent[0]["headers"]["X-AEC-Signature"].startswith("sha256=")
    assert sent[0]["headers"]["X-AEC-Event-Type"] == "handover.defect.reported"
    assert "X-AEC-Delivery-ID" in sent[0]["headers"]
    assert "X-AEC-Timestamp" in sent[0]["headers"]


async def test_drain_pending_schedules_retry_on_5xx(monkeypatch):
    """Non-2xx response → row stays `pending` with a future retry_at,
    NOT permanently failed (assuming we're under the attempt cap)."""
    from services.webhooks import drain_pending

    session = FakeAsyncSession()
    due = MagicMock()
    due.mappings.return_value.all.return_value = [_due_row(attempt_count=0)]
    session.push(due)

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, content, headers):
            res = MagicMock()
            res.status_code = 503
            res.text = "service unavailable"
            return res

    import services.webhooks as svc

    monkeypatch.setattr(svc, "httpx", MagicMock(AsyncClient=lambda **_: _FakeClient()))

    result = await drain_pending(session)  # type: ignore[arg-type]
    assert result["picked"] == 1
    assert result["delivered"] == 0
    assert result["retried"] == 1
    assert result["failed"] == 0


async def test_drain_pending_marks_failed_after_max_attempts(monkeypatch):
    """At attempt_count == 5 (going to attempt 6 = len(_BACKOFF_MINUTES)),
    a non-2xx flips to permanent `failed` instead of scheduling another
    retry. Pin the cap so a future change to _BACKOFF_MINUTES doesn't
    quietly extend the retry window."""
    from services.webhooks import drain_pending

    session = FakeAsyncSession()
    due = MagicMock()
    # attempt_count=5 → next attempt = 6 → exceeds len(_BACKOFF_MINUTES)
    due.mappings.return_value.all.return_value = [_due_row(attempt_count=5)]
    session.push(due)

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, content, headers):
            res = MagicMock()
            res.status_code = 500
            res.text = "boom"
            return res

    import services.webhooks as svc

    monkeypatch.setattr(svc, "httpx", MagicMock(AsyncClient=lambda **_: _FakeClient()))

    result = await drain_pending(session)  # type: ignore[arg-type]
    assert result["failed"] == 1
    assert result["retried"] == 0


async def test_drain_pending_handles_timeout_as_retry(monkeypatch):
    """A network timeout is a transient failure — schedule a retry,
    don't fail permanently."""
    import httpx as real_httpx

    from services.webhooks import drain_pending

    session = FakeAsyncSession()
    due = MagicMock()
    due.mappings.return_value.all.return_value = [_due_row(attempt_count=0)]
    session.push(due)

    class _TimingOutClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, content, headers):
            raise real_httpx.TimeoutException("read timeout")

    import services.webhooks as svc

    monkeypatch.setattr(
        svc,
        "httpx",
        MagicMock(
            AsyncClient=lambda **_: _TimingOutClient(),
            TimeoutException=real_httpx.TimeoutException,
            RequestError=real_httpx.RequestError,
        ),
    )

    result = await drain_pending(session)  # type: ignore[arg-type]
    assert result["retried"] == 1
    assert result["failed"] == 0
