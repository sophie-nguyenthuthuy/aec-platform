"""Webhook signature verification primitives (cycle Y2).

Standalone module — no dependency on `services.webhooks` (the
700-line dispatcher). The Q2 partner-facing playground at
`/api/v1/webhooks/verify-signature` should depend on a stable,
well-tested helper, not the sprawling parent.

Three layers:

  * `sign_payload(secret, body)` — bare HMAC-SHA256 hex digest.
    Used internally by the timestamp-aware variant; kept public
    for legacy receivers that verify against the body alone.

  * `sign_payload_with_timestamp(secret, body, ts)` — replay-
    resistant variant. Signs `f"{ts}.".encode() + body` so a
    receiver who only got the body without the timestamp can't
    forge a valid signature.

  * `verify_with_trace(secret, body, ts, signature, *, now,
    max_skew_seconds=300)` — structured-diagnosis verifier. Returns
    a `VerifyTrace` with `verified`, `expected_signature`,
    `provided_signature`, `skew_seconds`, and a closed-vocabulary
    `reason` (`timestamp_skew_exceeded`, `signature_mismatch`,
    `invalid_signature_format`, or None on success).

The trace shape powers the partner-facing playground UI — partners
paste their (secret, body, ts, signature) and see WHY their
receiver rejected the message instead of just "didn't match."

The dispatcher's signing path (in `services.webhooks._deliver_one`)
is expected to delegate here in a follow-up; this cycle ships the
standalone helper so the partner-facing primitive is durable
even when the larger dispatcher module churns.

Pure Python — no DB, no httpx, no Slack SDK. Side-effect free.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

# Default skew window for `verify_with_trace`. 300s matches the
# dispatcher's default — receivers running a stricter / looser
# window pass it as the kwarg.
DEFAULT_MAX_SKEW_SECONDS = 300


# Closed reason vocabulary for `VerifyTrace.reason`. The frontend
# playground UI keys off these exact strings to render focused
# diagnostic copy ("clock skew 720s — re-sync NTP" vs "signature
# mismatch — check secret"). Adding a new reason = update the UI
# and this constant in lockstep.
REASON_CODES: frozenset[str] = frozenset(
    {
        "timestamp_skew_exceeded",
        "signature_mismatch",
        "invalid_signature_format",
    }
)


@dataclass(frozen=True)
class VerifyTrace:
    """Structured-diagnosis result for the playground.

    `verified`: did the receiver's signature match? Boolean.
    `expected_signature`: the hex digest the receiver SHOULD have
        computed under the supplied (secret, body, ts).
    `provided_signature`: the supplied signature with any
        `sha256=` prefix stripped.
    `skew_seconds`: signed `now - ts` — positive means now ahead
        of timestamp ("clock is ahead by Xs"), negative means
        receiver behind sender.
    `reason`: None on success; one of `REASON_CODES` on failure.
    """

    verified: bool
    expected_signature: str
    provided_signature: str
    skew_seconds: int
    reason: str | None


# ---------- Bare signing ----------


def sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 of the body, hex-encoded.

    Used by legacy receivers that only check `hmac(body)` — kept
    for back-compat. New integrations should verify the timestamp-
    aware variant via `sign_payload_with_timestamp`.
    """
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def sign_payload_with_timestamp(secret: str, body: bytes, ts: int) -> str:
    """Replay-resistant variant. Signs `f"{ts}.".encode() + body`.

    Why the `.` separator: without it, an attacker controlling
    either the timestamp or the body could shift the boundary
    between them (length-extension shape). The `.` is not in the
    digit alphabet, so no body byte can swallow it and pretend to
    be part of the timestamp.

    Sender layout (header on the wire):
        X-AEC-Timestamp: <ts>
        X-AEC-Signature: sha256=<sign_payload_with_timestamp(...)>
    """
    msg = f"{ts}.".encode() + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


# ---------- Verification with structured diagnosis ----------


def verify_with_trace(
    secret: str,
    body: bytes,
    ts: int,
    signature: str,
    *,
    now: int,
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
) -> VerifyTrace:
    """Verify a signature with structured failure reasoning.

    Returns a `VerifyTrace` regardless of outcome. The frontend
    playground reads this to render focused diagnostic copy.

    Order of checks (mirror what the production dispatcher would
    do at receive-side):
      1. Freshness — `abs(now - ts) <= max_skew_seconds`. Symmetric
         on purpose: a year-9999 timestamp from an attacker rejects
         just like a year-1970 stale one. We STILL compute the
         expected signature so the trace shows both clock + sig
         info simultaneously (a partner with TWO bugs sees both).
      2. Signature equality — `hmac.compare_digest`. Constant-time
         to avoid leaking signature bytes through timing.

    Robust against malformed signature inputs: non-hex chars,
    wrong-length digests, empty strings all surface as
    `invalid_signature_format` rather than an exception trace.
    Receivers pass header values verbatim; an exception at this
    boundary would be a DoS vector.
    """
    skew = now - ts

    # Step 1: freshness. We still compute the expected sig + return
    # it so the playground can show both pieces of info at once.
    if abs(skew) > max_skew_seconds:
        expected = sign_payload_with_timestamp(secret, body, ts)
        return VerifyTrace(
            verified=False,
            expected_signature=expected,
            provided_signature=_strip_prefix(signature),
            skew_seconds=skew,
            reason="timestamp_skew_exceeded",
        )

    # Step 2: signature compare. Strip the `sha256=` prefix if
    # present (receiver may pass header verbatim or pre-stripped).
    expected = sign_payload_with_timestamp(secret, body, ts)
    provided = _strip_prefix(signature)

    try:
        match = hmac.compare_digest(expected, provided)
    except (TypeError, ValueError):
        # `compare_digest` raises on incompatible types; we treat
        # that as a malformed-signature failure rather than letting
        # the exception propagate.
        return VerifyTrace(
            verified=False,
            expected_signature=expected,
            provided_signature=provided,
            skew_seconds=skew,
            reason="invalid_signature_format",
        )

    return VerifyTrace(
        verified=match,
        expected_signature=expected,
        provided_signature=provided,
        skew_seconds=skew,
        reason=None if match else "signature_mismatch",
    )


def _strip_prefix(signature: str) -> str:
    """Drop the `sha256=` prefix the wire format includes.

    The wire form is `sha256=<hex>`; receivers may pass the header
    verbatim (with prefix) OR pre-strip. Both should verify.
    """
    if signature.startswith("sha256="):
        return signature[len("sha256=") :]
    return signature
