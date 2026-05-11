"""Pin the `services.cron_alerts` watchdog — fresh-failure +
stuck-cron Slack alerter.

Two distinct decision rules in this module, both calibrated and
both with high cost-of-regression:

  * **Fresh-failure window.** Every 5 min, alert on `cron_runs`
    rows that failed in the last 5 min. A regression that drifted
    the window away from the cron's tick interval would either:
      - **Drop alerts** (window < tick): a failure at minute 4
        falls between tick 0 and tick 5, never gets surfaced.
      - **Double-alert** (window > tick): a single failure gets
        announced twice, eroding trust in the alerts.

  * **Stuck-cron multiplier.** A `running` cron that's exceeded
    `_STUCK_MULTIPLIER × p95(7d)` is flagged. Calibration trade-offs:
      - Lifting the multiplier (5×, 10×) means slower MTTR on
        truly hung crons.
      - Lowering it (1.5×, 2×) means slow-but-progressing runs
        get false-flagged — wakes someone at 3am for a healthy
        run that was just having a slow night.
      - The 3× value sits at the documented "healthy clusters
        within 2× p95 even on a slow day" boundary.

Other invariants this file pins:

  * **Slack `kind` literals are SEPARATE.** `cron_failure` ≠
    `cron_stuck` so the `/admin/slack-deliveries` dashboard's filter
    cleanly separates them. A regression that merged into one kind
    would silently make the failure-rate metrics for both surfaces
    inseparable.

  * **`_is_stuck` insufficient-data guards.** A cron with <3
    baseline samples OR p95=0 returns False. The conservative-on-
    insufficient-data choice is what prevents the "first run after
    deploy gets paged" failure mode.

  * **DISTINCT ON (cron_name) collapses repeat failures.** A cron
    that fires every minute and has been failing for 4 of the last
    5 minutes produces ONE alert, not five. A regression that
    dropped DISTINCT ON would hammer Slack on chronic failures —
    the noise-amplifier classic anti-pattern.

  * **Fresh-failures filter happens in Python, NOT SQL.** Pushing
    `WHERE status = 'failed'` into the SQL would make DISTINCT ON
    miss the "failed → succeeded → failed" sequence's interim
    recovery. Pin the in-Python filter.

  * **Watchdog is self-wrapped via `_telemetry`** so the alerter
    itself shows up in `/admin/crons`. A regression that registered
    the watchdog without the wrapper would silently break the
    "alerter health is observable" property — if the alerter
    breaks, you'd never know until you noticed alerts had stopped.

  * **Watchdog tick === fresh-failure window.** Both pinned at
    5 min in different files; cross-pin asserts they agree.

This file is read-only — exercises pure helpers + source-greps the
SQL + watchdog wiring. Survives reverts.
"""

from __future__ import annotations

import inspect
from pathlib import Path

# ---------- Module + public surface ----------


def test_cron_alerts_module_imports():
    """All public + private surfaces importable. Hard ImportError on
    revert = the desired loud signal vs silently broken alerting."""
    from services.cron_alerts import (  # noqa: F401
        _BASELINE_WINDOW_DAYS,
        _FRESH_FAILURE_WINDOW_MINUTES,
        _MIN_SAMPLES_FOR_BASELINE,
        _STUCK_MULTIPLIER,
        _is_stuck,
        check_failing_crons,
        check_stuck_crons,
    )


def test_public_exports_via_dunder_all():
    """Both watchdog entrypoints are in `__all__`. The watchdog cron
    in `workers/queue.py` imports them by name; a regression that
    dropped one from the public surface would break the cron's
    import line."""
    import services.cron_alerts as mod

    assert "check_failing_crons" in mod.__all__
    assert "check_stuck_crons" in mod.__all__


# ---------- Constants — calibrated values ----------


def test_fresh_failure_window_pinned_at_5_minutes():
    """The window MUST equal the watchdog cron's tick interval (also
    5 min in `WorkerSettings.cron_jobs`). Drift in either direction
    breaks the alert pipeline silently — see module docstring."""
    from services.cron_alerts import _FRESH_FAILURE_WINDOW_MINUTES

    assert _FRESH_FAILURE_WINDOW_MINUTES == 5, (
        f"_FRESH_FAILURE_WINDOW_MINUTES drifted to "
        f"{_FRESH_FAILURE_WINDOW_MINUTES}. The watchdog tick (in "
        "workers.queue.WorkerSettings.cron_jobs) is 5 min — "
        "mismatch silently drops or double-emits alerts."
    )


def test_stuck_multiplier_pinned_at_3x():
    """3× p95 is the calibrated "this is hung, not slow" boundary.
    Re-tuning means re-running the noise-vs-signal analysis against
    historical cron durations.

    Lifting (5×, 10×) means slower MTTR on hung crons.
    Lowering (1.5×, 2×) means slow-but-progressing runs flag.
    """
    from services.cron_alerts import _STUCK_MULTIPLIER

    assert _STUCK_MULTIPLIER == 3.0, (
        f"_STUCK_MULTIPLIER drifted to {_STUCK_MULTIPLIER}. The 3× "
        "value sits at the boundary documented in the module "
        "docstring; re-tuning needs a deliberate calibration pass."
    )


def test_min_samples_for_baseline_pinned_at_3():
    """A cron with <3 successful samples in the window has no
    credible baseline. Alerting on its first run is noise — pin the
    floor so a "be more aggressive about catching regressions"
    refactor doesn't silently turn the watchdog into a 3am pager
    for fresh deployments."""
    from services.cron_alerts import _MIN_SAMPLES_FOR_BASELINE

    assert _MIN_SAMPLES_FOR_BASELINE == 3, (
        f"_MIN_SAMPLES_FOR_BASELINE drifted to "
        f"{_MIN_SAMPLES_FOR_BASELINE}. Lower means false-flagging "
        "fresh deploys' first runs; higher means missed alerts on "
        "newly-stuck crons."
    )


def test_baseline_window_days_at_least_7():
    """The window MUST be ≥ the longest cron interval in the
    registry (`weekly_report_cron` = 7d). A shorter window means
    the weekly cron has zero baseline samples, which short-circuits
    the stuck check via `_MIN_SAMPLES_FOR_BASELINE` and silently
    disables stuck detection for weekly crons."""
    from services.cron_alerts import _BASELINE_WINDOW_DAYS

    assert _BASELINE_WINDOW_DAYS >= 7, (
        f"_BASELINE_WINDOW_DAYS dropped to {_BASELINE_WINDOW_DAYS}. "
        "Weekly crons (weekly_report, codeguard_quota_reconcile) "
        "need ≥7d to accumulate the minimum baseline samples; a "
        "shorter window silently disables stuck detection for them."
    )


def test_baseline_window_pinned_at_7_days():
    """7d is the calibrated value. Pinning the exact value catches
    "I'll bump to 14d for stability" tweaks that change the noise
    profile — the watchdog's noise floor is sensitive to this."""
    from services.cron_alerts import _BASELINE_WINDOW_DAYS

    assert _BASELINE_WINDOW_DAYS == 7


# ---------- Slack `kind` literals — dashboard filter discriminators ----------


def test_failure_alert_kind_is_cron_failure():
    """The kind literal is what `/admin/slack-deliveries` filters on.
    Pin via source-grep — a rename to `crons.failure` would break the
    dashboard's per-kind summary card silently."""
    import services.cron_alerts as mod

    src = inspect.getsource(mod.check_failing_crons)
    assert "_KIND" in src or '"cron_failure"' in src, (
        "check_failing_crons no longer uses the documented `cron_failure` "
        "kind literal. The /admin/slack-deliveries dashboard filters on "
        "this exact string."
    )

    # Read the module-level _KIND constant directly.
    from services.cron_alerts import _KIND

    assert _KIND == "cron_failure", (
        f"_KIND drifted to {_KIND!r}. The slack-deliveries dashboard "
        "filter pin (and ops's mental model) hardcodes 'cron_failure'."
    )


def test_stuck_alert_kind_is_cron_stuck_distinct_from_failure():
    """SECURITY/CORRECTNESS pin: the stuck-cron alert uses a
    DIFFERENT kind than fresh-failure. A regression that merged
    them into one kind would let a chronic failure (frequent) and
    a stuck cron (rare but high-priority) be indistinguishable in
    the dashboard's filter — ops would have to read every text
    preview to tell them apart.
    """
    import services.cron_alerts as mod

    src = inspect.getsource(mod.check_stuck_crons)
    assert '"cron_stuck"' in src, (
        "check_stuck_crons no longer uses `cron_stuck` as the "
        "Slack kind. The dashboard relies on this literal to "
        "separate the failure pile from the stuck pile."
    )
    # And the failure path uses a DIFFERENT literal — pin the
    # discriminator so a refactor that unified them fails CI.
    from services.cron_alerts import _KIND

    assert _KIND != "cron_stuck", (
        "Failure kind == stuck kind. The two surfaces MUST be filter-separable in /admin/slack-deliveries."
    )


# ---------- _is_stuck decision rule ----------


def test_is_stuck_returns_false_when_no_baseline():
    """No samples in the window → return False conservatively. The
    "fresh deploy" path: a brand-new cron has zero successful runs
    in the last 7d, so its baseline is None. Alerting on its very
    first run would page someone for the first run after every
    deploy."""
    from services.cron_alerts import _is_stuck

    row = {
        "cron_name": "cron:fresh_one",
        "elapsed_ms": 999_999_999,  # comically long
        "sample_count": None,
        "p95_ms": None,
    }
    assert _is_stuck(row) is False, (
        "_is_stuck flagged a cron with no baseline as stuck. The "
        "guard is what prevents 3am pages on first-run-after-deploy."
    )


def test_is_stuck_returns_false_when_below_min_samples():
    """`<3` samples → return False. The `_MIN_SAMPLES_FOR_BASELINE`
    floor; a rolling p95 over 1-2 samples isn't a credible baseline."""
    from services.cron_alerts import _is_stuck

    row = {
        "cron_name": "cron:few",
        "elapsed_ms": 999_999_999,
        "sample_count": 2,  # below the floor
        "p95_ms": 100,
    }
    assert _is_stuck(row) is False


def test_is_stuck_returns_false_when_p95_is_zero():
    """`p95 == 0` → return False. A cron whose p95 is 0 is a no-op
    cron; multiplier × 0 = 0 → every run would flag. Pin the
    explicit guard so the "no-op cron means alert on every run"
    failure mode can't slip in.
    """
    from services.cron_alerts import _is_stuck

    row = {
        "cron_name": "cron:noop",
        "elapsed_ms": 100,
        "sample_count": 100,  # plenty of samples
        "p95_ms": 0,  # but they were all 0ms
    }
    assert _is_stuck(row) is False


def test_is_stuck_returns_true_when_elapsed_exceeds_3x_p95():
    """Happy path — a running row whose elapsed time exceeds 3× p95
    is flagged. The 3× value MUST be the test's threshold; this
    pin couples to `_STUCK_MULTIPLIER` so a tweak there + a tweak
    here is the deliberate-change pattern."""
    from services.cron_alerts import _STUCK_MULTIPLIER, _is_stuck

    p95_ms = 1000.0  # 1s baseline
    elapsed_ms = p95_ms * (_STUCK_MULTIPLIER + 0.1)  # 3.1× → over

    row = {
        "cron_name": "cron:stuck",
        "elapsed_ms": elapsed_ms,
        "sample_count": 100,
        "p95_ms": p95_ms,
    }
    assert _is_stuck(row) is True


def test_is_stuck_returns_false_at_or_below_3x_p95():
    """Boundary: at exactly 3× p95 the run is NOT yet stuck. The
    operator (and the Slack message) talks about "exceeded 3×",
    not "reached 3×" — pin the strictly-greater semantics so a
    change from `>` to `>=` doesn't silently change the threshold.
    """
    from services.cron_alerts import _STUCK_MULTIPLIER, _is_stuck

    p95_ms = 1000.0
    # Exactly 3× — should NOT flag.
    elapsed_ms = p95_ms * _STUCK_MULTIPLIER

    row = {
        "cron_name": "cron:edge",
        "elapsed_ms": elapsed_ms,
        "sample_count": 100,
        "p95_ms": p95_ms,
    }
    assert _is_stuck(row) is False, (
        "_is_stuck flagged a run at EXACTLY 3× p95 — the threshold "
        "is strictly-greater. Drifting to >= silently shifts the "
        "alert threshold downward."
    )


# ---------- _fresh_failures source invariants ----------


def test_fresh_failures_uses_distinct_on_to_collapse_repeats():
    """SECURITY pin against alert-storms. A cron that fires every
    minute and has been failing for 4 of the last 5 minutes MUST
    produce ONE alert. DISTINCT ON (cron_name) collapses repeats
    into the latest row per cron. A regression that dropped
    DISTINCT ON would Slack-bomb on chronic failures."""
    import services.cron_alerts as mod

    src = inspect.getsource(mod._fresh_failures)
    assert "DISTINCT ON (cron_name)" in src, (
        "_fresh_failures no longer collapses with DISTINCT ON. "
        "Chronic failures would now produce one Slack message per "
        "cron_runs row in the window — alert-storm anti-pattern."
    )


def test_fresh_failures_filters_in_python_not_sql():
    """The SQL fetches the latest row per cron (regardless of status);
    the Python filter `r["status"] == "failed"` happens after.
    Pushing the filter into SQL would let DISTINCT ON skip a
    "failed → succeeded → failed" sequence's interim recovery —
    we want last_status, not last_failure.
    """
    import services.cron_alerts as mod

    src = inspect.getsource(mod._fresh_failures)

    # The SQL block (between text(""" ... """)) MUST NOT carry a
    # status filter — that would defeat DISTINCT ON's "last row per
    # cron" semantics and miss interim recoveries.
    sql_start = src.find("text(\n")
    sql_end = src.find('"""\n    )', sql_start)
    sql_block = src[sql_start:sql_end].lower() if sql_end != -1 else ""
    assert "status = 'failed'" not in sql_block, (
        "_fresh_failures pushed the status='failed' filter into the "
        "SQL block. Doing so makes DISTINCT ON skip interim recoveries "
        "— a 'failed → succeeded → failed' sequence collapses to the "
        "first failure, missing the second."
    )

    # And the Python-side filter exists outside the SQL block.
    assert 'r["status"] == "failed"' in src or "r['status'] == 'failed'" in src, (
        "_fresh_failures dropped the Python-side status filter. "
        "Either every row is alerted (succeeded ones too!) or the "
        "SQL was changed without updating both sides."
    )


# ---------- _running_crons_with_baseline source invariants ----------


def test_running_crons_query_uses_percentile_cont():
    """The p95 is computed via `percentile_cont(0.95) WITHIN GROUP
    (ORDER BY duration_ms)` — PG-native, no in-Python sort. A
    regression to `percentile_disc` (different semantics) or a
    Python sort (slow on large baselines) would either break the
    decision rule's calibration or scale poorly."""
    import services.cron_alerts as mod

    src = inspect.getsource(mod._running_crons_with_baseline)
    assert "percentile_cont(0.95)" in src, (
        "_running_crons_with_baseline no longer uses percentile_cont(0.95). "
        "The 3× p95 calibration is keyed on continuous-percentile "
        "semantics; percentile_disc would shift the boundary."
    )


def test_running_crons_query_filters_status_running_AND_finished_at_null():
    """Both predicates because a row could in theory be left in
    `running` status by a crashed wrapper before `finished_at`
    gets set. The explicit NULL check makes that case still
    surface.
    """
    import services.cron_alerts as mod

    src = inspect.getsource(mod._running_crons_with_baseline)
    assert "status = 'running'" in src
    assert (
        "finished_at IS NULL" in src.upper().replace("FINISHED_AT IS NULL", "finished_at IS NULL")
        or "finished_at IS NULL" in src
    ), (
        "_running_crons_with_baseline no longer requires "
        "finished_at IS NULL. A row stuck with status='running' "
        "but stale finished_at would slip past the watchdog."
    )


# ---------- Watchdog signatures ----------


def test_check_failing_crons_returns_documented_summary_keys():
    """The watchdog cron logs the return at INFO. Renaming the keys
    would silently break any log-aggregator dashboard that grouped
    by them."""
    import asyncio

    import services.cron_alerts as mod

    # Stub the SQL helper so we don't need a DB.
    async def _stub_no_failures():
        return []

    original = mod._fresh_failures
    mod._fresh_failures = _stub_no_failures  # type: ignore[assignment]
    try:
        out = asyncio.run(mod.check_failing_crons())
    finally:
        mod._fresh_failures = original  # type: ignore[assignment]

    assert set(out.keys()) == {"checked", "alerted", "skipped"}, (
        f"check_failing_crons summary keys drifted: {set(out.keys())}"
    )


def test_check_stuck_crons_returns_documented_summary_keys():
    """Same shape pin for the stuck-cron summary."""
    import asyncio

    import services.cron_alerts as mod

    async def _stub_no_running():
        return []

    original = mod._running_crons_with_baseline
    mod._running_crons_with_baseline = _stub_no_running  # type: ignore[assignment]
    try:
        out = asyncio.run(mod.check_stuck_crons())
    finally:
        mod._running_crons_with_baseline = original  # type: ignore[assignment]

    assert set(out.keys()) == {"checked", "stuck", "alerted"}, (
        f"check_stuck_crons summary keys drifted: {set(out.keys())}"
    )


# ---------- Watchdog wiring in workers/queue.py ----------


def test_watchdog_cron_runs_every_5_minutes():
    """Cross-file pin. The cron registered for
    `cron_failure_watchdog_cron` MUST tick every 5 min — matching
    `_FRESH_FAILURE_WINDOW_MINUTES`. Source-grep for the
    `minute={i for i in range(0, 60, 5)}` literal in `WorkerSettings`.
    """
    from pathlib import Path

    queue_path = Path(__file__).parent.parent / "workers" / "queue.py"
    src = queue_path.read_text()

    # The watchdog registration line. We check the `cron_failure_watchdog_cron`
    # appears AND the same line uses the 5-minute multiple set.
    assert "cron_failure_watchdog_cron" in src, (
        "workers/queue.py no longer registers cron_failure_watchdog_cron. "
        "Without the cron entry, the watchdog never runs — fresh "
        "failures + stuck crons go un-alerted."
    )
    # Match the documented every-5-minute set syntax.
    assert "minute={i for i in range(0, 60, 5)}" in src, (
        "Watchdog cron tick interval drifted from every-5-minute. "
        "MUST match _FRESH_FAILURE_WINDOW_MINUTES (5) — see module "
        "docstring of services.cron_alerts."
    )


def test_watchdog_is_self_wrapped_via_telemetry():
    """The watchdog ITSELF MUST be wrapped via `_telemetry(...)` so
    it shows up in `/admin/crons`. A regression that registered
    bare `cron_failure_watchdog_cron` would break the "alerter is
    visible in the registry" property — if the alerter breaks,
    you'd never know.
    """
    queue_path = Path(__file__).parent.parent / "workers" / "queue.py"
    src = queue_path.read_text()

    assert "_telemetry(cron_failure_watchdog_cron)" in src, (
        "cron_failure_watchdog_cron is registered without _telemetry "
        "wrap. The alerter's own runs won't appear in /admin/crons; "
        "a broken alerter would be silently invisible."
    )


def test_watchdog_calls_both_check_paths():
    """The cron coroutine in `workers/queue.py` calls BOTH
    `check_failing_crons` AND `check_stuck_crons`. A regression that
    dropped one would silently disable that surface (failure-only
    OR stuck-only, no signal).
    """
    queue_path = Path(__file__).parent.parent / "workers" / "queue.py"
    src = queue_path.read_text()

    # Look at the watchdog function definition.
    assert "check_failing_crons" in src, "Watchdog no longer calls check_failing_crons. Fresh failures go un-alerted."
    assert "check_stuck_crons" in src, (
        "Watchdog no longer calls check_stuck_crons. Stuck-mid-run "
        "crons go un-alerted — the most operationally-important "
        "signal during incidents."
    )


def test_watchdog_catches_independent_per_path_failures():
    """SECURITY/AVAILABILITY pin. The watchdog runs both checks in
    sequence with INDEPENDENT try/except blocks. A failure of the
    fresh-failure path MUST NOT prevent the stuck-cron path from
    running. Pin via source-grep: two `except Exception` blocks in
    the watchdog body.
    """
    queue_path = Path(__file__).parent.parent / "workers" / "queue.py"
    src = queue_path.read_text()

    # Find the watchdog cron's body.
    body_start = src.find("async def cron_failure_watchdog_cron")
    assert body_start != -1, (
        "cron_failure_watchdog_cron not found. The watchdog cron's "
        "function definition is the wiring point for both checks."
    )
    # Look for "next def" or end of cron_jobs to bound the body
    # search. Counting except-Exception inside the body.
    next_def = src.find("\nasync def ", body_start + 1)
    body = src[body_start : next_def if next_def != -1 else len(src)]

    except_count = body.count("except Exception")
    assert except_count >= 2, (
        f"Watchdog has only {except_count} `except Exception` block(s). "
        "Both check paths MUST have independent error handling — a "
        "failure on the failure-check shouldn't skip the stuck-check."
    )
