"""Lightweight per-key in-memory rate limiter.

Designed for the public RFQ supplier portal: each `?t=<token>` URL gets
its own bucket so a misconfigured supplier email client doing reload-
loops can't hammer the endpoints, and a leaked token gives a single
attacker only N requests per window before they have to wait.

We DON'T use Redis here because:
  * The public endpoints are single-replica today (one API container).
  * Tokens are unguessable — brute-force enumeration is infeasible — so
    this limiter is a politeness shim, not a security control.
  * In-memory means one less moving part for the public surface area.

If/when the API horizontally scales, swap `_BUCKETS` for a Redis-backed
implementation behind the same `check_and_consume` interface; tests
don't care which storage you use.

The limiter keys on `sha256(raw_key)[:16]` so the bucket map never
holds the original token in memory. That's defence in depth: an attack
that dumps process memory still doesn't recover any live tokens.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from threading import Lock

# Buckets are mutated from async code but hold tiny critical sections,
# so a stdlib `threading.Lock` is sufficient — no asyncio.Lock dance.
_BUCKETS_LOCK = Lock()
_BUCKETS: dict[str, _Bucket] = {}


@dataclass
class _Bucket:
    """Token bucket: `tokens` refills at `rate_per_sec` up to `capacity`."""

    capacity: float
    rate_per_sec: float
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = self.capacity
        self.last_refill = time.monotonic()

    def consume(self, cost: float = 1.0) -> bool:
        """Try to take `cost` tokens. Returns True on success, False on deny."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now
        # Refill up to capacity. `min(...)` clamps so a long-idle client
        # doesn't get an unbounded burst.
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_sec)
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


def _hash_key(raw_key: str) -> str:
    """Stable 16-hex-char digest — enough entropy that collisions are
    irrelevant within a single process lifetime, short enough that the
    bucket dict stays compact."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]


def check_and_consume(
    raw_key: str,
    *,
    capacity: int,
    per_seconds: int,
) -> bool:
    """Try to take one token from the bucket for `raw_key`.

    `capacity` is the burst size (e.g. 10 reqs); `per_seconds` is the
    refill window (e.g. 60 → 10 reqs / minute). The first call from a
    new key gets a full bucket; subsequent calls drain it and refill at
    `capacity / per_seconds` tokens per second.

    Returns True if the request is allowed, False if it should be 429'd.

    Threadsafe — but not async-safe across multiple processes. See the
    module docstring for the Redis migration path.
    """
    rate = capacity / per_seconds
    key = _hash_key(raw_key)
    with _BUCKETS_LOCK:
        bucket = _BUCKETS.get(key)
        if bucket is None or bucket.capacity != capacity or bucket.rate_per_sec != rate:
            # New key, or config changed since the last call — fresh bucket.
            # The capacity-check ensures a deploy-time tweak takes effect
            # without a restart; the bucket is cheap to recreate.
            bucket = _Bucket(capacity=capacity, rate_per_sec=rate)
            _BUCKETS[key] = bucket
        return bucket.consume()


def reset_for_tests() -> None:
    """Clear all buckets — only used by the test suite to isolate cases.

    Production code never calls this; bucket state is meant to live for
    the lifetime of the process.
    """
    with _BUCKETS_LOCK:
        _BUCKETS.clear()
