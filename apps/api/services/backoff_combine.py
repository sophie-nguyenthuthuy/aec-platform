"""Backoff jitter combiner (cycle VV1).

Compose Z1's `webhook_backoff` schedule + OO3's `backoff_jitter`
into the canonical worker pattern. Today the webhook delivery
worker manually composes Z1's BACKOFF_MINUTES with OO3's
apply_jitter — the two-step pattern is duplicated in the audit
retry handler and the email digest scheduler. This module is
the single source of truth.

  compute_jittered_delay(attempt, seed, jitter_pct)  — float seconds

Composes:
  * Z1 (`webhook_backoff.BACKOFF_MINUTES`) — base schedule.
  * OO3 (`backoff_jitter.apply_jitter`) — deterministic jitter.

Pinned invariants:
  * `attempt_count` < 0 raises ValueError.
  * `attempt_count` >= Z1's MAX_ATTEMPTS raises ValueError
    (terminal — caller should hard-fail, not schedule further
    retries).
  * Returns float seconds with OO3's MIN_DELAY_SECONDS floor.
  * Attempt 0 (Z1's `BACKOFF_MINUTES[0]` = 0) floors to
    OO3's MIN_DELAY_SECONDS.
  * Deterministic given (attempt, seed, jitter_pct).

Pure stdlib + Z1 + OO3.
"""

from __future__ import annotations

from services.backoff_jitter import DEFAULT_JITTER_PCT, apply_jitter
from services.webhook_backoff import BACKOFF_MINUTES, MAX_ATTEMPTS


def compute_jittered_delay(
    attempt_count: int,
    seed: str,
    jitter_pct: float = DEFAULT_JITTER_PCT,
) -> float:
    """Compute the jittered delay (in seconds) for a retry attempt.

    Two-step composition:
      1. base_seconds = Z1's BACKOFF_MINUTES[attempt] * 60
      2. delay = OO3's apply_jitter(base_seconds, attempt, seed)

    Raises:
      * ValueError if `attempt_count < 0`.
      * ValueError if `attempt_count >= MAX_ATTEMPTS` (terminal).
    """
    if attempt_count < 0:
        raise ValueError(f"attempt_count must be >= 0, got {attempt_count}")
    if attempt_count >= MAX_ATTEMPTS:
        raise ValueError(
            f"attempt_count {attempt_count} >= MAX_ATTEMPTS={MAX_ATTEMPTS} — caller should hard-fail rather than retry"
        )

    base_minutes = BACKOFF_MINUTES[attempt_count]
    base_seconds = float(base_minutes * 60)

    return apply_jitter(base_seconds, attempt_count, seed, jitter_pct)
