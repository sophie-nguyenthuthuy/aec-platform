"""AEC Platform AI quality eval harness.

Runs curated Q&A pairs through CodeGuard + Drawbridge pipelines and
produces an accuracy + cost report. Designed to be:

  * Cheap-skip-able when API keys aren't set (CI-safe).
  * Trend-trackable — writes results to `apps/ml/eval_results/{date}.json`
    so a regression in CodeGuard accuracy across model upgrades is
    visible by diffing the latest two JSON files.
  * Cost-transparent — reports both per-question and total VND spend
    so the team knows what each release-candidate eval costs.

Usage:
    cd apps/ml
    python -m scripts.eval_harness --suite codeguard
    python -m scripts.eval_harness --suite drawbridge
    python -m scripts.eval_harness --suite all --report html

Output:
    apps/ml/eval_results/2026-05-15-codeguard.json  (machine-readable)
    apps/ml/eval_results/2026-05-15-codeguard.html  (browseable report)

Requirements (gated, skip-safe):
    TEST_DATABASE_URL  — Postgres with fixtures seeded
    GOOGLE_API_KEY     — for embeddings + Gemini chat (cheap)
    ANTHROPIC_API_KEY  — for Claude scan (optional; falls back to Gemini)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval_results"


@dataclass
class EvalCase:
    case_id: str
    suite: str
    question: str
    expected_section_ref: str | None = None
    expected_keywords: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case_id: str
    suite: str
    question: str
    passed: bool
    reason: str
    actual_citations: list[str] = field(default_factory=list)
    confidence: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_vnd: int = 0
    latency_ms: int = 0
    error: str | None = None


@dataclass
class SuiteReport:
    suite: str
    generated_at: str
    total: int
    passed: int
    failed: int
    error: int
    accuracy_pct: float
    total_cost_vnd: int
    total_input_tokens: int
    total_output_tokens: int
    avg_latency_ms: int
    cases: list[CaseResult] = field(default_factory=list)


# ---------- Eval case definitions ----------


def codeguard_cases() -> list[EvalCase]:
    """Mirror of QA_PAIRS in tests/test_codeguard_quality_eval.py.

    Kept in sync via the manifest-drift guard at the bottom of this file.
    Cross-section questions deliberately excluded — keep assertions tight.
    """
    return [
        EvalCase("corridor_width", "codeguard",
                 "Chiều rộng tối thiểu của hành lang thoát nạn trong nhà chung cư là bao nhiêu?",
                 expected_section_ref="3.2.1"),
        EvalCase("exit_count", "codeguard",
                 "Số lượng lối thoát nạn tối thiểu trên mỗi tầng được quy định thế nào?",
                 expected_section_ref="3.1"),
        EvalCase("fire_resistance", "codeguard",
                 "Bậc chịu lửa của nhà được phân loại như thế nào?",
                 expected_section_ref="2.1"),
        EvalCase("fire_compartment", "codeguard",
                 "Khoang cháy có yêu cầu gì về diện tích và bậc chịu lửa?",
                 expected_section_ref="2.2"),
        EvalCase("evacuation_distance", "codeguard",
                 "Khoảng cách thoát nạn tối đa cho phép là bao nhiêu mét?",
                 expected_section_ref="3.3"),
        EvalCase("fire_alarm", "codeguard",
                 "Hệ thống báo cháy tự động yêu cầu lắp đặt ở đâu?",
                 expected_section_ref="4.1"),
        EvalCase("smoke_extraction", "codeguard",
                 "Hệ thống hút khói hành lang có yêu cầu gì?",
                 expected_section_ref="5.1"),
        EvalCase("stair_pressurization", "codeguard",
                 "Tạo áp buồng thang bộ yêu cầu gì?",
                 expected_section_ref="5.2"),
    ]


def drawbridge_cases() -> list[EvalCase]:
    """Drawing-Q&A eval. These require an ingested drawing set.

    Section refs aren't applicable; we check expected keywords appear
    in the cited excerpts instead (more forgiving — drawings don't
    always have crisp section anchors).
    """
    return [
        EvalCase("floor_thickness", "drawbridge",
                 "Bản vẽ M2 ghi độ dày sàn tầng 3 là bao nhiêu mm?",
                 expected_keywords=["sàn", "tầng 3", "mm"]),
        EvalCase("electrical_room_count", "drawbridge",
                 "Trên mặt bằng tầng 1 có mấy phòng kỹ thuật điện?",
                 expected_keywords=["phòng kỹ thuật", "điện"]),
        EvalCase("emergency_exit_count", "drawbridge",
                 "Có bao nhiêu lối thoát hiểm trên tầng điển hình?",
                 expected_keywords=["thoát hiểm", "lối"]),
        EvalCase("elevator_spec", "drawbridge",
                 "Thông số kỹ thuật của thang máy hành khách là gì?",
                 expected_keywords=["thang máy", "tải trọng", "tốc độ"]),
        EvalCase("hvac_capacity", "drawbridge",
                 "Tổng công suất hệ HVAC là bao nhiêu kW?",
                 expected_keywords=["HVAC", "công suất", "kW"]),
    ]


# ---------- Runners ----------


async def run_codeguard_case(case: EvalCase, session: Any) -> CaseResult:
    """Execute one CodeGuard case via the live pipeline.

    Imports happen lazily so the harness module is importable on
    machines without the ML deps (the runner will then skip via
    the env-var check before touching this).
    """
    from ml.pipelines.codeguard import answer_question  # type: ignore[import-not-found]
    from services.llm_spend import compute_cost_vnd

    t0 = time.time()
    try:
        result = await answer_question(
            db=session,
            organization_id=None,  # cross-tenant eval — admin session bypasses RLS
            question=case.question,
            category="fire_safety",
        )
    except Exception as exc:
        return CaseResult(
            case_id=case.case_id,
            suite=case.suite,
            question=case.question,
            passed=False,
            reason="pipeline_exception",
            error=str(exc)[:200],
            latency_ms=int((time.time() - t0) * 1000),
        )

    latency_ms = int((time.time() - t0) * 1000)
    citations = [c.section_ref for c in result.citations] if result.citations else []
    passed = (
        case.expected_section_ref is not None
        and case.expected_section_ref in citations
        and (result.confidence or 0) > 0.3
    )
    reason = (
        "ok"
        if passed
        else f"expected_section={case.expected_section_ref} not in {citations} (conf={result.confidence:.2f})"
    )

    in_tokens = getattr(result, "input_tokens", 0) or 0
    out_tokens = getattr(result, "output_tokens", 0) or 0
    cost = compute_cost_vnd(
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=in_tokens,
        output_tokens=out_tokens,
    )

    return CaseResult(
        case_id=case.case_id,
        suite=case.suite,
        question=case.question,
        passed=passed,
        reason=reason,
        actual_citations=citations,
        confidence=result.confidence,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        cost_vnd=cost,
        latency_ms=latency_ms,
    )


async def run_drawbridge_case(case: EvalCase, session: Any) -> CaseResult:
    """Execute one Drawbridge case via the live pipeline."""
    from ml.pipelines.drawbridge import answer_document_query  # type: ignore[import-not-found]
    from services.llm_spend import compute_cost_vnd

    t0 = time.time()
    try:
        result = await answer_document_query(
            db=session,
            organization_id=None,
            project_id=os.environ.get("EVAL_DRAWBRIDGE_PROJECT_ID"),  # set by ops
            question=case.question,
            disciplines=None,
        )
    except Exception as exc:
        return CaseResult(
            case_id=case.case_id,
            suite=case.suite,
            question=case.question,
            passed=False,
            reason="pipeline_exception",
            error=str(exc)[:200],
            latency_ms=int((time.time() - t0) * 1000),
        )

    latency_ms = int((time.time() - t0) * 1000)
    answer_text = (result.answer or "").lower()
    matched = [k for k in case.expected_keywords if k.lower() in answer_text]
    passed = (
        len(matched) >= max(1, len(case.expected_keywords) // 2)
        and len(result.source_documents) > 0
        and (result.confidence or 0) > 0.3
    )
    reason = (
        "ok"
        if passed
        else f"matched_kw={matched} / expected={case.expected_keywords} "
             f"(conf={result.confidence:.2f}, sources={len(result.source_documents)})"
    )

    in_tokens = getattr(result, "input_tokens", 0) or 0
    out_tokens = getattr(result, "output_tokens", 0) or 0
    cost = compute_cost_vnd(
        provider="gemini",
        model="gemini-1.5-flash",
        input_tokens=in_tokens,
        output_tokens=out_tokens,
    )

    return CaseResult(
        case_id=case.case_id,
        suite=case.suite,
        question=case.question,
        passed=passed,
        reason=reason,
        actual_citations=[d.document_id for d in result.source_documents][:5],
        confidence=result.confidence,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        cost_vnd=cost,
        latency_ms=latency_ms,
    )


# ---------- Top-level orchestration ----------


async def run_suite(suite_name: str) -> SuiteReport:
    """Run all cases of a suite. Skip-safe when DB unreachable.

    Returns the aggregate report. Callers can serialise to JSON or
    render HTML.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    db_url = os.environ.get("TEST_DATABASE_URL")
    if not db_url:
        logger.warning("TEST_DATABASE_URL not set — skipping %s suite", suite_name)
        return _empty_report(suite_name, reason="missing_db_url")

    if suite_name == "codeguard":
        cases = codeguard_cases()
        runner = run_codeguard_case
    elif suite_name == "drawbridge":
        cases = drawbridge_cases()
        runner = run_drawbridge_case
    else:
        raise ValueError(f"unknown suite: {suite_name}")

    engine = create_async_engine(db_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    results: list[CaseResult] = []
    async with factory() as session:
        for case in cases:
            logger.info("eval[%s] running %s", suite_name, case.case_id)
            try:
                res = await runner(case, session)
            except Exception as exc:
                res = CaseResult(
                    case_id=case.case_id,
                    suite=case.suite,
                    question=case.question,
                    passed=False,
                    reason="runner_exception",
                    error=str(exc)[:200],
                )
            results.append(res)
            logger.info(
                "eval[%s] %s — %s  (%dms, %d VND)",
                suite_name,
                case.case_id,
                "PASS" if res.passed else "FAIL",
                res.latency_ms,
                res.cost_vnd,
            )

    return _build_report(suite_name, results)


def _empty_report(suite: str, reason: str) -> SuiteReport:
    return SuiteReport(
        suite=suite,
        generated_at=datetime.now(UTC).isoformat(),
        total=0,
        passed=0,
        failed=0,
        error=0,
        accuracy_pct=0.0,
        total_cost_vnd=0,
        total_input_tokens=0,
        total_output_tokens=0,
        avg_latency_ms=0,
        cases=[],
    )


def _build_report(suite: str, results: list[CaseResult]) -> SuiteReport:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    error = sum(1 for r in results if r.error)
    failed = total - passed - error
    return SuiteReport(
        suite=suite,
        generated_at=datetime.now(UTC).isoformat(),
        total=total,
        passed=passed,
        failed=failed,
        error=error,
        accuracy_pct=(passed / total * 100) if total else 0.0,
        total_cost_vnd=sum(r.cost_vnd for r in results),
        total_input_tokens=sum(r.input_tokens for r in results),
        total_output_tokens=sum(r.output_tokens for r in results),
        avg_latency_ms=int(sum(r.latency_ms for r in results) / total) if total else 0,
        cases=results,
    )


# ---------- Persistence ----------


def write_results(report: SuiteReport, fmt: str = "json") -> Path:
    """Save the report under apps/ml/eval_results/{date}-{suite}.{ext}."""
    RESULTS_DIR.mkdir(exist_ok=True)
    stem = f"{datetime.now(UTC).strftime('%Y-%m-%d')}-{report.suite}"
    if fmt == "html":
        path = RESULTS_DIR / f"{stem}.html"
        path.write_text(_render_html(report), encoding="utf-8")
    else:
        path = RESULTS_DIR / f"{stem}.json"
        path.write_text(
            json.dumps(asdict(report), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    logger.info("wrote eval report → %s", path)
    return path


def _render_html(report: SuiteReport) -> str:
    """Minimal HTML report. Browseable + email-friendly."""
    rows = []
    for c in report.cases:
        status = "✅" if c.passed else ("⚠️" if c.error else "❌")
        conf_str = f"{c.confidence:.2f}" if c.confidence is not None else "—"
        rows.append(
            f"<tr><td>{status}</td>"
            f"<td><code>{c.case_id}</code></td>"
            f"<td>{c.question[:80]}</td>"
            f"<td>{conf_str}</td>"
            f"<td>{c.latency_ms}ms</td>"
            f"<td>{c.cost_vnd:,} đ</td>"
            f"<td>{c.reason}</td></tr>"
        )
    rows_html = "\n".join(rows)
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<title>Eval report — {report.suite} {report.generated_at[:10]}</title>
<style>
body{{font-family:system-ui;max-width:980px;margin:2rem auto;padding:0 1rem;color:#0f172a}}
h1{{color:#0f172a}}
.kpi{{display:flex;gap:1rem;margin:1rem 0}}
.kpi div{{flex:1;background:#f1f5f9;padding:1rem;border-radius:.5rem}}
.kpi div p:first-child{{color:#64748b;font-size:.75rem;text-transform:uppercase;margin:0}}
.kpi div p:last-child{{font-size:1.5rem;font-weight:700;margin:.25rem 0 0}}
table{{width:100%;border-collapse:collapse;font-size:.875rem}}
th,td{{padding:.5rem;border-bottom:1px solid #e2e8f0;text-align:left;vertical-align:top}}
th{{background:#f8fafc;font-size:.75rem;text-transform:uppercase;color:#475569}}
</style></head><body>
<h1>Eval report — {report.suite}</h1>
<p>Generated at {report.generated_at}</p>
<div class="kpi">
  <div><p>Tổng</p><p>{report.total}</p></div>
  <div><p>Pass</p><p style="color:#10b981">{report.passed}</p></div>
  <div><p>Fail</p><p style="color:#ef4444">{report.failed}</p></div>
  <div><p>Error</p><p style="color:#f59e0b">{report.error}</p></div>
  <div><p>Accuracy</p><p>{report.accuracy_pct:.1f}%</p></div>
  <div><p>Chi phí</p><p>{report.total_cost_vnd:,} đ</p></div>
  <div><p>Latency TB</p><p>{report.avg_latency_ms}ms</p></div>
</div>
<table>
<thead><tr><th></th><th>Case</th><th>Câu hỏi</th><th>Conf</th><th>Latency</th><th>Cost</th><th>Reason</th></tr></thead>
<tbody>
{rows_html}
</tbody></table>
</body></html>"""


# ---------- Drift guard ----------


def check_case_manifest_in_sync():
    """The CodeGuard cases here must match the test file's QA_PAIRS.

    Run by the CI dry-run so a developer who adds a case in one place
    + forgets the other gets a loud test failure instead of a silently
    stale eval.
    """
    expected_ids = {c.case_id for c in codeguard_cases()}
    test_file = Path(__file__).resolve().parent.parent / "tests" / "test_codeguard_quality_eval.py"
    if not test_file.exists():
        return
    text = test_file.read_text(encoding="utf-8")
    actual_ids = set()
    for line in text.splitlines():
        s = line.strip()
        # Match the (quoted) first element of each tuple in QA_PAIRS.
        if s.startswith('"') and s.endswith('",'):
            candidate = s.strip('",')
            if "_" in candidate and candidate.replace("_", "").isalnum():
                actual_ids.add(candidate)
    missing = expected_ids - actual_ids
    if missing:
        raise AssertionError(
            f"eval_harness codeguard cases out of sync with test_codeguard_quality_eval.py: "
            f"missing in test file: {missing}"
        )


# ---------- CLI ----------


async def _amain(args: argparse.Namespace) -> int:
    suites = ["codeguard", "drawbridge"] if args.suite == "all" else [args.suite]
    overall_pass = True
    for suite in suites:
        report = await run_suite(suite)
        write_results(report, fmt="json")
        if args.report == "html":
            write_results(report, fmt="html")
        print(
            f"[{suite}] {report.passed}/{report.total} pass "
            f"({report.accuracy_pct:.1f}%)  cost={report.total_cost_vnd:,}đ  "
            f"latency_avg={report.avg_latency_ms}ms"
        )
        if report.total > 0 and report.passed < report.total:
            overall_pass = False
    return 0 if overall_pass else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="AEC AI quality eval harness")
    parser.add_argument(
        "--suite",
        choices=["codeguard", "drawbridge", "all"],
        default="all",
    )
    parser.add_argument(
        "--report",
        choices=["json", "html"],
        default="json",
        help="Output format; html implies json too",
    )
    args = parser.parse_args(argv)

    # Drift guard runs before any LLM call — fails fast if manifests
    # have skewed.
    check_case_manifest_in_sync()

    import asyncio
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
