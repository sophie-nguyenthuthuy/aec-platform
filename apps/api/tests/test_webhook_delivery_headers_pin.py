"""Pin the headers `_deliver_one` POSTs on every webhook delivery.

Why this exists: every successful delivery to a customer's URL
carries five headers that together implement the webhook contract:

  * `Content-Type: application/json` — receivers reject non-JSON.
  * `X-AEC-Signature: sha256=<hex>` — HMAC-SHA256 of the body, the
    receiver's only cryptographic proof the event came from us.
  * `X-AEC-Event-Type: <event_type>` — lets receivers route on
    type without parsing the body.
  * `X-AEC-Delivery-ID: <uuid>` — idempotency key. Receivers dedupe
    on this so a redelivered event isn't double-processed.
  * `X-AEC-Timestamp: <unix_seconds>` — replay-attack defense.
    Receivers using `verify_payload` reject deliveries with skew
    >5 minutes from their wall clock.

A revert that drops any one of these has a different silent failure
mode:

  * Drop `X-AEC-Signature` → receiver auth fails; deliveries 401.
  * Drop `X-AEC-Event-Type` → receivers either reject or process
    every event identically (varies by receiver implementation).
  * Drop `X-AEC-Delivery-ID` → idempotency is gone; a redeliver
    after a network blip double-charges / double-creates.
  * Drop `X-AEC-Timestamp` → `verify_payload`-using receivers
    reject every delivery as un-timestamped.

This test mocks httpx, intercepts the POST, and asserts all five
headers are present + well-formed. The full set is small enough
to enumerate exactly so a "let's clean up the User-Agent header"
refactor that accidentally drops one of the X-AEC ones surfaces
as a loud failure.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from services.webhooks import _deliver_one

pytestmark = pytest.mark.asyncio


class _CapturingClient:
    """Drop-in for `httpx.AsyncClient` that captures the most recent
    POST without doing network I/O.

    `_deliver_one` constructs the body + headers + calls
    `http.post(url, content=..., headers=...)` — we intercept that
    call and stash the kwargs so the test assertions can read them
    back.
    """

    def __init__(self) -> None:
        self.captured: dict[str, Any] = {}

    async def post(self, url: str, *, content: bytes, headers: dict[str, str]):
        self.captured = {"url": url, "content": content, "headers": dict(headers)}

        # Mimic the response shape `_deliver_one` reads — a 200 with
        # a small body. The actual send-vs-receive logic isn't what
        # this test pins; we just need the function to complete
        # without raising.
        class _Resp:
            status_code = 200
            text = "ok"

        return _Resp()


async def test_deliver_one_emits_all_five_required_headers():
    """Pin the five-header set + their value shapes.

    `Content-Type` must be `application/json` — receivers reject
    other types. The four X-AEC headers are documented in the
    module docstring of `services.webhooks`; this test pins them
    by name so a revert can't silently drop one.
    """
    client = _CapturingClient()
    delivery_id = uuid4()

    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret="0" * 64,
        event_type="costpulse.estimate.approve",
        delivery_id=delivery_id,
        payload={"resource_id": "abc"},
    )

    headers = client.captured["headers"]
    expected_keys = {
        "Content-Type",
        "X-AEC-Signature",
        "X-AEC-Event-Type",
        "X-AEC-Delivery-ID",
        "X-AEC-Timestamp",
    }
    missing = expected_keys - headers.keys()
    assert not missing, (
        f"_deliver_one dropped these required headers: {sorted(missing)}. "
        "Each one has a different downstream failure mode — see file "
        "docstring."
    )


async def test_deliver_one_signature_header_format():
    """`X-AEC-Signature` must be `sha256=<hex>` form. The receiver's
    canonical verification reads:

        sig = header.split('sha256=', 1)[-1]
        hmac.compare_digest(sig, expected_hex)

    A regression that emits the bare hex (without the `sha256=`
    prefix) silently breaks every receiver that uses the
    documented two-step parse, even though the HMAC bytes are
    correct.
    """
    client = _CapturingClient()
    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret="x" * 64,
        event_type="webhook.test",
        delivery_id=uuid4(),
        payload={},
    )
    sig = client.captured["headers"]["X-AEC-Signature"]
    assert sig.startswith("sha256="), f"X-AEC-Signature header should start with 'sha256='; got {sig!r}"
    # 64 hex chars after the prefix → SHA256 digest length.
    digest = sig.removeprefix("sha256=")
    assert len(digest) == 64, f"X-AEC-Signature digest is {len(digest)} chars; SHA256 hex is 64."
    # All hex digits — bytes.fromhex would raise on a non-hex char.
    bytes.fromhex(digest)


async def test_deliver_one_event_type_header_echoes_payload_kind():
    """`X-AEC-Event-Type` must equal the `event_type` argument
    verbatim. A regression that lowercased it / stripped dotted
    segments would break receivers that route on the value."""
    client = _CapturingClient()
    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret="x" * 64,
        event_type="costpulse.rfq.slots_expired",
        delivery_id=uuid4(),
        payload={},
    )
    assert client.captured["headers"]["X-AEC-Event-Type"] == "costpulse.rfq.slots_expired"


async def test_deliver_one_delivery_id_header_is_uuid_string():
    """`X-AEC-Delivery-ID` must be the stringified UUID. Receivers
    use it as an idempotency key — a regression that emitted the
    raw `UUID(...)` repr or a truncated form would break dedupe on
    the receiver's side, leading to double-processing on retry.
    """
    client = _CapturingClient()
    delivery_id = uuid4()
    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret="x" * 64,
        event_type="webhook.test",
        delivery_id=delivery_id,
        payload={},
    )
    actual = client.captured["headers"]["X-AEC-Delivery-ID"]
    assert actual == str(delivery_id)
    # 36 chars / 4 hyphens — standard UUID hex form.
    assert len(actual) == 36
    assert actual.count("-") == 4


async def test_deliver_one_timestamp_header_is_unix_seconds():
    """`X-AEC-Timestamp` must be the unix-seconds integer as a
    string. `verify_payload` parses it as `int(header)`; a
    regression that emitted ISO-8601 or float seconds would break
    the int-parse on the receiver's side and reject every
    delivery as un-timestamped."""
    import time as time_mod

    client = _CapturingClient()
    before = int(time_mod.time())

    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret="x" * 64,
        event_type="webhook.test",
        delivery_id=uuid4(),
        payload={},
    )
    after = int(time_mod.time())

    ts_str = client.captured["headers"]["X-AEC-Timestamp"]
    # Must parse cleanly as int — the canonical receiver parse.
    ts = int(ts_str)
    # Within a 2-second window of when the test ran.
    assert before <= ts <= after + 1, (
        f"X-AEC-Timestamp {ts} not within [{before}, {after + 1}]. "
        "If `time.time()` was replaced with something else (e.g. `now()`), "
        "verify the spelling parses cleanly as int."
    )


async def test_deliver_one_content_type_is_application_json():
    """`Content-Type: application/json` is the canonical webhook
    payload format. A regression to text/plain or multipart would
    silently break any receiver that does
    `if request.content_type != 'application/json': return 415`.
    """
    client = _CapturingClient()
    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret="x" * 64,
        event_type="webhook.test",
        delivery_id=uuid4(),
        payload={},
    )
    assert client.captured["headers"]["Content-Type"] == "application/json"


async def test_deliver_one_signature_matches_body_under_secret():
    """End-to-end sanity: the HMAC in the header must verify
    against the body under the supplied secret. This duplicates
    the unit-test of `sign_payload` in
    `test_webhooks_replay_defense.py` from the integration angle —
    a refactor that swapped in a different signing algorithm
    (HMAC-SHA1, plain hash, etc.) would silently produce
    well-formed signatures that no receiver could verify.
    """
    import hashlib
    import hmac

    secret = "deadbeef" * 8  # 64 chars, fixed so the test is deterministic.
    client = _CapturingClient()
    await _deliver_one(
        client,
        url="https://example.com/hook",
        secret=secret,
        event_type="webhook.test",
        delivery_id=uuid4(),
        payload={"x": 1},
    )

    body = client.captured["content"]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    actual = client.captured["headers"]["X-AEC-Signature"].removeprefix("sha256=")
    assert hmac.compare_digest(expected, actual), (
        "X-AEC-Signature doesn't verify against the captured body under the "
        "supplied secret — `_deliver_one` may have switched signing algorithm."
    )
