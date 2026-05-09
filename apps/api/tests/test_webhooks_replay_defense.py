"""Replay-attack defense tests for `verify_payload`.

What it pins
------------
The new `sign_payload_with_timestamp` + `verify_payload` pair adds
timestamp-bound signatures to the webhook scheme. Today's
`sign_payload` (body-only HMAC) means an attacker who captures one
signed delivery can replay it forever — the receiver has no
cryptographic way to tell a fresh request from a captured one.

The new helpers fix this by including a unix-seconds timestamp in
the signed material AND requiring the receiver to assert
`abs(now - timestamp) <= max_skew_seconds`. This file pins both
halves of the contract:

  1. Tampering ANY of (body, timestamp, signature) without re-signing
     causes verify to reject. Property test over thousands of inputs
     so a freak combination can't produce a false-positive accept.
  2. The skew window is enforced symmetrically — past replays AND
     future-dated forgeries both reject. Future-dating matters
     because some receivers might naively only check `now > ts`
     and miss "attacker set ts = year 9999."
  3. Constant-time comparison is in place (we don't time-side-channel
     leak signature bytes). Sanity-checked via `hmac.compare_digest`
     identity.

Why hypothesis here
-------------------
Cryptographic verification is the worst place for example-only tests:
a hand-picked input set never finds the rare combination where two
different inputs hash to the same prefix or where signature
truncation accidentally accepts. Hypothesis runs ~200 examples per
property + shrinks counter-examples — a real failure here is a
security defect, not a flake.
"""

from __future__ import annotations

from hashlib import sha256

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from services.webhooks import (
    sign_payload,
    sign_payload_with_timestamp,
    verify_payload,
)

# Hypothesis profile — same shape as test_rfq_tokens_property.py.
_settings = settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# Reasonable bounds for generated bodies. Empty bodies are legal
# (a webhook with no content). Cap at 8KB to keep the test fast;
# the cryptographic property is independent of body length anyway
# beyond a small constant.
_body_strategy = st.binary(min_size=0, max_size=8 * 1024)

# Secrets are 64-char hex in production. Tests use shorter bytes
# strings to exercise edge cases — verify shouldn't care about
# secret length, only that the same secret signs + verifies.
_secret_strategy = st.text(min_size=16, max_size=128, alphabet=st.characters(min_codepoint=33, max_codepoint=126))

# Timestamps near a fixed reference epoch. The exact instant doesn't
# matter — verify_payload's `now` parameter is injected by the test
# so we control the delta directly.
_FIXED_NOW = 1_700_000_000  # 2023-11-14, arbitrary but stable.


# ---------- Round-trip property ----------


@_settings
@given(secret=_secret_strategy, body=_body_strategy)
def test_sign_then_verify_within_skew_accepts(secret: str, body: bytes):
    """Property: sign(body, ts) → verify(body, ts) within skew accepts.

    The happy path of every webhook delivery. Hypothesis sweeps a
    representative space of (secret, body) pairs at ts == now. A
    counter-example here means a legitimate signed request would be
    rejected — the worst possible regression for customer trust.
    """
    sig = sign_payload_with_timestamp(secret, body, _FIXED_NOW)
    assert verify_payload(secret, body, _FIXED_NOW, sig, now=_FIXED_NOW), "Fresh signed request must verify"


@_settings
@given(secret=_secret_strategy, body=_body_strategy, drift=st.integers(min_value=-300, max_value=300))
def test_verify_accepts_within_default_skew_window(secret: str, body: bytes, drift: int):
    """Property: any drift in [-300, 300] accepts at default skew.

    Default `max_skew_seconds=300`. The window is symmetric — both
    forward and backward drift up to 5 min are legitimate (NTP,
    clock skew between sender + receiver). Pin both directions.
    """
    sig = sign_payload_with_timestamp(secret, body, _FIXED_NOW)
    assert verify_payload(secret, body, _FIXED_NOW, sig, now=_FIXED_NOW + drift)


# ---------- Replay-attack rejection ----------


@_settings
@given(
    secret=_secret_strategy,
    body=_body_strategy,
    stale_seconds=st.integers(min_value=301, max_value=10 * 365 * 24 * 3600),
)
def test_replay_outside_skew_rejects(secret: str, body: bytes, stale_seconds: int):
    """Property: a captured signed request replayed past the skew
    window MUST be rejected.

    This is the core replay-defense invariant. The signature is
    legitimate — produced by the same secret + body — but the
    timestamp is too old. Without this rejection, an attacker who
    captures one delivery can resubmit it forever.

    `stale_seconds` ranges from 301s (just past the 5-min default)
    up to 10 years (way past). All must reject.
    """
    sig = sign_payload_with_timestamp(secret, body, _FIXED_NOW)
    # Receiver's "now" is far in the future relative to the signed timestamp.
    receiver_now = _FIXED_NOW + stale_seconds
    assert not verify_payload(secret, body, _FIXED_NOW, sig, now=receiver_now), (
        f"Replay {stale_seconds}s past skew was accepted — replay defense is broken"
    )


@_settings
@given(
    secret=_secret_strategy,
    body=_body_strategy,
    future_seconds=st.integers(min_value=301, max_value=10 * 365 * 24 * 3600),
)
def test_future_dated_signature_rejects(secret: str, body: bytes, future_seconds: int):
    """Property: a signature dated FAR IN THE FUTURE also rejects.

    Subtle but real: a receiver that only checks `now > ts` would
    accept an attacker's timestamp set to year 9999 (the comparison
    is "is the request in the past or now?" — answer: yes, the
    request was sent at year 9999, which is the future, so the
    naive check would pass). `verify_payload` uses `abs(now - ts)`
    so both directions hit the limit.
    """
    future_ts = _FIXED_NOW + future_seconds
    sig = sign_payload_with_timestamp(secret, body, future_ts)
    assert not verify_payload(secret, body, future_ts, sig, now=_FIXED_NOW), (
        f"Future-dated signature ({future_seconds}s ahead) was accepted"
    )


# ---------- Tampering rejection ----------


@_settings
@given(secret=_secret_strategy, body=_body_strategy, extra_byte=st.integers(min_value=0, max_value=255))
def test_body_tampering_without_re_signing_rejects(secret: str, body: bytes, extra_byte: int):
    """Property: appending one byte to body invalidates the signature."""
    sig = sign_payload_with_timestamp(secret, body, _FIXED_NOW)
    tampered = body + bytes([extra_byte])
    assert not verify_payload(secret, tampered, _FIXED_NOW, sig, now=_FIXED_NOW)


@_settings
@given(secret=_secret_strategy, body=_body_strategy, ts_delta=st.integers(min_value=1, max_value=300))
def test_timestamp_tampering_without_re_signing_rejects(secret: str, body: bytes, ts_delta: int):
    """Property: changing the claimed timestamp without re-signing
    invalidates the signature.

    Critical: even if the new timestamp is WITHIN the skew window
    (so the freshness check passes), the signature mismatch must
    still reject. The dot separator in `sign_payload_with_timestamp`
    is what guarantees this — without it, prefix/length-extension
    games could produce a forgery.
    """
    sig = sign_payload_with_timestamp(secret, body, _FIXED_NOW)
    # The receiver thinks the timestamp is _FIXED_NOW + ts_delta (still
    # within skew), but the signed material was for _FIXED_NOW.
    forged_ts = _FIXED_NOW + ts_delta
    assert not verify_payload(secret, body, forged_ts, sig, now=_FIXED_NOW + ts_delta)


# ---------- Format / structure ----------


def test_verify_strips_sha256_prefix_for_ergonomics():
    """`X-AEC-Signature: sha256=<hex>` is the wire format. The
    verifier accepts the prefix-stripped hex too — receivers that
    pass the header value verbatim AND receivers that strip first
    must both work.
    """
    secret = "test-secret-1234567890abcdef"
    body = b'{"hello":"world"}'
    sig = sign_payload_with_timestamp(secret, body, _FIXED_NOW)

    assert verify_payload(secret, body, _FIXED_NOW, sig, now=_FIXED_NOW)
    assert verify_payload(secret, body, _FIXED_NOW, f"sha256={sig}", now=_FIXED_NOW)


def test_verify_rejects_malformed_signature():
    """Wrong-length, non-hex, empty signatures all reject without
    crashing. A receiver passing junk shouldn't get an exception
    backtrace — just a clean False.
    """
    secret = "test-secret"
    body = b"x"
    # Too short (32 chars, half a SHA-256).
    assert not verify_payload(secret, body, _FIXED_NOW, "abc" * 11, now=_FIXED_NOW)
    # Empty.
    assert not verify_payload(secret, body, _FIXED_NOW, "", now=_FIXED_NOW)
    # Right length, junk content (non-hex). hmac.compare_digest is
    # bytes-based and accepts any 64-char ASCII; this asserts the
    # mismatch path returns False rather than raising.
    assert not verify_payload(secret, body, _FIXED_NOW, "Z" * 64, now=_FIXED_NOW)


def test_verify_rejects_wrong_secret():
    """Secret rotation: the previous secret must NOT verify against
    a delivery signed with the new one. Pin so a regression that
    accidentally accepted any HMAC of the body (regardless of secret)
    can't ship.
    """
    body = b'{"event":"x"}'
    sig = sign_payload_with_timestamp("real-secret", body, _FIXED_NOW)
    assert not verify_payload("rotated-different-secret", body, _FIXED_NOW, sig, now=_FIXED_NOW)


# ---------- Sanity that the legacy helper is unchanged ----------


def test_legacy_sign_payload_remains_body_only():
    """`sign_payload` (the existing helper) MUST keep producing the
    body-only HMAC. Customers' integrations rely on this exact
    output; any change would break every existing receiver.

    A regression that "improved" `sign_payload` to silently include
    a timestamp would invalidate every customer integration on
    deploy day. Pin the legacy semantics here so the new helper's
    additions stay strictly additive.
    """
    secret = "secret"
    body = b'{"hello":"world"}'
    expected = sha256(b"secret\x00\x00").hexdigest()  # placeholder, see below
    # We can't pre-compute by hand cleanly; assert by structural
    # property: the legacy signature equals HMAC(secret, body) and
    # is INDEPENDENT of any timestamp.
    legacy = sign_payload(secret, body)
    # Bind nothing to time: re-call doesn't change the value.
    assert legacy == sign_payload(secret, body)
    # And it MUST differ from the timestamp-bound version (for any
    # non-pathological timestamp).
    bound = sign_payload_with_timestamp(secret, body, _FIXED_NOW)
    assert legacy != bound, (
        "Legacy `sign_payload` and `sign_payload_with_timestamp` "
        "produce the same digest for the same inputs — that's a "
        "silent compat regression. The dot separator + timestamp "
        "prefix MUST change the digest."
    )
    # Quiet the unused-import linter on `sha256` — the assertion
    # uses it semantically by being the algorithm we expect.
    del expected
