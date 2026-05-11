"""Cron stuck-detection rule (cycle Y3).

Pinned seams:
  1. Three guards before comparison: insufficient samples, non-
     positive p95, missing elapsed.
  2. The 3× multiplier and 3-sample minimum constants pinned so
     a "let's bump to 5×" PR triggers a deliberate review.
  3. Boundary: elapsed > 3×p95 → stuck; elapsed == 3×p95 → NOT
     stuck (strict greater-than).
  4. `stuck_threshold_ms` returns None when unarmable so callers
     can't accidentally compare elapsed against zero.
"""

from __future__ import annotations

from services.cron_stuck_rule import (
    DEFAULT_MIN_SAMPLES,
    DEFAULT_MULTIPLIER,
    is_stuck,
    stuck_threshold_ms,
)

# ---------- Constants ----------


def test_default_multiplier_pinned_to_3x():
    """3× p95 is the "this is past normal variance, probably hung"
    threshold. Pin so a refactor doesn't silently widen / tighten
    the false-positive vs false-negative trade."""
    assert DEFAULT_MULTIPLIER == 3.0


def test_default_min_samples_pinned_to_3():
    """3 samples is the smallest credible "this is repeatable
    behaviour" — below that, p95 over 1-2 runs is too noisy to
    alert on."""
    assert DEFAULT_MIN_SAMPLES == 3


# ---------- is_stuck guards ----------


def test_is_stuck_returns_false_for_insufficient_samples():
    """A brand-new cron with 1 sample shouldn't alert just because
    its first run was slow. Pin the guard."""
    out = is_stuck(elapsed_ms=60_000, p95_ms=1000, sample_count=1)
    assert out is False


def test_is_stuck_returns_false_for_zero_samples():
    """Edge: zero samples (no successful runs yet)."""
    out = is_stuck(elapsed_ms=60_000, p95_ms=1000, sample_count=0)
    assert out is False


def test_is_stuck_returns_false_for_none_sample_count():
    """`sample_count` None happens when the LEFT JOIN finds no
    baseline row. Treat as insufficient data."""
    out = is_stuck(elapsed_ms=60_000, p95_ms=1000, sample_count=None)
    assert out is False


def test_is_stuck_returns_false_for_none_p95():
    """No baseline row → p95 None. Don't alert."""
    out = is_stuck(elapsed_ms=60_000, p95_ms=None, sample_count=10)
    assert out is False


def test_is_stuck_returns_false_for_zero_p95():
    """Degenerate baseline: every successful run took 0ms (usually
    a no-op cron). multiplier × 0 = 0 means EVERY run would flag —
    skip."""
    out = is_stuck(elapsed_ms=60_000, p95_ms=0, sample_count=10)
    assert out is False


def test_is_stuck_returns_false_for_negative_p95():
    """p95 < 0 is impossible from real data but defensive — guard
    treats <=0 the same as 0."""
    out = is_stuck(elapsed_ms=60_000, p95_ms=-100, sample_count=10)
    assert out is False


def test_is_stuck_returns_false_for_none_elapsed():
    """`elapsed_ms` None happens for non-running rows (CASE WHEN
    branch returns NULL). Defensive — even though the caller
    should already filter to running rows."""
    out = is_stuck(elapsed_ms=None, p95_ms=1000, sample_count=10)
    assert out is False


# ---------- is_stuck comparison ----------


def test_is_stuck_true_when_elapsed_well_past_threshold():
    """Canonical: elapsed = 60s, p95 = 1s, multiplier = 3 →
    60 > 3 → stuck."""
    out = is_stuck(elapsed_ms=60_000, p95_ms=1000, sample_count=10)
    assert out is True


def test_is_stuck_false_when_elapsed_below_threshold():
    """elapsed = 2× p95 — within normal variance, not stuck."""
    out = is_stuck(elapsed_ms=2000, p95_ms=1000, sample_count=10)
    assert out is False


def test_is_stuck_strict_greater_than_at_boundary():
    """elapsed = exactly 3× p95 → NOT stuck (strict >). Pin the
    boundary so a refactor that switches to >= silently flips
    every cron at-the-line over the threshold."""
    out = is_stuck(elapsed_ms=3000, p95_ms=1000, sample_count=10)
    assert out is False
    # Just past it → stuck.
    out_past = is_stuck(elapsed_ms=3001, p95_ms=1000, sample_count=10)
    assert out_past is True


def test_is_stuck_respects_custom_multiplier():
    """Caller can override the 3× default — useful for tests +
    future per-cron tuning. Pin so the kwarg actually changes
    the threshold."""
    # 5× threshold: elapsed must be > 5000ms.
    out_under = is_stuck(elapsed_ms=4000, p95_ms=1000, sample_count=10, multiplier=5.0)
    out_over = is_stuck(elapsed_ms=6000, p95_ms=1000, sample_count=10, multiplier=5.0)
    assert out_under is False
    assert out_over is True


def test_is_stuck_respects_custom_min_samples():
    """A future per-cron config might bump min_samples for noisy
    crons — kwarg must thread through."""
    # 1 sample with default min_samples (3) → skip.
    assert is_stuck(elapsed_ms=60_000, p95_ms=1000, sample_count=1) is False
    # Same data with min_samples=1 → fire.
    assert is_stuck(elapsed_ms=60_000, p95_ms=1000, sample_count=1, min_samples=1) is True


def test_is_stuck_handles_float_inputs():
    """Some SQL paths return floats for ms columns (DECIMAL casts).
    Pin no float-vs-int mismatch."""
    out = is_stuck(
        elapsed_ms=3001.5,
        p95_ms=1000.0,
        sample_count=10,
    )
    assert out is True


# ---------- stuck_threshold_ms ----------


def test_threshold_returns_multiplied_p95():
    """The threshold IS multiplier × p95 — pin so a refactor that
    introduces an additive offset would surface."""
    out = stuck_threshold_ms(p95_ms=1000, sample_count=10)
    assert out == 3000.0


def test_threshold_returns_none_for_unarmable_cases():
    """Insufficient samples / non-positive p95 → None (NOT 0). The
    caller MUST handle None explicitly; comparing `elapsed > 0`
    against an unarmable threshold would always flag, which is
    exactly the bug the guards exist to prevent."""
    assert stuck_threshold_ms(p95_ms=1000, sample_count=1) is None
    assert stuck_threshold_ms(p95_ms=None, sample_count=10) is None
    assert stuck_threshold_ms(p95_ms=0, sample_count=10) is None


def test_threshold_kwarg_consistency_with_is_stuck():
    """`is_stuck(elapsed=X+1, ...)` MUST agree with
    `stuck_threshold_ms(...) < X+1` whenever the threshold is
    armable. Pin the cross-helper consistency."""
    p95 = 1000
    samples = 10
    threshold = stuck_threshold_ms(p95_ms=p95, sample_count=samples)
    assert threshold is not None
    # At the threshold → not stuck.
    assert is_stuck(elapsed_ms=threshold, p95_ms=p95, sample_count=samples) is False
    # Just past → stuck.
    assert is_stuck(elapsed_ms=threshold + 1, p95_ms=p95, sample_count=samples) is True
