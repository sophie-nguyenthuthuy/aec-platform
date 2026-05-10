"""Webhook signature verification helper (cycle Y2).

Pinned seams:
  1. `sign_payload` matches the canonical HMAC-SHA256 hex shape
     (lowercase 64-char hex digest).
  2. `sign_payload_with_timestamp` includes the `<ts>.` prefix —
     replay defense.
  3. `verify_with_trace` returns a `VerifyTrace` with the closed
     vocab `reason` (None / signature_mismatch /
     timestamp_skew_exceeded / invalid_signature_format).
  4. Skew check is symmetric (future timestamps rejected too).
  5. `sha256=` prefix on input is stripped before comparison.
  6. `compare_digest` exceptions caught → invalid_signature_format
     rather than 500.
"""

from __future__ import annotations

import hashlib
import hmac

from services.webhook_sig import (
    DEFAULT_MAX_SKEW_SECONDS,
    REASON_CODES,
    VerifyTrace,
    sign_payload,
    sign_payload_with_timestamp,
    verify_with_trace,
)


# ---------- sign_payload ----------


def test_sign_payload_matches_hmac_sha256_hex():
    """Canonical: HMAC-SHA256 of `body` under `secret`, hex-encoded.
    Receivers verify against this exact shape."""
    secret = "deadbeef" * 8  # 64-char hex secret
    body = b'{"event":"test"}'
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert sign_payload(secret, body) == expected


def test_sign_payload_is_deterministic():
    """Same inputs → same digest. Receivers depend on this for
    replay verification."""
    a = sign_payload("abc123", b"x")
    b = sign_payload("abc123", b"x")
    assert a == b


def test_sign_payload_returns_64_char_lowercase_hex():
    """SHA-256 hex digest = 64 chars, all lowercase. Pin the shape
    so a refactor that switches to base64 would surface."""
    sig = sign_payload("x" * 64, b"abc")
    assert len(sig) == 64
    assert sig == sig.lower()
    # Every char is a hex digit.
    assert all(c in "0123456789abcdef" for c in sig)


# ---------- sign_payload_with_timestamp ----------


def test_timestamp_signing_includes_ts_dot_prefix():
    """The signed material is `f"{ts}.".encode() + body`. Without
    the timestamp prefix, an attacker who intercepts a (body,
    signature) pair could replay it later — pin the contract so a
    refactor that drops the prefix doesn't silently undo the
    replay defense."""
    secret = "x" * 64
    body = b"abc"
    ts = 1_700_000_000
    expected = hmac.new(
        secret.encode(),
        f"{ts}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    assert sign_payload_with_timestamp(secret, body, ts) == expected


def test_timestamp_signing_differs_per_timestamp():
    """Two signatures of the same body at different timestamps must
    differ — that's the whole point of binding the timestamp."""
    secret = "x" * 64
    body = b"abc"
    a = sign_payload_with_timestamp(secret, body, 1_000)
    b = sign_payload_with_timestamp(secret, body, 1_001)
    assert a != b


# ---------- verify_with_trace ----------


def test_verify_returns_verified_true_on_match():
    """Happy path: secret + body + ts produce the expected
    signature; verify returns True with reason=None."""
    secret = "x" * 64
    body = b'{"event":"test"}'
    ts = 1_700_000_000
    sig = sign_payload_with_timestamp(secret, body, ts)
    out = verify_with_trace(secret, body, ts, sig, now=ts)
    assert out.verified is True
    assert out.reason is None
    assert out.expected_signature == sig
    assert out.provided_signature == sig
    assert out.skew_seconds == 0


def test_verify_accepts_sha256_prefix():
    """Wire format is `sha256=<hex>`. Verifier strips before compare
    so receivers passing the header verbatim work."""
    secret = "x" * 64
    body = b"abc"
    ts = 1_700_000_000
    sig = sign_payload_with_timestamp(secret, body, ts)
    wire = f"sha256={sig}"
    out = verify_with_trace(secret, body, ts, wire, now=ts)
    assert out.verified is True
    # `provided_signature` is shown stripped so partners can compare
    # digest-to-digest visually.
    assert out.provided_signature == sig


def test_verify_returns_skew_exceeded_for_stale_timestamp():
    """Skew > max → reason='timestamp_skew_exceeded'. Pin the
    closed-vocab reason code so the playground UI's diagnostic
    copy stays aligned."""
    secret = "x" * 64
    body = b"abc"
    ts = 1_000_000
    sig = sign_payload_with_timestamp(secret, body, ts)

    out = verify_with_trace(secret, body, ts, sig, now=ts + 600)
    assert out.verified is False
    assert out.reason == "timestamp_skew_exceeded"
    # Positive skew = now ahead of ts.
    assert out.skew_seconds == 600
    # We STILL compute the expected sig so partners can eyeball
    # both clock + sig issues together.
    assert out.expected_signature == sig


def test_verify_skew_check_is_symmetric():
    """A future-dated timestamp (year 9999 attack) must reject the
    same way a stale one does. Pin so a one-sided check (`now > ts +
    skew`) doesn't slip through."""
    secret = "x" * 64
    body = b"abc"
    ts = 1_700_000_000
    sig = sign_payload_with_timestamp(secret, body, ts)

    # Receiver clock is BEHIND the timestamp by 600s.
    out = verify_with_trace(secret, body, ts, sig, now=ts - 600)
    assert out.verified is False
    assert out.reason == "timestamp_skew_exceeded"
    # Negative skew = receiver behind sender.
    assert out.skew_seconds == -600


def test_verify_within_skew_window_passes():
    """Skew within the 300s window → still verifies. Pin the
    boundary."""
    secret = "x" * 64
    body = b"abc"
    ts = 1_700_000_000
    sig = sign_payload_with_timestamp(secret, body, ts)

    out = verify_with_trace(secret, body, ts, sig, now=ts + 100)
    assert out.verified is True
    assert out.skew_seconds == 100


def test_verify_returns_signature_mismatch_on_wrong_secret():
    """Wrong secret produces a different expected sig; provided
    no longer matches → reason='signature_mismatch'."""
    secret = "x" * 64
    wrong_secret = "y" * 64
    body = b"abc"
    ts = 1_700_000_000
    sig_wrong = sign_payload_with_timestamp(wrong_secret, body, ts)

    out = verify_with_trace(secret, body, ts, sig_wrong, now=ts)
    assert out.verified is False
    assert out.reason == "signature_mismatch"
    # Both signatures surface so the partner can compare hex-by-hex.
    assert out.expected_signature != sig_wrong
    assert out.provided_signature == sig_wrong


def test_verify_custom_max_skew_kwarg_threads_through():
    """Partners diagnose "would this verify if we accepted up to N
    seconds skew?" without changing production policy. Pin the
    kwarg actually changes the threshold."""
    secret = "x" * 64
    body = b"abc"
    ts = 1_700_000_000
    sig = sign_payload_with_timestamp(secret, body, ts)

    # 600s skew, default 300s window → fail.
    out_default = verify_with_trace(secret, body, ts, sig, now=ts + 600)
    assert out_default.verified is False
    # Same skew, bumped 3600s window → pass.
    out_relaxed = verify_with_trace(
        secret,
        body,
        ts,
        sig,
        now=ts + 600,
        max_skew_seconds=3600,
    )
    assert out_relaxed.verified is True


def test_verify_handles_malformed_signature_gracefully():
    """A non-hex / wrong-length signature shouldn't 500 the
    endpoint. Caught and surfaced as the closed-vocab reason
    code."""
    secret = "x" * 64
    body = b"abc"
    ts = 1_700_000_000
    # `compare_digest` requires same-length inputs of compatible
    # types. A wildly-wrong signature returns False rather than
    # raising under most Python versions, but we pin the trace
    # shape regardless.
    out = verify_with_trace(
        secret,
        body,
        ts,
        "not-hex-not-the-right-length",
        now=ts,
    )
    assert out.verified is False
    # Either signature_mismatch (the digest comparison correctly
    # said "no") or invalid_signature_format (compare_digest
    # raised) is acceptable — both outcomes are partner-actionable.
    assert out.reason in {"signature_mismatch", "invalid_signature_format"}


# ---------- Constants + types ----------


def test_default_max_skew_pinned_to_300():
    """5-minute window matches the dispatcher's default; pin so a
    refactor that bumps to 1h doesn't silently widen the replay
    window across receivers."""
    assert DEFAULT_MAX_SKEW_SECONDS == 300


def test_reason_codes_vocabulary_pinned():
    """The frontend playground UI keys off these exact strings.
    Adding / renaming a code would break the per-reason copy
    branches in the playground.

    Pin the set so a Y2-future addition (e.g. "secret_too_short")
    is a deliberate cross-cutting touch, not a silent schema
    change."""
    assert REASON_CODES == frozenset(
        {
            "timestamp_skew_exceeded",
            "signature_mismatch",
            "invalid_signature_format",
        }
    )


def test_verify_trace_is_frozen():
    """Frozen dataclass → callers can't mutate the result by
    accident. Pin so a refactor that drops `frozen=True` surfaces."""
    out = verify_with_trace(
        "x" * 64,
        b"abc",
        1_700_000_000,
        sign_payload_with_timestamp("x" * 64, b"abc", 1_700_000_000),
        now=1_700_000_000,
    )
    assert isinstance(out, VerifyTrace)
    import dataclasses

    assert dataclasses.is_dataclass(out)
    # Frozen dataclasses raise on attribute assignment.
    import pytest as _pytest

    with _pytest.raises(dataclasses.FrozenInstanceError):
        out.reason = "tampered"  # type: ignore[misc]
