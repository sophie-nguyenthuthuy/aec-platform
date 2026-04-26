"""Unit tests for `services.rate_limit`.

Covers the token-bucket primitives. Endpoint-level integration with the
public RFQ router (asserting that a flood of requests is rejected with
HTTP 429) is in `test_public_rfq_router.py`.
"""

from __future__ import annotations

import pytest

from services import rate_limit


@pytest.fixture(autouse=True)
def _reset_buckets():
    """Each test starts with a clean bucket map."""
    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


def test_first_call_is_allowed():
    assert rate_limit.check_and_consume("k1", capacity=3, per_seconds=60) is True


def test_burst_up_to_capacity_then_blocked():
    """Capacity controls the burst size; the (capacity + 1)th must 429."""
    for _ in range(3):
        assert rate_limit.check_and_consume("k1", capacity=3, per_seconds=60) is True
    # Bucket empty — next call is denied.
    assert rate_limit.check_and_consume("k1", capacity=3, per_seconds=60) is False


def test_separate_keys_have_separate_buckets():
    # Drain one key.
    for _ in range(3):
        rate_limit.check_and_consume("alice", capacity=3, per_seconds=60)
    # A different key still has a fresh bucket.
    assert rate_limit.check_and_consume("bob", capacity=3, per_seconds=60) is True


def test_refill_releases_blocked_calls(monkeypatch):
    """Advancing the monotonic clock must let denied calls succeed again."""
    fake_now = [1000.0]

    def _now() -> float:
        return fake_now[0]

    monkeypatch.setattr(rate_limit.time, "monotonic", _now)

    # capacity=2, per_seconds=2 → rate=1 token/sec.
    assert rate_limit.check_and_consume("k", capacity=2, per_seconds=2) is True
    assert rate_limit.check_and_consume("k", capacity=2, per_seconds=2) is True
    assert rate_limit.check_and_consume("k", capacity=2, per_seconds=2) is False  # drained

    # Advance by 1.5 sec — at 1 token/sec, that's 1.5 tokens refilled.
    fake_now[0] += 1.5
    assert rate_limit.check_and_consume("k", capacity=2, per_seconds=2) is True
    # Only 0.5 tokens left — next call should be denied.
    assert rate_limit.check_and_consume("k", capacity=2, per_seconds=2) is False


def test_idle_bucket_does_not_overflow_capacity(monkeypatch):
    """A long-idle key shouldn't accumulate unbounded bursts on next use."""
    fake_now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: fake_now[0])

    rate_limit.check_and_consume("k", capacity=3, per_seconds=3)  # spend 1
    # Sleep for 10 minutes — way more than the refill window.
    fake_now[0] += 600

    # Only `capacity` tokens are available — bucket is clamped.
    for _ in range(3):
        assert rate_limit.check_and_consume("k", capacity=3, per_seconds=3) is True
    assert rate_limit.check_and_consume("k", capacity=3, per_seconds=3) is False


def test_changing_capacity_resets_bucket():
    """A deploy that tightens the cap must take effect without a restart."""
    for _ in range(5):
        rate_limit.check_and_consume("k", capacity=5, per_seconds=60)
    # Same key, but tighter cap — bucket is rebuilt; first call refilled.
    assert rate_limit.check_and_consume("k", capacity=2, per_seconds=60) is True
    assert rate_limit.check_and_consume("k", capacity=2, per_seconds=60) is True
    assert rate_limit.check_and_consume("k", capacity=2, per_seconds=60) is False


def test_raw_key_is_hashed_not_stored():
    """The bucket dict must not contain the original key — defence in depth."""
    rate_limit.check_and_consume("super-secret-token", capacity=3, per_seconds=60)
    assert "super-secret-token" not in rate_limit._BUCKETS
    # The actual key in the dict is the 16-char SHA prefix.
    assert all(len(k) == 16 for k in rate_limit._BUCKETS)
