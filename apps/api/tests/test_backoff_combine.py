"""Backoff jitter combiner (cycle VV1).

Pinned seams:
  1. attempt 0 floors to OO3's MIN_DELAY_SECONDS (1s).
  2. attempt N → Z1's BACKOFF_MINUTES[N] * 60 ± OO3's jitter band.
  3. attempt < 0 raises ValueError.
  4. attempt >= MAX_ATTEMPTS raises ValueError.
  5. Deterministic given (attempt, seed, jitter_pct).
  6. Cross-cycle: imports Z1 + OO3 directly.
"""

from __future__ import annotations

import pytest

from services.backoff_combine import compute_jittered_delay
from services.backoff_jitter import MIN_DELAY_SECONDS
from services.webhook_backoff import BACKOFF_MINUTES, MAX_ATTEMPTS

# ---------- Boundary attempts ----------


def test_attempt_0_floors_to_min_delay():
    """Z1's BACKOFF_MINUTES[0] = 0. Even with jitter, OO3
    floors to MIN_DELAY_SECONDS = 1s."""
    delay = compute_jittered_delay(0, "seed-A")
    assert delay == MIN_DELAY_SECONDS


def test_attempt_1_within_60s_band():
    """Z1's BACKOFF_MINUTES[1] = 1 minute = 60s.
    ± 20% jitter → [48, 72]."""
    delay = compute_jittered_delay(1, "seed-A")
    assert 48 <= delay <= 72


def test_attempt_2_within_5min_band():
    """Z1's BACKOFF_MINUTES[2] = 5 min = 300s.
    ± 20% jitter → [240, 360]."""
    delay = compute_jittered_delay(2, "seed-A")
    assert 240 <= delay <= 360


def test_attempt_3_within_30min_band():
    """Z1's BACKOFF_MINUTES[3] = 30 min = 1800s.
    ± 20% jitter → [1440, 2160]."""
    delay = compute_jittered_delay(3, "seed-A")
    assert 1440 <= delay <= 2160


def test_attempt_4_within_2hr_band():
    """Z1's BACKOFF_MINUTES[4] = 120 min = 7200s.
    ± 20% jitter → [5760, 8640]."""
    delay = compute_jittered_delay(4, "seed-A")
    assert 5760 <= delay <= 8640


def test_attempt_5_within_12hr_band():
    """Z1's BACKOFF_MINUTES[5] = 720 min = 43200s (12h).
    ± 20% jitter → [34560, 51840]."""
    delay = compute_jittered_delay(5, "seed-A")
    assert 34560 <= delay <= 51840


# ---------- Out of range ----------


def test_negative_attempt_raises():
    with pytest.raises(ValueError):
        compute_jittered_delay(-1, "seed-A")


def test_attempt_at_max_raises():
    """Cardinal pin: attempt >= MAX_ATTEMPTS is terminal —
    raise rather than schedule further retries."""
    with pytest.raises(ValueError):
        compute_jittered_delay(MAX_ATTEMPTS, "seed-A")


def test_attempt_past_max_raises():
    with pytest.raises(ValueError):
        compute_jittered_delay(MAX_ATTEMPTS + 1, "seed-A")


def test_attempt_at_max_minus_one_succeeds():
    """The last valid attempt is MAX_ATTEMPTS - 1."""
    delay = compute_jittered_delay(MAX_ATTEMPTS - 1, "seed-A")
    assert delay >= MIN_DELAY_SECONDS


# ---------- Determinism ----------


def test_deterministic_same_input():
    """Same (attempt, seed) → same delay."""
    a = compute_jittered_delay(2, "seed-A")
    b = compute_jittered_delay(2, "seed-A")
    assert a == b


def test_different_seeds_different_delays():
    a = compute_jittered_delay(2, "seed-A")
    b = compute_jittered_delay(2, "seed-B")
    assert a != b


def test_different_attempts_different_delays():
    a = compute_jittered_delay(1, "seed-A")
    b = compute_jittered_delay(2, "seed-A")
    assert a != b


# ---------- jitter_pct=0 (no-op) ----------


def test_jitter_pct_zero_returns_exact_base():
    """jitter_pct=0 → no jitter. attempt 1 → exactly 60s."""
    delay = compute_jittered_delay(1, "seed", jitter_pct=0.0)
    assert delay == 60.0


def test_jitter_pct_zero_attempt_0_floors():
    """Even with no jitter, attempt 0 (base=0) floors to MIN."""
    delay = compute_jittered_delay(0, "seed", jitter_pct=0.0)
    assert delay == MIN_DELAY_SECONDS


# ---------- Cross-cycle composition ----------


def test_imports_z1_backoff_minutes():
    """Cross-cycle pin: this module's behaviour follows Z1's
    schedule. A bump in Z1 BACKOFF_MINUTES would surface
    here via the band tests."""
    assert BACKOFF_MINUTES == [0, 1, 5, 30, 120, 720]


def test_imports_z1_max_attempts():
    """Cross-cycle pin: terminal threshold matches Z1."""
    assert MAX_ATTEMPTS == 6


def test_composes_z1_and_oo3_chain():
    """Cardinal cross-cycle pin: this module's `compute_jittered_delay`
    is equivalent to manually composing Z1's BACKOFF_MINUTES +
    OO3's apply_jitter. Verify via direct comparison."""
    from services.backoff_jitter import apply_jitter

    for attempt in range(MAX_ATTEMPTS):
        manual = apply_jitter(
            BACKOFF_MINUTES[attempt] * 60,
            attempt,
            "seed-X",
        )
        composed = compute_jittered_delay(attempt, "seed-X")
        assert manual == composed, f"attempt={attempt}: manual={manual}, composed={composed}"
