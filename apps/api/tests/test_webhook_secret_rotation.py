"""Unit tests for the webhook secret rotation flow (cycle O1).

The rotation surface has three seams that all have to line up or
the customer's receiver breaks:

  1. **Service-level swap.** `services.webhooks.rotate_secret` runs
     a single `UPDATE … RETURNING` that moves `secret` →
     `secret_previous`, sets the expiry, and writes a fresh secret.
     The org-scope check is in the WHERE so a wrong-org call returns
     None (the router 404s) without ever reaching the DB. Pin the
     bound params so a refactor can't silently drop them.

  2. **Dispatcher dual-signature emit.** `_deliver_one` emits a
     second header `X-AEC-Signature-Previous` ONLY inside the grace
     window. Outside the window, the function's wire shape is
     identical to the pre-rotation form. Pin both branches.

  3. **`_previous_secret_active` decision rule.** Pure helper that
     decides whether to emit the second signature. Three guards:
     * No previous secret → False.
     * No expiry → False.
     * Expiry in the past → False.
     * Otherwise → True.

The tests use the same `_CapturingClient` shape as
`test_webhook_delivery_headers_pin.py` so the pattern is consistent;
a future refactor that touches both files at once will see the same
mock surface in each.

Why not call the router end-to-end here: the router test path needs
a real DB transaction (the UPDATE's RETURNING + commit). That
coverage lives in `test_webhooks_router.py` (existing). This module
isolates the service-level + dispatcher seams so a bug in either
fails ONE focused test rather than a noisy integration assertion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from services.webhooks import (
    DEFAULT_ROTATION_GRACE_SECONDS,
    _deliver_one,
    _previous_secret_active,
    rotate_secret,
)

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
SUB_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


# ---------- _previous_secret_active (pure helper) ------------------


def test_previous_secret_active_returns_false_when_no_previous():
    """No rotation has happened — the dispatcher must NOT emit a
    second header. The default branch keeps the helper a strict
    superset of the pre-rotation contract."""
    assert _previous_secret_active(None, None) is False
    # Even if an expiry is set (corrupt row, programmer bug), absent
    # secret material → can't sign → False.
    assert _previous_secret_active(None, datetime.now(UTC) + timedelta(hours=1)) is False


def test_previous_secret_active_returns_false_when_expiry_unset():
    """A populated `secret_previous` with no expiry would otherwise
    leak indefinitely. Treat as inactive — defensive against a
    malformed write that sets the secret without the expiry."""
    assert _previous_secret_active("old-secret", None) is False


def test_previous_secret_active_returns_false_when_expired():
    """The grace window has passed. The helper rejects so the
    dispatcher stops emitting the second signature, matching the
    quiet-retirement contract documented in `_deliver_one`."""
    past = datetime.now(UTC) - timedelta(seconds=1)
    assert _previous_secret_active("old-secret", past) is False


def test_previous_secret_active_returns_true_inside_window():
    """Both columns populated AND expiry in the future → emit the
    second signature. The single happy-path branch."""
    future = datetime.now(UTC) + timedelta(hours=1)
    assert _previous_secret_active("old-secret", future) is True


def test_previous_secret_active_takes_explicit_now_for_determinism():
    """The `now` kwarg lets tests pin the boundary without monkey-
    patching `datetime.now`. Pin the contract so a refactor that
    drops the kwarg breaks here, not at a flaky boundary test."""
    fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    expires = datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)  # 1s in the future
    assert _previous_secret_active("old", expires, now=fixed_now) is True
    # Same expiry, "now" past it → False.
    after_expiry = datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC)
    assert _previous_secret_active("old", expires, now=after_expiry) is False


# ---------- rotate_secret (DB seam) --------------------------------


class FakeAsyncSession:
    """Minimal stand-in for AsyncSession used by `rotate_secret`.

    Captures the SQL + bound params so the test can assert what got
    sent to the DB without a real Postgres connection. `push_result`
    queues the next `execute()` return value.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self.commits = 0
        self._results: list[Any] = []

    def push_result(self, result: Any) -> None:
        self._results.append(result)

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        # Default: empty result (UPDATE matched 0 rows).
        r = MagicMock()
        r.first.return_value = None
        return r

    async def commit(self) -> None:
        self.commits += 1


async def test_rotate_secret_returns_new_secret_and_commits():
    """Happy path: row exists in the caller's org, the UPDATE
    matches, helper returns the new secret string + commits the
    transaction.

    Pin both side-effects in the same test — a bug that returned
    the secret without committing would leave the customer with a
    secret that doesn't match the DB; a bug that committed but
    returned None would force a manual SQL recovery to find the
    just-written value."""
    db = FakeAsyncSession()
    insert_result = MagicMock()
    insert_result.first.return_value = MagicMock()  # one row matched
    db.push_result(insert_result)

    new_secret = await rotate_secret(
        db,
        subscription_id=SUB_ID,
        organization_id=ORG_ID,
    )

    assert new_secret is not None
    # 64-char hex (32 bytes) — same shape as `generate_secret()`.
    assert len(new_secret) == 64
    assert all(c in "0123456789abcdef" for c in new_secret)
    assert db.commits == 1, (
        "rotate_secret must commit on success — uncommitted, the customer's receiver and our DB diverge"
    )


async def test_rotate_secret_returns_none_when_row_missing():
    """No rows matched — wrong org, deleted subscription, or typo'd
    UUID. The helper returns None so the router 404s; nothing is
    committed (no state to flush)."""
    db = FakeAsyncSession()
    empty_result = MagicMock()
    empty_result.first.return_value = None
    db.push_result(empty_result)

    out = await rotate_secret(
        db,
        subscription_id=SUB_ID,
        organization_id=ORG_ID,
    )
    assert out is None
    assert db.commits == 0, (
        "Empty UPDATE must not commit — committing nothing is harmless "
        "but pinning the contract avoids a future refactor that adds "
        "side effects above the matched-check."
    )


async def test_rotate_secret_passes_grace_seconds_through():
    """The grace_seconds kwarg threads into the SQL bind — without
    that, the UPDATE always uses the default. Pin the parameter so a
    refactor that drops `:grace_seconds` from the SQL fails this test
    instead of silently shipping a permanent 24h grace."""
    db = FakeAsyncSession()
    matched = MagicMock()
    matched.first.return_value = MagicMock()
    db.push_result(matched)

    await rotate_secret(
        db,
        subscription_id=SUB_ID,
        organization_id=ORG_ID,
        grace_seconds=3600,  # 1 hour, not the default 24h
    )
    params = db.calls[0][1]
    assert params["grace_seconds"] == 3600
    # The id + org_id are also bound — pin so a refactor that
    # accidentally widens the WHERE clause (e.g. drops org_id)
    # surfaces here.
    assert params["id"] == str(SUB_ID)
    assert params["org_id"] == str(ORG_ID)


async def test_default_rotation_grace_is_24_hours():
    """The constant must be exactly 24h. Operationally the customer
    needs predictable rollover; a "let's lower to 1h" PR should be a
    deliberate decision documented in the diff."""
    assert DEFAULT_ROTATION_GRACE_SECONDS == 24 * 60 * 60


# ---------- _deliver_one dual-signature emit -----------------------


class _CapturingClient:
    """Same shape as `test_webhook_delivery_headers_pin.py`'s helper —
    intercepts the POST without hitting the network."""

    def __init__(self) -> None:
        self.captured: dict[str, Any] = {}

    async def post(self, url: str, *, content: bytes, headers: dict[str, str]):
        self.captured = {"url": url, "content": content, "headers": dict(headers)}

        class _Resp:
            status_code = 200
            text = "ok"

        return _Resp()


async def test_deliver_one_omits_second_signature_outside_grace():
    """No rotation in flight (or grace expired) → only the primary
    `X-AEC-Signature` header. Wire shape identical to the pre-
    rotation contract.

    This is the steady-state path: every delivery for a subscription
    that's never rotated, AND every delivery after the grace expires.
    """
    client = _CapturingClient()
    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret="x" * 64,
        secret_previous=None,  # no rotation in flight
        secret_previous_expires_at=None,
        event_type="webhook.test",
        delivery_id=uuid4(),
        payload={},
    )
    headers = client.captured["headers"]
    assert "X-AEC-Signature" in headers
    assert "X-AEC-Signature-Previous" not in headers, (
        "Outside the grace window the dispatcher must NOT emit the "
        "second header — receivers that explicitly check headers for "
        "presence would otherwise see drift."
    )


async def test_deliver_one_emits_second_signature_inside_grace():
    """Rotation in flight + grace not expired → both signatures.
    Receivers can verify against either one, letting them roll
    forward to the new secret without a flag-day deploy."""
    client = _CapturingClient()
    future = datetime.now(UTC) + timedelta(hours=1)
    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret="new-secret-" + "a" * 50,
        secret_previous="old-secret-" + "b" * 50,
        secret_previous_expires_at=future,
        event_type="webhook.test",
        delivery_id=uuid4(),
        payload={"resource_id": "abc"},
    )
    headers = client.captured["headers"]
    assert "X-AEC-Signature" in headers
    assert "X-AEC-Signature-Previous" in headers, (
        "Inside the grace window the dispatcher MUST emit both signatures so receivers can verify against either."
    )
    # Both must be sha256= hex form — same wire format.
    assert headers["X-AEC-Signature"].startswith("sha256=")
    assert headers["X-AEC-Signature-Previous"].startswith("sha256=")


async def test_deliver_one_dual_signatures_verify_under_each_secret():
    """End-to-end: each header must HMAC-verify against the body
    under its corresponding secret. A regression that signed BOTH
    headers with the same key (e.g. always the new secret) would
    break receivers running on the old secret — exactly the case
    rotation is meant to make safe."""
    import hashlib
    import hmac

    new_secret = "deadbeef" * 8  # 64 chars
    old_secret = "feedface" * 8  # 64 chars
    client = _CapturingClient()
    future = datetime.now(UTC) + timedelta(hours=1)
    payload = {"x": 1}
    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret=new_secret,
        secret_previous=old_secret,
        secret_previous_expires_at=future,
        event_type="webhook.test",
        delivery_id=uuid4(),
        payload=payload,
    )
    body = client.captured["content"]
    headers = client.captured["headers"]

    expected_new = hmac.new(new_secret.encode(), body, hashlib.sha256).hexdigest()
    expected_old = hmac.new(old_secret.encode(), body, hashlib.sha256).hexdigest()

    actual_new = headers["X-AEC-Signature"].removeprefix("sha256=")
    actual_old = headers["X-AEC-Signature-Previous"].removeprefix("sha256=")

    assert hmac.compare_digest(expected_new, actual_new), (
        "X-AEC-Signature must verify under the NEW secret. Regression suggests the dispatcher swapped the secrets."
    )
    assert hmac.compare_digest(expected_old, actual_old), (
        "X-AEC-Signature-Previous must verify under the OLD secret. "
        "Regression suggests both headers are signed with the same key."
    )
    # And — crucially — they must NOT match each other. If they did,
    # rotation has bought us nothing because both headers carry the
    # same crypto.
    assert actual_new != actual_old, (
        "Dual signatures are identical — rotation is a no-op for the "
        "receiver. Likely cause: `secret_previous` is being signed "
        "with the new secret instead of the previous secret."
    )


async def test_deliver_one_omits_second_signature_after_expiry():
    """Grace window has just elapsed (expiry == 1 second ago).
    Even though both columns are populated, the helper rejects and
    the dispatcher emits only the primary signature.

    This is the boundary the cron-driven cleanup relies on — once
    grace expires, receivers running on the old secret stop
    verifying and their owners must roll forward."""
    client = _CapturingClient()
    expired = datetime.now(UTC) - timedelta(seconds=1)
    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret="x" * 64,
        secret_previous="old-secret-" + "y" * 50,
        secret_previous_expires_at=expired,
        event_type="webhook.test",
        delivery_id=uuid4(),
        payload={},
    )
    headers = client.captured["headers"]
    assert "X-AEC-Signature-Previous" not in headers, (
        "Past expiry, the second signature must be omitted — that's "
        "the contract that retires the old secret on the dispatcher's "
        "side without a separate cleanup cron."
    )
