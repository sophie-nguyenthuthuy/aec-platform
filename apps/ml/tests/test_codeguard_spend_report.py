"""Tests for `scripts/codeguard_spend_report.py`.

The rollup is the bridge between "telemetry going to stderr" and "ops
can answer cost questions" — its math has to be right or the resulting
dashboards will lie about spend. These tests pin the contract:
  * `parse_record` accepts well-formed telemetry records and rejects
    everything else (non-JSON, missing `call`, non-dict).
  * `rollup` aggregates by call name with correct token totals, error
    counts, latency percentiles, and the HyDE-cache-hit-rate
    derivation.
  * The output schema (the dict shape `--json` emits) is stable —
    downstream scripts depend on it.

These run as Tier 1 unit tests — no Postgres, no API keys, no network.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "codeguard_spend_report.py"


@pytest.fixture(scope="module")
def report_module():
    """Load the script as a module so we can call its functions directly.

    `scripts/` isn't on the Python path and the file ends in `.py` but
    has no package wrapping — `importlib.util` is the cleanest way to
    pull it in for testing without restructuring the repo.
    """
    spec = importlib.util.spec_from_file_location("codeguard_spend_report", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["codeguard_spend_report"] = module
    spec.loader.exec_module(module)
    return module


# ---------- parse_record --------------------------------------------------


def test_parse_record_accepts_telemetry_record(report_module):
    """Well-formed JSON dict with `call` field → parsed."""
    rec = report_module.parse_record(
        '{"call": "hyde_expand", "model": "claude", "latency_ms": 100, '
        '"input_tokens": 50, "output_tokens": 20, "status": "ok"}'
    )
    assert rec is not None
    assert rec["call"] == "hyde_expand"
    assert rec["input_tokens"] == 50


def test_parse_record_rejects_non_json(report_module):
    """Plain log lines from non-telemetry sources mixed in the stream
    must be silently skipped, not crash the rollup."""
    assert report_module.parse_record("INFO: server started on port 8000") is None
    assert report_module.parse_record("") is None
    assert report_module.parse_record("   ") is None


def test_parse_record_rejects_json_without_call_field(report_module):
    """Other JSON-shaped log records (request logs, app events) lack
    `call` — that's the discriminator for "this is a telemetry record."
    """
    assert report_module.parse_record('{"event": "request", "path": "/foo"}') is None
    assert report_module.parse_record('{"hello": "world"}') is None


def test_parse_record_rejects_non_dict_json(report_module):
    """A JSON array or scalar at the top level isn't a record; reject it."""
    assert report_module.parse_record('["call", "value"]') is None
    assert report_module.parse_record('"just a string"') is None
    assert report_module.parse_record("42") is None


# ---------- rollup totals + per-call -------------------------------------


def _record(**fields):
    """Build a telemetry record with only the fields the test cares about."""
    base = {
        "call": "qa_generate",
        "model": "claude-sonnet-4-6",
        "latency_ms": 100,
        "input_chars": 1000,
        "output_chars": 500,
        "input_tokens": 250,
        "output_tokens": 125,
        "status": "ok",
        "error": None,
    }
    base.update(fields)
    return base


def test_rollup_aggregates_token_totals_per_call(report_module):
    """Two records for the same call sum tokens; different calls stay
    in separate buckets."""
    records = [
        _record(call="hyde_expand", input_tokens=10, output_tokens=5),
        _record(call="hyde_expand", input_tokens=20, output_tokens=8),
        _record(call="qa_generate", input_tokens=100, output_tokens=50),
    ]
    data = report_module.rollup(records)

    by_call = {row["call"]: row for row in data["by_call"]}
    assert by_call["hyde_expand"]["count"] == 2
    assert by_call["hyde_expand"]["input_tokens"] == 30
    assert by_call["hyde_expand"]["output_tokens"] == 13
    assert by_call["qa_generate"]["count"] == 1
    assert by_call["qa_generate"]["input_tokens"] == 100


def test_rollup_counts_errors_separately_from_ok(report_module):
    """Error records still count toward the bucket but flip an `errors`
    counter — needed for "what's our LLM error rate" rollups."""
    records = [
        _record(call="qa_generate", status="ok"),
        _record(call="qa_generate", status="error", error="Anthropic 503"),
        _record(call="qa_generate", status="error", error="timeout"),
    ]
    data = report_module.rollup(records)

    assert data["totals"] == {"count": 3, "ok": 1, "error": 2}
    qa = next(r for r in data["by_call"] if r["call"] == "qa_generate")
    assert qa["count"] == 3
    assert qa["errors"] == 2


def test_rollup_handles_missing_token_fields_as_zero(report_module):
    """Older records (pre token-capture upgrade) might have None for
    `input_tokens`/`output_tokens`. Treat as 0 so the rollup doesn't
    crash on a mixed log stream that spans deployments."""
    records = [
        _record(call="hyde_expand", input_tokens=None, output_tokens=None),
        _record(call="hyde_expand", input_tokens=10, output_tokens=5),
    ]
    data = report_module.rollup(records)

    hyde = next(r for r in data["by_call"] if r["call"] == "hyde_expand")
    assert hyde["count"] == 2
    assert hyde["input_tokens"] == 10
    assert hyde["output_tokens"] == 5


def test_rollup_computes_p50_and_p95_latency(report_module):
    """Percentile shape is what dashboards typically alert on. Must be
    deterministic across runs (sort + nearest-rank)."""
    latencies = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    records = [_record(call="qa_generate", latency_ms=ms) for ms in latencies]
    data = report_module.rollup(records)

    qa = next(r for r in data["by_call"] if r["call"] == "qa_generate")
    # Nearest-rank median for 10 values: rank ≈ 0.5 * 9 = 4.5 → 4 or 5.
    assert qa["p50_ms"] in (500, 600)
    # p95 of 10 values: rank ≈ 0.95 * 9 ≈ 8.55 → index 9 → 1000.
    assert qa["p95_ms"] == 1000


def test_rollup_sorts_by_call_count_descending(report_module):
    """Highest-volume calls render first in the table — the rollup
    pre-sorts so the formatter doesn't need to re-sort."""
    records = (
        [_record(call="rare")] * 1 + [_record(call="medium")] * 5 + [_record(call="common")] * 10
    )
    data = report_module.rollup(records)

    call_order = [row["call"] for row in data["by_call"]]
    assert call_order == ["common", "medium", "rare"]


def test_rollup_collects_unique_models_per_call(report_module):
    """A call that hits multiple models (e.g. Anthropic version rollover
    in flight) surfaces both — useful for "did our model swap happen?"
    queries."""
    records = [
        _record(call="qa_generate", model="claude-sonnet-4-6"),
        _record(call="qa_generate", model="claude-sonnet-4-7"),
        _record(call="qa_generate", model="claude-sonnet-4-6"),
    ]
    data = report_module.rollup(records)

    qa = next(r for r in data["by_call"] if r["call"] == "qa_generate")
    assert qa["models"] == ["claude-sonnet-4-6", "claude-sonnet-4-7"]


# ---------- HyDE cache hit rate ------------------------------------------


def test_rollup_hyde_hit_rate_zero_when_every_qa_produces_an_expand(report_module):
    """1 hyde_expand per qa_generate → cache wasn't helping. Hit rate = 0."""
    records = [_record(call="hyde_expand")] * 10 + [_record(call="qa_generate")] * 10
    data = report_module.rollup(records)
    assert data["hyde_cache"]["estimated_hit_rate"] == 0.0


def test_rollup_hyde_hit_rate_high_when_few_expands_per_qa(report_module):
    """1 hyde_expand for 10 qa_generate → cache caught 9 of 10. Hit rate ≈ 0.9."""
    records = [_record(call="hyde_expand")] * 1 + [_record(call="qa_generate")] * 10
    data = report_module.rollup(records)
    assert data["hyde_cache"]["estimated_hit_rate"] == pytest.approx(0.9)


def test_rollup_hyde_hit_rate_none_with_no_qa_traffic(report_module):
    """Can't compute a hit rate without a denominator. None signals
    "unknown" rather than misleadingly returning 0 or 1."""
    records = [_record(call="hyde_expand")] * 5
    data = report_module.rollup(records)
    assert data["hyde_cache"]["estimated_hit_rate"] is None


def test_rollup_hyde_hit_rate_includes_streaming_qa(report_module):
    """`qa_generate_stream` is the streaming variant of `qa_generate` —
    both go through `_hyde_expand` so both count toward the denominator.
    Pin this so a future refactor that splits the streaming path doesn't
    accidentally undercount cache hit rate."""
    records = (
        [_record(call="hyde_expand")] * 2
        + [_record(call="qa_generate")] * 5
        + [_record(call="qa_generate_stream")] * 5
    )
    data = report_module.rollup(records)
    # 2 hyde_expand for 10 total Q&A calls → hit rate 0.8.
    assert data["hyde_cache"]["estimated_hit_rate"] == pytest.approx(0.8)


# ---------- Output formatting --------------------------------------------


def test_format_report_handles_empty_input(report_module):
    """Empty stream → friendly message, not a stack trace or blank
    output. Operators sometimes pipe the wrong file into the script."""
    data = report_module.rollup([])
    text = report_module.format_report(data)
    assert "No CODEGUARD telemetry records" in text


def test_format_report_renders_call_table(report_module):
    """Sanity check that the table headers + a representative row both
    surface in the formatted text."""
    records = [
        _record(call="hyde_expand", input_tokens=100, output_tokens=50),
        _record(call="qa_generate", input_tokens=200, output_tokens=100),
    ]
    data = report_module.rollup(records)
    text = report_module.format_report(data)
    assert "call" in text
    assert "in_tok" in text
    assert "p50_ms" in text
    assert "hyde_expand" in text
    assert "qa_generate" in text
