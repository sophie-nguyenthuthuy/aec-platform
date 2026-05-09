"""Pin the `services.rate_limit` token-bucket contract.

The public RFQ supplier portal exposes endpoints that take a
`?t=<token>` URL — every supplier email opens these, often with
prefetch + reload-loop bugs in cheap email clients. This module is
the politeness shim that keeps a misbehaving client (or a leaked
token in someone's password manager) from hammering the endpoints
into a denial-of-service against the legitimate supplier on the
same shard.

It's also the cheapest piece of resilience theatre we have. If it
silently breaks, every non-fatal misuse becomes a fatal misuse —
the next retry-storm from a flaky email client takes the public
RFQ surface offline for everyone, and ops only notices when the
buyer-facing dashboard shows zero RFQ replies for an hour.

Three failure modes a regression here can produce, all silent:

  * **`check_and_consume` returns True unconditionally.** Every
    request is allowed. The throttle is gone. A reload-looping
    Outlook plugin can DoS the surface with no log line saying
    "we used to throttle this."

  * **Bucket key drift (different `_hash_key` output).** Every
    request from the same token gets a fresh bucket — full
    capacity each time. Effectively no throttle, but the function
    SAYS it's enforcing one.

  * **Capacity-or-rate change without re-creating the bucket.**
    A deploy-time tweak (e.g. dropping capacity from 10 to 3)
    silently doesn't take effect for any in-flight token until
    process restart. The dashboard says "we tightened the
    throttle" while production still throttles at the old rate.

This file is read-only — imports + pure-function calls. Survives
reverts of `services/rate_limit.py` (which has been stable, but
the cost of a regression is high enough that a tripwire pays for
itself the first time it fires).

Pinned contracts:

  * `_hash_key` is sha256-hex truncated to 16 chars, deterministic.
  * `_hash_key` does NOT leak the original token in memory (its
    output bears no character relation to the input).
  * `_Bucket.consume` enforces capacity (full bucket → drains).
  * `_Bucket.consume` refills at the documented `rate_per_sec`.
  * `check_and_consume` rebuilds the bucket when capacity OR rate
    changes (deploy-time tweaks must take effect immediately).
  * `check_and_consume` keyword-only signature.
  * `reset_for_tests` exists + clears state (test-isolation contract).
"""

from __future__ import annotations

import inspect
import time

# ---------- Module presence ----------


def test_rate_limit_module_imports():
    """All public surfaces importable. A revert that deleted any of
    them surfaces as a hard ImportError on the next CI run — the
    desired signal vs silently breaking the public RFQ surface."""
    from services.rate_limit import (  # noqa: F401
        _Bucket,
        _hash_key,
        check_and_consume,
        reset_for_tests,
    )


# ---------- _hash_key ----------


def test_hash_key_is_sha256_hex_truncated():
    """16 hex chars (sha256-truncated). A drift to a longer or
    shorter prefix would make the bucket dict either bloat (full
    64-char keys) or collide more often (8-char prefix collides
    every 4 billion keys — fine in practice, but the existing
    16-char prefix gives 2^64 distinct buckets and that's what's
    been calibrated against)."""
    from services.rate_limit import _hash_key

    h = _hash_key("aec_test_token_xyz")
    assert isinstance(h, str)
    assert len(h) == 16, (
        f"_hash_key returned {len(h)} chars; want 16. A drift here "
        "changes bucket-collision math AND breaks the documented "
        "trade-off in the module docstring."
    )
    assert all(c in "0123456789abcdef" for c in h), (
        f"_hash_key produced non-hex output: {h!r}. Lowercase-hex "
        "is the expected shape; case drift wouldn't affect lookups "
        "(it's stable per-call) but would break any future log/grep."
    )


def test_hash_key_is_deterministic():
    """Same token → same hash, every call. Defensive against a
    regression that introduced randomness (salt, time-based) — would
    make every call from the same token get a fresh bucket."""
    from services.rate_limit import _hash_key

    token = "aec_test_token_xyz"
    assert _hash_key(token) == _hash_key(token) == _hash_key(token)


def test_hash_key_distinguishes_different_tokens():
    """Different tokens MUST hash differently. Otherwise the throttle
    becomes shared across unrelated suppliers — one flaky email
    client throttles every other supplier's traffic too."""
    from services.rate_limit import _hash_key

    a = _hash_key("token_a")
    b = _hash_key("token_b")
    assert a != b


def test_hash_key_does_not_leak_raw_token():
    """SECURITY pin (defence in depth, per the module docstring).
    The bucket map keys MUST NOT be the original token — a memory
    dump of the API process should not recover live RFQ tokens.

    A regression that used the raw token (e.g. via a short-circuit
    `return raw_key`) would silently leak every active token into
    the bucket-map's key set.
    """
    from services.rate_limit import _hash_key

    sensitive = "aec_supplier_token_DO_NOT_LEAK_42"
    h = _hash_key(sensitive)
    # The hash MUST NOT contain any contiguous 4+-char substring of
    # the raw token. (Choose 4 because shorter overlaps could be
    # coincidental hex bytes.)
    for i in range(len(sensitive) - 3):
        substring = sensitive[i : i + 4]
        assert substring not in h, (
            f"_hash_key output {h!r} contains substring {substring!r} "
            f"from the raw token — possible token leak in the bucket map."
        )


# ---------- _Bucket.consume ----------


def test_bucket_consume_drains_capacity():
    """Fresh bucket holds `capacity` tokens. Consuming N times
    drains them; the (N+1)th call returns False."""
    from services.rate_limit import _Bucket

    b = _Bucket(capacity=3, rate_per_sec=0.0)  # zero refill so we test pure capacity
    assert b.consume() is True
    assert b.consume() is True
    assert b.consume() is True
    assert b.consume() is False, (
        "_Bucket.consume returned True after capacity exhausted — "
        "the throttle is broken; every caller gets unlimited tokens."
    )


def test_bucket_consume_refills_at_documented_rate():
    """Bucket refills at `rate_per_sec`. After 1.0s with rate=2.0,
    a fully-drained bucket should have ~2 tokens available.

    We use small sleep windows to keep the test fast; the timing
    isn't exact (monotonic clock granularity, GC, CI noise) so we
    assert "at least one consume succeeds after the refill window"
    rather than an exact token count.
    """
    from services.rate_limit import _Bucket

    b = _Bucket(capacity=2, rate_per_sec=10.0)  # 10 tokens/sec → 0.1s per token
    # Drain.
    b.consume()
    b.consume()
    assert b.consume() is False  # empty

    # Wait long enough for at least one refill tick.
    time.sleep(0.2)
    assert b.consume() is True, (
        "_Bucket.consume did not refill after the documented window. "
        "Rate-limited callers would stay locked out forever."
    )


def test_bucket_consume_clamps_at_capacity():
    """A long-idle bucket MUST NOT accumulate above `capacity`. The
    `min(capacity, ...)` clamp in `consume` guards against an
    unbounded burst from an idle client (which would defeat the
    burst-limiting purpose of the bucket)."""
    from services.rate_limit import _Bucket

    b = _Bucket(capacity=2, rate_per_sec=100.0)  # high refill
    # Simulate a long idle gap by faking the last_refill timestamp.
    b.last_refill = time.monotonic() - 60.0  # 60s of "idle" → would refill 6000 tokens
    # Trigger a refill via a consume call.
    b.consume()
    # After consume, tokens must be <= capacity (1 left, NOT 5999).
    assert b.tokens <= b.capacity, (
        f"_Bucket.tokens drifted to {b.tokens} after a long idle period; "
        f"capacity is {b.capacity}. The clamp is broken — an idle "
        "client gets an unbounded burst, defeating the throttle."
    )


# ---------- check_and_consume ----------


def test_check_and_consume_signature_pinned():
    """`check_and_consume(raw_key, *, capacity, per_seconds)`.

    Callers pass `capacity=` and `per_seconds=` by name. A
    positional-or-rename regression would TypeError at runtime in
    every caller (the fail-loud path) BUT a signature change to
    `(*, raw_key, capacity, per_seconds)` would TypeError every
    existing positional call site. Pin the exact shape.
    """
    from services.rate_limit import check_and_consume

    sig = inspect.signature(check_and_consume)
    params = list(sig.parameters.values())

    # First param is positional (the raw_key).
    assert params[0].name == "raw_key"
    assert params[0].kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.POSITIONAL_ONLY,
    ), f"check_and_consume's first param `raw_key` is {params[0].kind.name}; want POSITIONAL_OR_KEYWORD."

    # Then capacity + per_seconds, both keyword-only.
    kw_names = [p.name for p in params[1:]]
    assert kw_names == ["capacity", "per_seconds"], f"check_and_consume kw block drifted: {kw_names}"
    for p in params[1:]:
        assert p.kind is inspect.Parameter.KEYWORD_ONLY


def test_check_and_consume_allows_first_call():
    """A fresh key MUST get a full bucket → first call returns True.
    A regression that started buckets at zero would silently 429
    every legitimate first-time supplier link."""
    from services.rate_limit import check_and_consume, reset_for_tests

    reset_for_tests()
    assert check_and_consume("fresh-token", capacity=5, per_seconds=60) is True


def test_check_and_consume_drains_after_capacity_exhausted():
    """After `capacity` consecutive calls, the next one returns False.
    `per_seconds=10000` makes the refill effectively zero within
    test timing."""
    from services.rate_limit import check_and_consume, reset_for_tests

    reset_for_tests()
    for _ in range(3):
        assert check_and_consume("drain-token", capacity=3, per_seconds=10000) is True
    # 4th call: refill is ~0.0003 tokens/sec, so still empty.
    assert check_and_consume("drain-token", capacity=3, per_seconds=10000) is False


def test_check_and_consume_rebuilds_bucket_when_capacity_changes():
    """SECURITY-RELEVANT pin. The module docstring promises
    deploy-time tweaks take effect without a restart. A regression
    that kept the old bucket on capacity change would let a still-
    in-flight token continue to drain the old (looser) throttle
    while ops thinks they tightened it.
    """
    from services.rate_limit import check_and_consume, reset_for_tests

    reset_for_tests()
    # Drain the bucket at capacity=2.
    assert check_and_consume("rebuild-token", capacity=2, per_seconds=10000) is True
    assert check_and_consume("rebuild-token", capacity=2, per_seconds=10000) is True
    assert check_and_consume("rebuild-token", capacity=2, per_seconds=10000) is False

    # Same key, larger capacity. The implementation MUST rebuild
    # the bucket — the next call should succeed against the fresh
    # capacity.
    assert check_and_consume("rebuild-token", capacity=10, per_seconds=10000) is True, (
        "check_and_consume did not rebuild the bucket when capacity "
        "changed — deploy-time throttle tweaks silently don't take "
        "effect for any token still in the bucket map until restart."
    )


def test_check_and_consume_rebuilds_bucket_when_rate_changes():
    """Same pin as above but for the `per_seconds` knob. Together,
    capacity-or-rate change must trigger a fresh bucket."""
    from services.rate_limit import check_and_consume, reset_for_tests

    reset_for_tests()
    # capacity=2, per_seconds=60 → rate ~0.033/sec.
    check_and_consume("rate-token", capacity=2, per_seconds=60)
    check_and_consume("rate-token", capacity=2, per_seconds=60)
    # Drained (or near-drained). Now change rate.
    # capacity=2 same, per_seconds=1 → rate 2.0/sec, very different.
    # Rebuild → fresh full bucket → True.
    assert check_and_consume("rate-token", capacity=2, per_seconds=1) is True, (
        "check_and_consume did not rebuild bucket when per_seconds (and thus rate) changed."
    )


# ---------- reset_for_tests ----------


def test_reset_for_tests_clears_state():
    """The test-isolation contract. Without it, test order matters
    and a draining test in one module poisons the next module's
    fresh-bucket assumptions."""
    from services.rate_limit import _BUCKETS, check_and_consume, reset_for_tests

    check_and_consume("isolation-token", capacity=1, per_seconds=10000)
    # Bucket should now exist.
    assert len(_BUCKETS) > 0

    reset_for_tests()
    assert len(_BUCKETS) == 0, "reset_for_tests did not clear _BUCKETS; test isolation broken."
