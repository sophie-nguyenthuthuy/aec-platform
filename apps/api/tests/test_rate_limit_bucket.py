"""API rate limit token bucket (cycle KK1).

Pinned seams:
  1. Atomic consume — no partial.
  2. Refill clamps at capacity (overflow ignored).
  3. Clock skew (now < last_updated) treats elapsed as 0.
  4. Negative n rejected with no state change.
  5. n=0 always succeeds (refresh idiom).
  6. Immutable update — input bucket unchanged.
  7. Failed attempt still advances last_updated (refill recorded).
"""

from __future__ import annotations

from services.rate_limit_bucket import TokenBucket, try_consume


def _full_bucket(capacity: float = 10, refill: float = 1.0) -> TokenBucket:
    return TokenBucket(
        capacity=capacity,
        refill_per_second=refill,
        tokens=capacity,
        last_updated=0.0,
    )


# ---------- Basic consume ----------


def test_consume_one_from_full_bucket():
    bucket = _full_bucket()
    allowed, new_bucket = try_consume(bucket, now=0.0, n=1.0)
    assert allowed is True
    assert new_bucket.tokens == 9.0
    assert new_bucket.last_updated == 0.0


def test_consume_all_tokens_at_once():
    bucket = _full_bucket(capacity=10)
    allowed, new_bucket = try_consume(bucket, now=0.0, n=10.0)
    assert allowed is True
    assert new_bucket.tokens == 0.0


def test_consume_more_than_available_rejected():
    """Cardinal pin: atomic consume. Asking for 11 from a
    10-cap bucket fails ENTIRELY — not a partial 10 + reject 1."""
    bucket = _full_bucket(capacity=10)
    allowed, new_bucket = try_consume(bucket, now=0.0, n=11.0)
    assert allowed is False
    # Tokens unchanged (no partial consume).
    assert new_bucket.tokens == 10.0


def test_consume_zero_always_succeeds():
    """n=0 is the "refresh" idiom — pin so a refactor that adds
    a `> 0` guard surfaces here."""
    bucket = _full_bucket()
    allowed, new_bucket = try_consume(bucket, now=0.0, n=0.0)
    assert allowed is True
    assert new_bucket.tokens == bucket.tokens


# ---------- Refill ----------


def test_refill_increases_tokens_over_time():
    """5s elapsed at 1 token/s on an empty bucket → 5 tokens."""
    bucket = TokenBucket(
        capacity=10,
        refill_per_second=1.0,
        tokens=0.0,
        last_updated=0.0,
    )
    allowed, new_bucket = try_consume(bucket, now=5.0, n=3.0)
    assert allowed is True
    # Refilled to 5, consumed 3 → 2 remaining.
    assert new_bucket.tokens == 2.0
    assert new_bucket.last_updated == 5.0


def test_refill_clamps_at_capacity():
    """Cardinal pin: tokens never exceed capacity. A 10-cap
    bucket idle for 100s at 1/s does NOT have 100 tokens — caps
    at 10."""
    bucket = _full_bucket(capacity=10)
    allowed, new_bucket = try_consume(bucket, now=100.0, n=1.0)
    assert allowed is True
    # Refilled to 10 (cap), consumed 1 → 9.
    assert new_bucket.tokens == 9.0


def test_refill_at_partial_token_rates():
    """Refill rate of 0.5/s for 4s = 2 tokens added."""
    bucket = TokenBucket(
        capacity=10,
        refill_per_second=0.5,
        tokens=0.0,
        last_updated=0.0,
    )
    allowed, new_bucket = try_consume(bucket, now=4.0, n=2.0)
    assert allowed is True
    assert new_bucket.tokens == 0.0


# ---------- Clock skew defense ----------


def test_clock_skew_no_time_travel():
    """Cardinal pin: `now < last_updated` treats elapsed as 0.
    Defends against a buggy NTP causing clock backflow → no
    accidental burst from negative-elapsed refill."""
    bucket = TokenBucket(
        capacity=10,
        refill_per_second=1.0,
        tokens=5.0,
        last_updated=10.0,
    )
    # `now=5` is BEFORE last_updated=10. Refill clamps to 0 elapsed.
    allowed, new_bucket = try_consume(bucket, now=5.0, n=3.0)
    assert allowed is True
    # Tokens unchanged by refill (was 5, consumed 3 → 2).
    assert new_bucket.tokens == 2.0


# ---------- Negative n ----------


def test_negative_n_rejected_no_state_change():
    """Cardinal pin: invalid `n < 0` returns (False, bucket)
    with NO state change. A caller-side bug surfaces as a hard
    reject, not a silent corruption of the bucket."""
    bucket = _full_bucket()
    allowed, new_bucket = try_consume(bucket, now=5.0, n=-1.0)
    assert allowed is False
    # last_updated NOT advanced — full no-op.
    assert new_bucket == bucket


# ---------- Failed attempt advances time ----------


def test_failed_attempt_still_advances_last_updated():
    """Even when consume fails, the refill component is still
    applied so the next attempt sees fresh accumulation. Pin so
    a refactor that returns the original bucket on failure
    breaks here."""
    bucket = TokenBucket(
        capacity=10,
        refill_per_second=1.0,
        tokens=2.0,
        last_updated=0.0,
    )
    # Try consume 5 at t=2 — refill would bring to 4, still < 5.
    allowed, new_bucket = try_consume(bucket, now=2.0, n=5.0)
    assert allowed is False
    # last_updated MUST advance to 2.
    assert new_bucket.last_updated == 2.0
    # tokens reflect refill: 2 + 2 = 4.
    assert new_bucket.tokens == 4.0


# ---------- Immutability ----------


def test_input_bucket_unchanged_on_success():
    bucket = _full_bucket()
    original = TokenBucket(
        capacity=bucket.capacity,
        refill_per_second=bucket.refill_per_second,
        tokens=bucket.tokens,
        last_updated=bucket.last_updated,
    )
    try_consume(bucket, now=5.0, n=1.0)
    assert bucket == original


def test_input_bucket_unchanged_on_failure():
    bucket = _full_bucket(capacity=5)
    original_tokens = bucket.tokens
    try_consume(bucket, now=0.0, n=10.0)
    assert bucket.tokens == original_tokens


def test_token_bucket_is_frozen():
    bucket = _full_bucket()
    try:
        bucket.tokens = 0  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("TokenBucket should be frozen")


# ---------- Sequential consume realism ----------


def test_steady_state_one_per_second():
    """Realistic scenario: 1 token/s refill, consume 1 per
    second indefinitely → all succeed."""
    bucket = _full_bucket(capacity=10, refill=1.0)
    for t in range(100):
        allowed, bucket = try_consume(bucket, now=float(t), n=1.0)
        assert allowed is True, f"step {t} should succeed"


def test_burst_then_throttle():
    """Burst of 10 succeeds; 11th immediately fails; 1s later
    one token has refilled → succeeds again."""
    bucket = _full_bucket(capacity=10, refill=1.0)
    # Drain burst at t=0.
    for _ in range(10):
        allowed, bucket = try_consume(bucket, now=0.0, n=1.0)
        assert allowed is True
    # 11th immediately → fail.
    allowed, bucket = try_consume(bucket, now=0.0, n=1.0)
    assert allowed is False
    # 1 second later → 1 token refilled, consume succeeds.
    allowed, bucket = try_consume(bucket, now=1.0, n=1.0)
    assert allowed is True
    assert bucket.tokens == 0.0
