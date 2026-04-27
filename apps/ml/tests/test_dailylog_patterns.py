"""Unit tests for `ml.pipelines.dailylog.aggregate_patterns`.

This is a pure-Python rollup function — no DB, no LLM, no async — that
takes the denormalised query results passed in by the router and shapes
them into the `PatternsResponse` schema. It's the right layer to exercise
the rollup math directly so a regression doesn't sneak in via a router
test that mocks the function out.

Coverage targets
----------------
* `days_observed` is `len(log_rows)`, even when manpower_rows is empty.
* `avg_headcount` averages over `days_observed`, not over manpower rows
  (a 4-day window with 2 manpower entries divides by 4, not 2).
* `weather_anomaly_days` only flags days at-or-above the threshold —
  default 10mm; honours the override.
* `most_common_observations` truncates the description to 80 chars and
  caps at 5 entries (matches `Counter.most_common(5)`).
* `issue_count_by_kind` and `severity_counts` are flat string→int dicts.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from uuid import UUID

# `ml/pipelines/dailylog.py` is at apps/ml/pipelines/. Tests run from the
# repo root via the root pyproject's `testpaths`, so apps/ml/ has to be
# on sys.path for the bare-package `from pipelines.dailylog import ...`
# resolution. Mirror what the api conftest does.
_ML_ROOT = Path(__file__).resolve().parent.parent  # apps/ml/
if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))


PROJECT_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_days_observed_counts_logs_not_manpower():
    from pipelines.dailylog import aggregate_patterns

    out = aggregate_patterns(
        project_id=PROJECT_ID,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 4),
        log_rows=[
            {"log_date": date(2026, 4, 1), "weather": None},
            {"log_date": date(2026, 4, 2), "weather": None},
            {"log_date": date(2026, 4, 3), "weather": None},
            {"log_date": date(2026, 4, 4), "weather": None},
        ],
        manpower_rows=[
            {"headcount": 20},
            {"headcount": 30},
        ],
        observation_rows=[],
    )

    assert out["days_observed"] == 4
    # 50 total headcount / 4 days observed (NOT / 2 manpower rows).
    assert out["avg_headcount"] == 12.5


def test_zero_logs_does_not_divide_by_zero():
    from pipelines.dailylog import aggregate_patterns

    out = aggregate_patterns(
        project_id=PROJECT_ID,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 4),
        log_rows=[],
        manpower_rows=[{"headcount": 50}],  # would divide by 0 without the guard
        observation_rows=[],
    )

    assert out["days_observed"] == 0
    # `max(days_observed, 1)` guard keeps this finite.
    assert out["avg_headcount"] == 50.0


def test_weather_anomaly_days_at_or_above_threshold():
    from pipelines.dailylog import aggregate_patterns

    out = aggregate_patterns(
        project_id=PROJECT_ID,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 5),
        log_rows=[
            {"log_date": date(2026, 4, 1), "weather": {"precipitation_mm": 0}},
            {"log_date": date(2026, 4, 2), "weather": {"precipitation_mm": 9.9}},
            {"log_date": date(2026, 4, 3), "weather": {"precipitation_mm": 10}},  # at threshold
            {
                "log_date": date(2026, 4, 4),
                "weather": {"precipitation_mm": 25, "conditions": "rain"},
            },
            {"log_date": date(2026, 4, 5), "weather": None},
        ],
        manpower_rows=[],
        observation_rows=[],
    )

    flagged = [d["log_date"] for d in out["weather_anomaly_days"]]
    assert flagged == [date(2026, 4, 3), date(2026, 4, 4)]
    # The threshold-day entry retains its `conditions=None`; the heavy
    # rain day carries through the conditions string.
    heavy = next(d for d in out["weather_anomaly_days"] if d["precipitation_mm"] == 25)
    assert heavy["conditions"] == "rain"


def test_weather_anomaly_threshold_override():
    from pipelines.dailylog import aggregate_patterns

    out = aggregate_patterns(
        project_id=PROJECT_ID,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 1),
        log_rows=[
            {"log_date": date(2026, 4, 1), "weather": {"precipitation_mm": 6}},
        ],
        manpower_rows=[],
        observation_rows=[],
        weather_anomaly_threshold_mm=5.0,
    )

    assert len(out["weather_anomaly_days"]) == 1
    assert out["weather_anomaly_days"][0]["precipitation_mm"] == 6.0


def test_most_common_observations_truncated_and_capped_at_five():
    from pipelines.dailylog import aggregate_patterns

    long_desc = "x" * 200  # > 80 chars; output must be exactly 80 chars
    obs = (
        # Six distinct descriptions, each repeated to give a clear ranking.
        [{"description": "scaffold loose"}] * 5
        + [{"description": "ppe missing"}] * 4
        + [{"description": "trench unsafe"}] * 3
        + [{"description": "rebar exposed"}] * 2
        + [{"description": "lighting weak"}] * 1
        + [{"description": "cleanup needed"}] * 1
        # And a single very-long description that must be truncated.
        + [{"description": long_desc}] * 7
    )

    out = aggregate_patterns(
        project_id=PROJECT_ID,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 1),
        log_rows=[],
        manpower_rows=[],
        observation_rows=obs,
    )

    most = out["most_common_observations"]
    # Capped at 5.
    assert len(most) == 5

    # Top entry is the truncated 80-char string with count=7.
    assert most[0]["description"] == "x" * 80
    assert most[0]["count"] == 7

    # Subsequent entries follow the descending counts.
    counts = [entry["count"] for entry in most]
    assert counts == sorted(counts, reverse=True)


def test_kind_and_severity_counts_are_flat_dicts():
    from pipelines.dailylog import aggregate_patterns

    out = aggregate_patterns(
        project_id=PROJECT_ID,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 1),
        log_rows=[],
        manpower_rows=[],
        observation_rows=[
            {"kind": "safety", "severity": "high"},
            {"kind": "safety", "severity": "low"},
            {"kind": "quality", "severity": "low"},
        ],
    )

    # Plain {str: int}, no Counter / OrderedDict surprises.
    assert isinstance(out["issue_count_by_kind"], dict)
    assert out["issue_count_by_kind"] == {"safety": 2, "quality": 1}
    assert out["severity_counts"] == {"high": 1, "low": 2}


def test_observation_with_no_description_is_excluded_from_most_common():
    from pipelines.dailylog import aggregate_patterns

    out = aggregate_patterns(
        project_id=PROJECT_ID,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 1),
        log_rows=[],
        manpower_rows=[],
        observation_rows=[
            {"description": "real issue"},
            {"description": None},
            {"description": ""},
            {},  # missing key
        ],
    )

    # Only the row with a non-empty description should land in the rollup.
    descriptions = [m["description"] for m in out["most_common_observations"]]
    assert descriptions == ["real issue"]
