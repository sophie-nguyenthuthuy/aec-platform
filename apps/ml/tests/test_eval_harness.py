"""Unit tests for the eval-harness pure helpers.

The DB + LLM-touching code paths run only via `make eval-all` with
real credentials. Here we lock in the report shape + the drift guard
that catches forgotten case additions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `scripts.eval_harness` importable without a full apps/ml install.
_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))


def test_codeguard_cases_are_complete_and_well_formed():
    from scripts.eval_harness import codeguard_cases

    cases = codeguard_cases()
    assert len(cases) >= 8
    for c in cases:
        assert c.case_id
        assert c.suite == "codeguard"
        assert c.question
        assert c.expected_section_ref  # codeguard requires section anchor


def test_drawbridge_cases_use_keyword_matching():
    """Drawbridge eval pairs target keyword presence, not section refs,
    because drawings don't have crisp section anchors."""
    from scripts.eval_harness import drawbridge_cases

    cases = drawbridge_cases()
    assert len(cases) >= 5
    for c in cases:
        assert c.case_id
        assert c.suite == "drawbridge"
        assert c.expected_section_ref is None
        assert len(c.expected_keywords) >= 2


def test_empty_report_shape():
    """Skip-safe path: when DB unreachable, build_report → 0/0/0 with
    accuracy_pct=0, not a division-by-zero."""
    from scripts.eval_harness import _empty_report

    r = _empty_report("codeguard", reason="missing_db_url")
    assert r.suite == "codeguard"
    assert r.total == 0
    assert r.accuracy_pct == 0.0
    assert r.cases == []


def test_build_report_aggregates_correctly():
    from scripts.eval_harness import CaseResult, _build_report

    results = [
        CaseResult(
            case_id="c1", suite="x", question="q",
            passed=True, reason="ok",
            input_tokens=100, output_tokens=50, cost_vnd=120, latency_ms=300,
        ),
        CaseResult(
            case_id="c2", suite="x", question="q",
            passed=False, reason="missed",
            input_tokens=200, output_tokens=80, cost_vnd=240, latency_ms=500,
        ),
        CaseResult(
            case_id="c3", suite="x", question="q",
            passed=False, reason="exception", error="boom",
            input_tokens=0, output_tokens=0, cost_vnd=0, latency_ms=10,
        ),
    ]
    r = _build_report("x", results)
    assert r.total == 3
    assert r.passed == 1
    assert r.error == 1
    assert r.failed == 1  # total - passed - error
    assert abs(r.accuracy_pct - (1 / 3 * 100)) < 0.01
    assert r.total_cost_vnd == 360
    assert r.total_input_tokens == 300
    assert r.total_output_tokens == 130
    assert r.avg_latency_ms == int((300 + 500 + 10) / 3)


def test_html_renderer_emits_valid_top_level_tags():
    """Smoke check the HTML report — must include the doctype, KPI tiles,
    and a row per case. Out-of-scope: full DOM validation."""
    from scripts.eval_harness import (
        CaseResult,
        SuiteReport,
        _render_html,
    )

    report = SuiteReport(
        suite="codeguard",
        generated_at="2026-05-15T10:00:00+00:00",
        total=1, passed=1, failed=0, error=0,
        accuracy_pct=100.0,
        total_cost_vnd=120, total_input_tokens=100, total_output_tokens=50,
        avg_latency_ms=300,
        cases=[
            CaseResult(
                case_id="c1", suite="codeguard", question="Q?",
                passed=True, reason="ok",
                input_tokens=100, output_tokens=50, cost_vnd=120, latency_ms=300,
            ),
        ],
    )
    html = _render_html(report)
    assert "<!doctype html>" in html.lower()
    assert "codeguard" in html
    assert "c1" in html
    assert "100.0%" in html


def test_manifest_drift_guard_passes_when_in_sync():
    """The drift guard reads the test_codeguard_quality_eval.py file
    + the harness's codeguard_cases() and asserts case IDs are a
    subset. Passes silently when in sync."""
    from scripts.eval_harness import check_case_manifest_in_sync

    # Must not raise.
    check_case_manifest_in_sync()


def test_unknown_suite_name_raises():
    """`run_suite` rejects bogus suite names rather than silently
    no-op'ing — protects against typos in CI invocations."""
    import asyncio
    import os
    from scripts.eval_harness import run_suite

    os.environ["TEST_DATABASE_URL"] = "postgresql+asyncpg://fake/db"
    try:
        with pytest.raises(ValueError, match="unknown suite"):
            asyncio.run(run_suite("does-not-exist"))
    finally:
        os.environ.pop("TEST_DATABASE_URL", None)
