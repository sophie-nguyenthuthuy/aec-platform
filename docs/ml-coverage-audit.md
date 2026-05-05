# `apps/ml` coverage audit

Baseline as of 2026-05-02 — run `make test-ml-cov` to refresh.

## Summary

```
TOTAL  4959 statements, 2328 missed → 53% line coverage
```

22 test files, ~140 passing tests. The codeguard side is solid (pipeline + retrieval + telemetry + abstain logic all 90%+). The gaps are concentrated in two source modules + the integration tests that skip without a live DB.

## Source modules — coverage delta from the audit

| Module | Lines | Before audit | After audit | Status |
| --- | --- | --- | --- | --- |
| `apps/ml/pipelines/winwork.py` | 176 | **0%** | **45%** | ✅ pure helpers tested in [`test_winwork_pipeline_pure.py`](../apps/ml/tests/test_winwork_pipeline_pure.py); LLM-driven nodes still uncovered |
| `apps/ml/server.py` | 56 | **0%** | **0%** | ⚠️ Ray Serve entrypoint — see "Why server.py stays uncovered" below |

## What's still uncovered in `winwork.py` (the 55%)

Async LangGraph nodes that wrap LLM + DB calls:

- `_node_benchmark_lookup` — DB lookup against `cost_benchmarks`. Test would need `AdminSessionFactory` mock + canned rows.
- `_node_precedents` — vector retrieval against `proposal_chunks` (pgvector). Needs the LangChain HyDE pipeline mocked.
- `_node_scope_expansion` — Anthropic call. Mock the LLM + assert the scope-of-work shape.
- `_node_proposal_draft` — Anthropic call for cover letter. Mock + assert title/notes shape.
- `_node_fee_calculation` — pure math but reads `_construction_cost_per_sqm` (covered) + benchmark state. Worth a focused test.
- `_build_graph` / `run_proposal_pipeline` — LangGraph orchestration. Best exercised end-to-end with all four nodes mocked.

The pure helpers (`_construction_cost_per_sqm`, `_node_confidence`, `_extract_json`) are now fully covered. Each LLM-driven node would be ~3 tests in the same `monkeypatch _llm` pattern as the existing codeguard pipeline tests — total ~15 tests to lift `winwork.py` coverage from 45% → ~85%.

## Why `server.py` stays uncovered

`apps/ml/server.py` is the Ray Serve entrypoint that loads the YOLOv8 SiteEye safety model and exposes the FastAPI shim. Coverage requires either:

1. Running Ray Serve locally + the YOLOv8 model weights — too heavy for the unit lane.
2. Mocking the entire Ray Serve framework — high effort, low signal.

The Playwright lane covers this through real photo-analysis flow when the integration stack is up. Mark this as **intentionally untested at unit level** and rely on integration coverage. If the file's logic gets more complex than entrypoint+route wiring, the cost-benefit shifts.

## What to do next

1. **Cover the four LLM-driven `_node_*` functions in `winwork.py`** with mocked Anthropic. Each is 3-4 tests of "right system prompt + right output shape." Estimated: ~45 minutes for ~15 tests, lifts the whole apps/ml line coverage from 53% → ~58%.
2. **Add `--cov-fail-under=53` to a future `make test-ml-cov` invocation** in CI once the floor is stable. (Not done today — like apps/api's gate, only worth pinning after 2-3 rounds of "doesn't drop on its own.")
3. **Don't try to cover `server.py`** — defer to integration / Playwright.

## Already-covered modules (≥90%)

For reference — these are healthy and shouldn't need attention:

- `apps/ml/pipelines/codeguard.py` (the LangGraph query+scan pipelines)
- `apps/ml/pipelines/codeguard_chunking.py`
- `apps/ml/pipelines/codeguard_streaming.py`
- `apps/ml/pipelines/dailylog_patterns.py`
- `apps/ml/pipelines/pulse_client_report.py`
- `apps/ml/pipelines/siteeye.py` (dailylog sync)

The 9 files reported as "skipped due to complete coverage" by pytest-cov fall in this group.
