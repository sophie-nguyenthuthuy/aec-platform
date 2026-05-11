"""Backoff jitter helper (cycle OO3).

Apply deterministic ±jitter to backoff delays to avoid
thundering-herd retry waves across multi-tenant subscriptions.

  apply_jitter(base, attempt, seed, jitter_pct)  — jittered delay
  DEFAULT_JITTER_PCT                              — 0.2 (±20%)
  MIN_DELAY_SECONDS                               — 1.0

Composes with Z1 (`webhook_backoff`): the worker computes Z1's
backoff schedule (`BACKOFF_MINUTES[attempt] * 60` seconds) and
layers jitter via this helper before sleeping.

Deterministic: same `(seed, attempt_count)` always yields the
same jittered delay. Uses SHA-256 hash of `{seed}:{attempt}` to
derive the jitter factor — testable without RNG state, and
predictable across worker restarts (a retry that's been
scheduled stays scheduled at the same offset).

Pinned invariants:
  * Determinism — pure function of (base, attempt, seed, pct).
  * Jitter band: [base * (1 - pct), base * (1 + pct)].
  * MIN_DELAY_SECONDS floor — never sleep less than 1 second
    even after negative jitter.
  * jitter_pct = 0 → returns base (no-op idiom).
  * jitter_pct out of [0, 1] raises ValueError.
  * Different attempts → different jitter (so retries spread
    across the band rather than landing on the same offset).
  * Different seeds → different jitter (per-subscription
    spread, defends against multi-tenant herd).

Pure stdlib.
"""

from __future__ import annotations

import hashlib

# ±20% jitter — industry-standard band size for retry-storm
# avoidance. Small enough that the retry stays in the same
# operational time-bucket; large enough that 1000 subscriptions
# spread across a meaningful window.
DEFAULT_JITTER_PCT = 0.2


# Floor on the jittered delay. Even after negative jitter and
# tiny base delays, never sleep less than 1 second (defends
# against tight loops if a refactor makes base_delay accidentally
# tiny).
MIN_DELAY_SECONDS = 1.0


def _hash_to_factor(seed: str, attempt_count: int) -> float:
    """Map (seed, attempt) → deterministic float in [0.0, 1.0).

    SHA-256 hash, take first 8 bytes as uint64, divide by 2^64.
    Determinism ensures the same retry stays scheduled at the
    same offset across worker restarts.
    """
    digest = hashlib.sha256(
        f"{seed}:{attempt_count}".encode(),
    ).digest()
    n = int.from_bytes(digest[:8], "big")
    return n / (2**64)


def apply_jitter(
    base_delay_seconds: float,
    attempt_count: int,
    seed: str,
    jitter_pct: float = DEFAULT_JITTER_PCT,
) -> float:
    """Apply deterministic ±jitter_pct to a backoff delay.

    Returns a jittered delay in seconds, clamped to a minimum
    of `MIN_DELAY_SECONDS`.

    `jitter_pct = 0` returns the base delay unchanged (still
    floor-clamped to MIN_DELAY_SECONDS).
    """
    if not (0 <= jitter_pct <= 1):
        raise ValueError(f"jitter_pct must be in [0, 1], got {jitter_pct!r}")
    if jitter_pct == 0:
        return max(MIN_DELAY_SECONDS, float(base_delay_seconds))

    factor = _hash_to_factor(seed, attempt_count)
    # Map [0, 1) to [-jitter_pct, +jitter_pct].
    offset = factor * 2 * jitter_pct - jitter_pct
    delay = base_delay_seconds * (1 + offset)
    return max(MIN_DELAY_SECONDS, delay)
