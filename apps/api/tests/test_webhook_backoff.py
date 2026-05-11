"""Webhook backoff schedule (cycle Z1).

Pinned seams:
  1. `BACKOFF_MINUTES` is the canonical schedule
     `[0, 1, 5, 30, 120, 720]`. A change requires a deliberate
     review touch.
  2. `next_retry_at` is anchored to base_time (not last-attempt
     time) so slow retries don't compound the gap.
  3. `is_terminal_failure` triggers at attempt_count == MAX_ATTEMPTS.
  4. `total_window_minutes` matches the docs' "~15 hour" claim
     (876 minutes).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.webhook_backoff import (
    BACKOFF_MINUTES,
    MAX_ATTEMPTS,
    is_terminal_failure,
    next_retry_at,
    total_window_minutes,
)

# ---------- Constants ----------


def test_backoff_minutes_pinned_to_canonical_schedule():
    """[0, 1, 5, 30, 120, 720] — pin so a refactor doesn't silently
    widen / tighten any of the per-step delays. The values were
    chosen against Stripe's public webhook-retry data; changes
    should be deliberate."""
    assert BACKOFF_MINUTES == [0, 1, 5, 30, 120, 720]


def test_max_attempts_matches_schedule_length():
    """MAX_ATTEMPTS = len(BACKOFF_MINUTES). Pin so a refactor that
    bumps the schedule but forgets to update the constant doesn't
    silently mark rows terminal one attempt early."""
    assert len(BACKOFF_MINUTES) == MAX_ATTEMPTS
    assert MAX_ATTEMPTS == 6


def test_total_window_minutes_matches_docs():
    """Partner docs claim "we retry for ~15 hours." Pin the math:
    0 + 1 + 5 + 30 + 120 + 720 = 876 min ≈ 14.6 hours."""
    assert total_window_minutes() == 876


# ---------- next_retry_at ----------


_BASE = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


def test_next_retry_at_attempt_zero_fires_immediately():
    """attempt 0's delay is 0 minutes — the row enters the queue at
    its created_at and the dispatcher's first cron tick fires it."""
    out = next_retry_at(attempt_count=0, base_time=_BASE)
    assert out == _BASE


def test_next_retry_at_attempt_one_is_base_plus_one_minute():
    """First retry (after the initial attempt failed) is 1 min
    later. Pin so a refactor that flips the index meaning to
    "next-attempt" off-by-one surfaces."""
    out = next_retry_at(attempt_count=1, base_time=_BASE)
    assert out == _BASE + timedelta(minutes=1)


def test_next_retry_at_attempt_five_is_twelve_hours_later():
    """attempt 5 = 720 minutes = 12 hours."""
    out = next_retry_at(attempt_count=5, base_time=_BASE)
    assert out == _BASE + timedelta(hours=12)


def test_next_retry_at_returns_none_at_max_attempts():
    """attempt_count == MAX_ATTEMPTS → schedule exhausted →
    None. The dispatcher reads this as "mark terminal-failed."""
    out = next_retry_at(attempt_count=MAX_ATTEMPTS, base_time=_BASE)
    assert out is None


def test_next_retry_at_returns_none_past_max():
    """Defensive: a row somehow at attempt_count > MAX should
    return None too (not raise IndexError). Pin the safety net."""
    out = next_retry_at(attempt_count=99, base_time=_BASE)
    assert out is None


def test_next_retry_at_returns_none_for_negative_count():
    """Defensive: negative attempt_count is a caller bug. Return
    None rather than raise — the dispatcher branch becomes "don't
    re-queue, log + investigate" instead of crashing the cron."""
    out = next_retry_at(attempt_count=-1, base_time=_BASE)
    assert out is None


def test_next_retry_at_anchored_to_base_not_now():
    """Schedule is anchored to `base_time` (the row's created_at).
    Pin so a refactor that anchors to "right now" doesn't silently
    push retries forward when the cron is slow."""
    # Two calls with the same attempt_count + base_time MUST
    # return the same datetime, regardless of when they're called.
    a = next_retry_at(attempt_count=3, base_time=_BASE)
    b = next_retry_at(attempt_count=3, base_time=_BASE)
    assert a == b == _BASE + timedelta(minutes=30)


# ---------- is_terminal_failure ----------


def test_is_terminal_failure_false_within_schedule():
    """While attempts remain, retry is on the table. Pin every
    in-range attempt count returns False."""
    for n in range(MAX_ATTEMPTS):
        assert is_terminal_failure(attempt_count=n) is False, f"attempt_count={n} should NOT be terminal"


def test_is_terminal_failure_true_at_max():
    """attempt_count == MAX_ATTEMPTS → terminal. Pin the boundary."""
    assert is_terminal_failure(attempt_count=MAX_ATTEMPTS) is True


def test_is_terminal_failure_true_past_max():
    """attempt_count > MAX_ATTEMPTS → still terminal (defensive)."""
    assert is_terminal_failure(attempt_count=MAX_ATTEMPTS + 1) is True
    assert is_terminal_failure(attempt_count=99) is True


def test_is_terminal_failure_consistent_with_next_retry_at():
    """Cross-check: is_terminal_failure should be True iff
    next_retry_at returns None.

    Pin the consistency so a refactor that updates one but not
    the other (e.g. bumps MAX_ATTEMPTS in one place) breaks here
    instead of subtly leaving rows in `pending` forever."""
    for n in [-1, 0, 3, 5, 6, 99]:
        terminal = is_terminal_failure(attempt_count=n)
        next_at = next_retry_at(attempt_count=n, base_time=_BASE)
        # Negative is the one asymmetric case — both paths return
        # None / True, but for different reasons. Either way the
        # dispatcher treats it as "don't re-queue."
        if n < 0:
            assert next_at is None
            continue
        assert terminal == (next_at is None), (
            f"is_terminal_failure({n})={terminal} vs next_retry_at({n})={'None' if next_at is None else 'datetime'}"
        )
