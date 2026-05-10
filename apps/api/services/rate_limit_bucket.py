"""API rate limit token bucket (cycle KK1).

Pure stateful struct for token-bucket rate limiting. Today the
webhook delivery worker's per-domain limiter, the API's per-IP
guard, and the email digest scheduler's per-org throttle each
duplicate the bucket math inline with subtly different overflow
handling. This module is the single source of truth.

  TokenBucket                      — frozen dataclass
  try_consume(bucket, now, n=1)    — (allowed, new_bucket) tuple

Composes with Z1 (`webhook_backoff`): a rate-limited domain can
trigger longer backoff via `try_consume` returning `False`.

Pinned invariants:
  * Immutable update — caller stores the returned `new_bucket`.
  * Atomic consume — either ALL `n` tokens succeed or NONE.
  * Refill clamps at `capacity` — overflow doesn't accumulate.
  * `last_updated > now` (clock skew) treats elapsed as 0
    (no time-travel refill).
  * Negative `n` rejected — returns `(False, bucket)` with NO
    state change (defensive against caller bugs).
  * Non-mutating: `bucket` argument is never modified
    (frozen dataclass + dataclasses.replace).

Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class TokenBucket:
    """A token bucket for rate limiting.

    `capacity` is the max burst (tokens never exceed this).
    `refill_per_second` is the steady-state rate.
    `tokens` is the current token count at `last_updated`.
    `last_updated` is the wall-clock seconds since epoch.

    Example: a 10-burst, 1-token-per-second bucket initialized
    full at t=0 looks like:
        TokenBucket(capacity=10, refill_per_second=1.0,
                    tokens=10.0, last_updated=0.0)
    """

    capacity: float
    refill_per_second: float
    tokens: float
    last_updated: float


def _refill(bucket: TokenBucket, now: float) -> TokenBucket:
    """Compute the refilled bucket at `now` (doesn't consume).

    Negative elapsed (clock skew where `now < last_updated`) is
    clamped to 0 — no time-travel refill.
    """
    elapsed = now - bucket.last_updated
    if elapsed < 0:
        elapsed = 0
    new_tokens = bucket.tokens + elapsed * bucket.refill_per_second
    if new_tokens > bucket.capacity:
        new_tokens = bucket.capacity
    return replace(bucket, tokens=new_tokens, last_updated=now)


def try_consume(
    bucket: TokenBucket,
    now: float,
    n: float = 1.0,
) -> tuple[bool, TokenBucket]:
    """Try to consume `n` tokens at wall-clock `now`.

    Returns `(allowed, new_bucket)`:
      * On success: `allowed=True`, new_bucket reflects refill +
        consume.
      * On failure (insufficient tokens): `allowed=False`,
        new_bucket reflects refill ONLY (the time forward is
        recorded so the next attempt sees fresh accumulation).
      * On invalid input (`n < 0`): `(False, bucket)` with NO
        state change — caller bug surfaces as a hard reject
        without time travel.

    Atomic: never partial — if `tokens < n`, NONE consumed.
    """
    if n < 0:
        return (False, bucket)
    refilled = _refill(bucket, now)
    if refilled.tokens >= n:
        return (True, replace(refilled, tokens=refilled.tokens - n))
    return (False, refilled)
