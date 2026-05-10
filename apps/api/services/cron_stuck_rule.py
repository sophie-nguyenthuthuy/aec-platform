"""Cron stuck-detection rule (cycle Y3).

Pure-helper module. Decides whether a `running` cron_runs row has
been running long enough to flag as "stuck" (the worker probably
crashed mid-run, and the row will never finish without operator
intervention).

Today this rule appears in two places:

  * `services/cron_alerts.py::_is_stuck` — the watchdog cron's
    Slack-alert decision.
  * `services/cron_telemetry.py::latest_run_per_cron` — the
    `/admin/crons` dashboard's per-row "stuck" pill computation.

The integrator-surface snapshot pins them aligned, but the LOGIC
is duplicated. A subtle change (e.g. bumping multiplier from 3.0
to 5.0 to reduce false alerts) currently means two edits + two
reviews. This module is the single source of truth.

Rule:

  * `sample_count < min_samples` → return False.
    The p95 over fewer than 3 samples is too noisy; a brand-new
    cron's first slow run shouldn't page.
  * `p95_ms is None or p95_ms <= 0` → return False.
    Degenerate baseline (cron has never succeeded, or every run
    took 0ms — usually a no-op cron). Pin returns False so we
    don't multiply zero × multiplier and flag every running row.
  * Otherwise → `elapsed_ms > multiplier × p95_ms`.

Defaults match the existing watchdog: multiplier=3.0, min_samples=3.
The 3× rationale: healthy crons cluster within 2× p95 even on
slow days; 3× ignores a slow-but-progressing run while flagging
truly hung ones. Tune each independently per call if needed.

Pure Python — no DB, no async. Drop-in replacement for the two
existing duplicated implementations.
"""

from __future__ import annotations

# Default multiplier — elapsed > N × p95 = stuck.
# 3.0 picked over 5× / 10× because:
#   * Healthy crons cluster within 2× p95 even on a slow day, so
#     3× ignores normal variance.
#   * 10× would mean a 1-minute-baseline cron has to run 10 minutes
#     before alerting; 3× = 3 minutes alert lag, faster MTTR.
#   * The "10× expected" heuristic is folk wisdom; 3× is the
#     SRE-Workbook-shaped "p95 + safety margin" version.
DEFAULT_MULTIPLIER = 3.0

# Minimum successful-run samples before the rule is allowed to
# fire. Below this, p95 is too noisy to alert on.
DEFAULT_MIN_SAMPLES = 3


def is_stuck(
    *,
    elapsed_ms: float | int | None,
    p95_ms: float | int | None,
    sample_count: int | None,
    multiplier: float = DEFAULT_MULTIPLIER,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> bool:
    """Pure decision: is this running cron's elapsed time past the
    stuck threshold?

    Three guards before the comparison:

      1. `sample_count` < `min_samples` → False. Skip.
      2. `p95_ms` None or non-positive → False. Skip.
      3. `elapsed_ms` None → False. Defensive against missing
         elapsed columns from the SQL projection.

    Otherwise: `elapsed_ms > multiplier × p95_ms`.

    Returns False on insufficient data — a missed alert is
    recoverable (next watchdog tick has more samples), a false
    alert wakes someone up at 3am for nothing.

    Why kwargs-only: the function takes 5 numeric values. Positional
    calls would be brittle (which is which?). Forcing keyword form
    makes call sites self-documenting.
    """
    if sample_count is None or sample_count < min_samples:
        return False
    if p95_ms is None:
        return False
    if p95_ms <= 0:
        return False
    if elapsed_ms is None:
        return False
    return float(elapsed_ms) > float(multiplier) * float(p95_ms)


def stuck_threshold_ms(
    *,
    p95_ms: float | int | None,
    sample_count: int | None,
    multiplier: float = DEFAULT_MULTIPLIER,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> float | None:
    """Compute the elapsed-ms threshold at which a row would flag.

    Returns the threshold (`multiplier × p95`) when the rule is
    armable, None when it isn't (insufficient samples, missing /
    non-positive p95). Useful for:

      * Dashboard rendering "stuck after Xs" tooltip on an
        in-flight row.
      * Tests that want to construct a row exactly at / past the
        threshold without re-doing the multiplier math.

    Same guard order as `is_stuck`. Returning None for unarmable
    cases keeps the caller's integer-comparison branches honest:
    `if elapsed > stuck_threshold_ms(...)` would be a type error
    on None, forcing the caller to handle the unarmable path
    explicitly.
    """
    if sample_count is None or sample_count < min_samples:
        return None
    if p95_ms is None or p95_ms <= 0:
        return None
    return float(multiplier) * float(p95_ms)
