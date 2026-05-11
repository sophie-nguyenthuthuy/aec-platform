"""Backoff jitter helper (cycle OO3).

Pinned seams:
  1. DEFAULT_JITTER_PCT = 0.2 (±20%).
  2. MIN_DELAY_SECONDS = 1.0.
  3. Determinism: same (seed, attempt) → same delay.
  4. Jitter band: [base*0.8, base*1.2].
  5. jitter_pct=0 returns base unchanged (floor-clamped).
  6. jitter_pct out of [0, 1] raises ValueError.
  7. Different seeds / attempts → different delays.
  8. Composes with Z1 webhook_backoff schedule.
"""

from __future__ import annotations

import pytest

from services.backoff_jitter import (
    DEFAULT_JITTER_PCT,
    MIN_DELAY_SECONDS,
    apply_jitter,
)

# ---------- Constants ----------


def test_default_jitter_pct():
    assert DEFAULT_JITTER_PCT == 0.2


def test_min_delay_seconds():
    assert MIN_DELAY_SECONDS == 1.0


# ---------- Determinism ----------


def test_deterministic_same_inputs():
    """Cardinal pin: same (seed, attempt) always yields same
    delay. Defends against a refactor that introduces RNG state
    — a retry scheduled for offset T should stay at offset T
    across worker restarts."""
    a = apply_jitter(60, 1, "seed-A")
    b = apply_jitter(60, 1, "seed-A")
    assert a == b


def test_deterministic_across_calls():
    """Multiple sequential calls all match."""
    seeds = ["seed-A", "seed-B", "seed-C"]
    for seed in seeds:
        for attempt in range(5):
            a = apply_jitter(60, attempt, seed)
            b = apply_jitter(60, attempt, seed)
            assert a == b


# ---------- Jitter band ----------


def test_jitter_within_band():
    """Cardinal pin: result always in [base*(1-pct), base*(1+pct)].
    Pin so a refactor that widens the band silently surfaces."""
    base = 60.0
    for attempt in range(100):
        result = apply_jitter(base, attempt, "seed-X")
        assert base * 0.8 <= result <= base * 1.2, (
            f"attempt={attempt}: {result} outside band [{base * 0.8}, {base * 1.2}]"
        )


def test_jitter_band_with_custom_pct():
    """Custom jitter_pct narrows / widens the band."""
    base = 100.0
    for attempt in range(50):
        result = apply_jitter(base, attempt, "seed", jitter_pct=0.1)
        assert base * 0.9 <= result <= base * 1.1


# ---------- Floor ----------


def test_min_delay_floor():
    """Even with deep negative jitter on a small base, the
    delay is floored to MIN_DELAY_SECONDS."""
    # base=0.5 with -20% would give 0.4s, but floor is 1.0.
    result = apply_jitter(0.5, 1, "seed")
    assert result >= MIN_DELAY_SECONDS


def test_min_delay_floor_with_zero_base():
    """Cardinal pin: even base=0 gets floored to MIN_DELAY."""
    result = apply_jitter(0.0, 1, "seed")
    assert result == MIN_DELAY_SECONDS


# ---------- jitter_pct = 0 (no-op) ----------


def test_zero_jitter_returns_base_unchanged():
    """jitter_pct=0 is the no-op idiom. Pin so a refactor that
    treats 0 as "use default" surfaces here."""
    assert apply_jitter(60, 1, "seed", jitter_pct=0.0) == 60.0


def test_zero_jitter_still_floor_clamped():
    """jitter_pct=0 doesn't bypass the MIN_DELAY floor."""
    assert apply_jitter(0.5, 1, "seed", jitter_pct=0.0) == MIN_DELAY_SECONDS


# ---------- jitter_pct validation ----------


def test_negative_jitter_pct_raises():
    """Pin: negative jitter_pct is a config bug — raise rather
    than silently widen the band into negatives."""
    with pytest.raises(ValueError):
        apply_jitter(60, 1, "seed", jitter_pct=-0.1)


def test_jitter_pct_above_one_raises():
    """Pin: 100%+ jitter would give negative delays even before
    the floor. Raise to surface config bugs."""
    with pytest.raises(ValueError):
        apply_jitter(60, 1, "seed", jitter_pct=1.5)


def test_jitter_pct_at_zero_boundary_allowed():
    apply_jitter(60, 1, "seed", jitter_pct=0.0)  # no raise


def test_jitter_pct_at_one_boundary_allowed():
    """Pin: 100% jitter is technically valid (huge spread).
    Boundary [0, 1] inclusive."""
    apply_jitter(60, 1, "seed", jitter_pct=1.0)  # no raise


# ---------- Variance ----------


def test_different_seeds_yield_different_delays():
    """Cardinal pin: different seeds spread retries across
    subscriptions. Defends against multi-tenant herd."""
    a = apply_jitter(60, 1, "seed-A")
    b = apply_jitter(60, 1, "seed-B")
    # Astronomically unlikely to collide for two random seeds.
    assert a != b


def test_different_attempts_yield_different_delays():
    """Pin: same seed, different attempts → different jitter.
    Defends against the same retry chain landing on the same
    offset across attempts."""
    a = apply_jitter(60, 1, "seed-A")
    b = apply_jitter(60, 2, "seed-A")
    assert a != b


def test_jitter_distributes_across_band():
    """Sanity: many attempts spread across the band (not all
    landing at the same offset). Take 100 jittered values, check
    that at least 5 distinct buckets are populated."""
    base = 60.0
    values = [apply_jitter(base, i, "seed-Y") for i in range(100)]
    # Bucket into 10 bins across the band.
    bins: set[int] = set()
    for v in values:
        # Map to [0, 10) bucket index across the [0.8*base, 1.2*base] band.
        normalized = (v - base * 0.8) / (base * 0.4)
        bucket = min(9, int(normalized * 10))
        bins.add(bucket)
    # Expect distribution across many bins.
    assert len(bins) >= 5, f"jitter not well-distributed: {len(bins)} bins"


# ---------- Composition with Z1 ----------


def test_composes_with_z1_backoff_schedule():
    """Cardinal cross-cycle pin: Z1's BACKOFF_MINUTES schedule
    feeds into apply_jitter for the actual sleep duration the
    worker uses. Pin the composition pattern."""
    from services.webhook_backoff import BACKOFF_MINUTES

    # Z1 schedule values pin: [0, 1, 5, 30, 120, 720] minutes.
    assert BACKOFF_MINUTES[1] == 1
    assert BACKOFF_MINUTES[2] == 5
    assert BACKOFF_MINUTES[3] == 30

    # Worker pattern: base = Z1's minutes * 60 seconds, then jitter.
    base_seconds = BACKOFF_MINUTES[2] * 60  # 5 min = 300s
    jittered = apply_jitter(base_seconds, 2, "subscription-id-42")
    # Should be within ±20% of 300s.
    assert 240 <= jittered <= 360


def test_z1_attempt_zero_floors_to_min_delay():
    """Z1's BACKOFF_MINUTES[0] = 0 (immediate retry). After
    jitter, this still floors to MIN_DELAY_SECONDS."""
    from services.webhook_backoff import BACKOFF_MINUTES

    assert BACKOFF_MINUTES[0] == 0
    base_seconds = BACKOFF_MINUTES[0] * 60  # 0s
    jittered = apply_jitter(base_seconds, 0, "sub-id")
    assert jittered == MIN_DELAY_SECONDS
