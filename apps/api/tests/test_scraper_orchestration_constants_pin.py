"""Pin the orchestration-level constants in `services.price_scrapers`.

Why this exists: two small constants in `services/price_scrapers/__init__.py`
shape every scrape's customer-facing behaviour:

  * `_DRIFT_THRESHOLD = 0.30` — when `unmatched / scraped > 0.30`,
    `run_scraper` logs a `scraper.drift` WARNING that triggers the
    ops-alert email + Slack pipeline. A typo to 0.03 would page
    ops on every healthy run; a typo to 3.0 would silence the
    drift detector entirely (no scrape ever exceeds 100% unmatched).

  * `_UNMATCHED_SAMPLE_CAP = 25` — the per-run cap on distinct
    unmatched material names retained for telemetry. The
    `unmatched_sample` field in `scraper_runs` is what ops use
    to write new normalizer rules — too small (5) misses the
    long-tail drift signal; too big (500) bloats the JSONB
    column and the per-row payload size.

These two values were tuned across multiple scrape windows; each
is a "load-bearing magic number" that a reviewer might be tempted
to "clean up" without understanding the calibration. Pin both so
a tweak has to be deliberate.

This file also pins the structural invariants:
  * `_DRIFT_THRESHOLD` is a probability (0 < x < 1).
  * `_UNMATCHED_SAMPLE_CAP` is a positive integer.
  * Both names exist in the module (a rename would break consumers).

If you intentionally re-tune either, update the EXPECTED below in
the same PR + verify the change against the historical drift
distribution (a tighter threshold pages more often; a looser one
masks more regressions).
"""

from __future__ import annotations

from services import price_scrapers

# ---------- Drift threshold ----------


def test_drift_threshold_is_pinned_at_thirty_percent():
    """30% unmatched is the canonical "this scraper has drifted"
    boundary. Tuned because:

      * Typical healthy runs are 5-15% unmatched (long-tail
        materials never get rules written for them).
      * 30% is comfortably above the noise floor — a healthy slug
        won't false-positive.
      * 30% is comfortably below the "completely broken" zone (a
        slug whose source page changed format usually drops to
        70-90% matching).

    Re-tuning means going back to the historical drift distribution
    and re-picking the noise-vs-signal trade. Pin so the change
    has to be deliberate.
    """
    assert price_scrapers._DRIFT_THRESHOLD == 0.30, (
        f"_DRIFT_THRESHOLD changed to {price_scrapers._DRIFT_THRESHOLD}. "
        "If this is intentional, update the pin here in the same PR "
        "+ document the new noise-vs-signal calibration."
    )


def test_drift_threshold_is_a_probability():
    """Defensive: must be in (0, 1). 0.0 would page on every run
    (every scrape has at least one unmatched row); 1.0 would
    never page (no scrape ever exceeds 100%). Catches a typo
    like `30` (intended as percent points but read as ratio).
    """
    assert 0.0 < price_scrapers._DRIFT_THRESHOLD < 1.0, (
        f"_DRIFT_THRESHOLD = {price_scrapers._DRIFT_THRESHOLD} is outside "
        "(0, 1). The threshold is a ratio (`unmatched / scraped`), not a "
        "percent — a typo `30` instead of `0.30` would silence the drift "
        "detector entirely."
    )


# ---------- Unmatched sample cap ----------


def test_unmatched_sample_cap_is_pinned_at_25():
    """25 distinct unmatched names per run.

    Tuning rationale:
      * The full list can run hundreds of names — most are
        long-tail variants that will never be worth a rule.
      * 25 captures enough to spot a new pattern (e.g. a province
        renaming "Bê tông M300" to "BT cấp C30") without
        bloating the JSONB column.
      * The admin UI's drift sample shows the first 5 anyway;
        25 gives ops a deeper pool to scan when they investigate.

    A re-tune up (50, 100) bloats every scraper_runs row; a re-
    tune down (5, 10) loses the long-tail visibility. Either way
    surfaces here.
    """
    assert price_scrapers._UNMATCHED_SAMPLE_CAP == 25, (
        f"_UNMATCHED_SAMPLE_CAP changed to "
        f"{price_scrapers._UNMATCHED_SAMPLE_CAP}. "
        "Re-tuning impacts both telemetry value and JSONB payload size."
    )


def test_unmatched_sample_cap_is_positive_int():
    """A negative or zero cap silently produces no sample (the
    `len(out) >= cap` check fires immediately on first row).
    Pin positive int to catch a `0` or `-1` regression."""
    cap = price_scrapers._UNMATCHED_SAMPLE_CAP
    assert isinstance(cap, int), f"cap is {type(cap).__name__}, want int"
    assert cap > 0, f"cap = {cap}, must be > 0 (else no sample is retained)"


# ---------- Module-level invariants ----------


def test_constants_exposed_under_documented_names():
    """Both constants are referenced by tests + admin-UI code via
    `services.price_scrapers._DRIFT_THRESHOLD` etc. A rename (e.g.
    to `DRIFT_RATIO_THRESHOLD`) would silently break consumers
    importing the documented names. Pin the names explicitly."""
    assert hasattr(price_scrapers, "_DRIFT_THRESHOLD"), (
        "services.price_scrapers no longer exposes `_DRIFT_THRESHOLD`. "
        "If renamed, update consumers (`grep -rn '_DRIFT_THRESHOLD' apps/api`)."
    )
    assert hasattr(price_scrapers, "_UNMATCHED_SAMPLE_CAP"), (
        "services.price_scrapers no longer exposes `_UNMATCHED_SAMPLE_CAP`."
    )


def test_drift_threshold_matches_admin_ui_amber_threshold():
    """The frontend's `<Sparkline>` (in
    `apps/web/app/(dashboard)/admin/scrapers/_components/Sparkline.tsx`)
    tints the line amber when any point exceeds 30% drift — the
    same threshold the email/log alert uses. If we ever shift
    `_DRIFT_THRESHOLD`, the admin UI's amber boundary needs to
    move with it (else ops sees green sparklines on slugs that
    triggered an alert email, or vice versa).

    This test pins the cross-system invariant: the API-side
    threshold lines up with the documented frontend threshold.
    The frontend constant lives in TS and isn't directly imported
    here, so we pin the value (0.30) in both places' docs.
    """
    # If the API-side threshold changes, the matching change in
    # `apps/web/app/(dashboard)/admin/scrapers/_components/Sparkline.tsx`
    # (the `threshold={0.3}` prop on the sparkline) has to be
    # made in the same PR. This assertion's existence signals
    # the cross-system contract; the actual cross-system check
    # would need the apps/web tree to be importable here, which
    # it isn't.
    assert price_scrapers._DRIFT_THRESHOLD == 0.30
