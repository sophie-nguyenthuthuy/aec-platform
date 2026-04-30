#!/usr/bin/env python3
"""Roll up CODEGUARD telemetry log lines into a per-call spend report.

Reads JSON-formatted log records from stdin (one record per line) and
prints a per-call rollup of token spend, latency percentiles, error
counts, and HyDE cache effectiveness. Designed for the "I just need a
first dashboard" case where you've got telemetry going to stderr but
no Loki/Honeycomb backend yet.

Typical use:

    # Pull a pod's logs, filter to telemetry, run the rollup.
    kubectl logs deploy/aec-api -c api --since=1h \\
      | python scripts/codeguard_spend_report.py

    # Or against a captured log file:
    python scripts/codeguard_spend_report.py < /var/log/aec-api.jsonl

    # Machine-readable output for scripting:
    python scripts/codeguard_spend_report.py --json < logs.jsonl

Lines that aren't JSON or that don't have a `call` field are skipped
silently — so the script is safe to point at a mixed log stream
without pre-filtering. To make Python's structured logger emit JSON,
install `python-json-logger` and configure the `codeguard.telemetry`
logger with a `JsonFormatter` (see docs/codeguard-telemetry.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable
from typing import Any


def parse_record(line: str) -> dict | None:
    """Parse one log line into a telemetry record, or None if not one.

    A "telemetry record" is any JSON object with a `call` field — that's
    the dimension the rollup pivots on. We don't filter on logger name
    because different log shippers attach the logger in different fields
    (`logger`, `name`, `logger_name`, sometimes nothing).
    """
    line = line.strip()
    if not line:
        return None
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(rec, dict):
        return None
    if "call" not in rec:
        return None
    return rec


def _percentile(values: list[int], p: float) -> int:
    """Lightweight percentile without numpy. Returns 0 for empty input."""
    if not values:
        return 0
    s = sorted(values)
    if p <= 0:
        return s[0]
    if p >= 100:
        return s[-1]
    # Nearest-rank method — close enough for ops dashboards.
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def rollup(records: Iterable[dict]) -> dict[str, Any]:
    """Aggregate a stream of telemetry records into a rollup dict.

    Output shape (stable — `--json` consumers depend on this):

        {
            "totals": {"count": int, "ok": int, "error": int},
            "by_call": [
                {
                    "call": str, "count": int, "errors": int,
                    "input_tokens": int, "output_tokens": int,
                    "input_chars": int, "output_chars": int,
                    "p50_ms": int, "p95_ms": int,
                    "models": list[str],
                },
                ...  # sorted by `count` descending
            ],
            "hyde_cache": {
                "hyde_calls": int,
                "qa_calls": int,
                "estimated_hit_rate": float | None,
            },
        }

    `estimated_hit_rate` is a derived signal: cache hits emit NO
    telemetry record (by design — see `_hyde_expand` in
    `apps/ml/pipelines/codeguard.py`). So if N Q&A calls happened and
    M of them produced a hyde_expand record, the hit rate is roughly
    `1 - M/N`. None when N is zero (no Q&A traffic to compare against).
    """
    by_call: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "errors": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "input_chars": 0,
            "output_chars": 0,
            "latencies": [],
            "models": set(),
        }
    )
    total_ok = 0
    total_error = 0

    for rec in records:
        call = rec.get("call", "<unknown>")
        bucket = by_call[call]
        bucket["count"] += 1
        if rec.get("status") == "error":
            bucket["errors"] += 1
            total_error += 1
        else:
            total_ok += 1
        # `or 0` collapses both None and missing fields — keeps the
        # rollup robust against records that haven't been backfilled
        # with token counts yet (e.g. older deployments before the
        # token-capture upgrade landed).
        bucket["input_tokens"] += rec.get("input_tokens") or 0
        bucket["output_tokens"] += rec.get("output_tokens") or 0
        bucket["input_chars"] += rec.get("input_chars") or 0
        bucket["output_chars"] += rec.get("output_chars") or 0
        latency = rec.get("latency_ms")
        if isinstance(latency, (int, float)):
            bucket["latencies"].append(int(latency))
        model = rec.get("model")
        if isinstance(model, str):
            bucket["models"].add(model)

    by_call_sorted: list[dict[str, Any]] = []
    for call, bucket in sorted(by_call.items(), key=lambda kv: -kv[1]["count"]):
        latencies = bucket["latencies"]
        by_call_sorted.append(
            {
                "call": call,
                "count": bucket["count"],
                "errors": bucket["errors"],
                "input_tokens": bucket["input_tokens"],
                "output_tokens": bucket["output_tokens"],
                "input_chars": bucket["input_chars"],
                "output_chars": bucket["output_chars"],
                "p50_ms": _percentile(latencies, 50),
                "p95_ms": _percentile(latencies, 95),
                "models": sorted(bucket["models"]),
            }
        )

    # HyDE cache effectiveness: hyde_expand record count vs Q&A call
    # counts (both streaming + non-streaming). A working cache leaves
    # most Q&A calls without a corresponding hyde_expand record.
    hyde_calls = by_call.get("hyde_expand", {}).get("count", 0)
    qa_calls = by_call.get("qa_generate", {}).get("count", 0) + by_call.get(
        "qa_generate_stream", {}
    ).get("count", 0)
    hit_rate: float | None = None
    if qa_calls > 0:
        # Floor at 0 because hyde count > qa count happens if HyDE was
        # invoked outside Q&A (it isn't today, but pin the contract).
        hit_rate = max(0.0, 1.0 - (hyde_calls / qa_calls))

    return {
        "totals": {
            "count": total_ok + total_error,
            "ok": total_ok,
            "error": total_error,
        },
        "by_call": by_call_sorted,
        "hyde_cache": {
            "hyde_calls": hyde_calls,
            "qa_calls": qa_calls,
            "estimated_hit_rate": hit_rate,
        },
    }


def format_report(data: dict[str, Any]) -> str:
    """Pretty-print the rollup as a human-readable table."""
    lines: list[str] = []
    totals = data["totals"]
    if totals["count"] == 0:
        return "No CODEGUARD telemetry records found in input.\n"

    err_pct = (totals["error"] / totals["count"]) * 100 if totals["count"] else 0
    lines.append(f"CODEGUARD telemetry rollup — {totals['count']} call(s)")
    lines.append(f"  ok:     {totals['ok']:>7,}")
    lines.append(f"  error:  {totals['error']:>7,}  ({err_pct:.1f}%)")
    lines.append("")

    # Per-call table. Width-tuned for typical call names; long names
    # get truncated to 35 chars to keep the rest aligned.
    header = (
        f"{'call':<36} {'n':>6} {'err':>4} {'in_tok':>10} {'out_tok':>10} "
        f"{'p50_ms':>7} {'p95_ms':>7}  models"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for row in data["by_call"]:
        name = row["call"]
        if len(name) > 35:
            name = name[:32] + "..."
        models = ",".join(row["models"]) or "-"
        lines.append(
            f"{name:<36} {row['count']:>6} {row['errors']:>4} "
            f"{row['input_tokens']:>10,} {row['output_tokens']:>10,} "
            f"{row['p50_ms']:>7} {row['p95_ms']:>7}  {models}"
        )
    lines.append("")

    cache = data["hyde_cache"]
    if cache["qa_calls"] > 0:
        rate = cache["estimated_hit_rate"]
        rate_str = f"{rate * 100:.1f}%" if rate is not None else "n/a"
        lines.append(
            f"HyDE cache: {cache['hyde_calls']} expand call(s) for "
            f"{cache['qa_calls']} Q&A request(s) → estimated hit rate {rate_str}"
        )
        lines.append(
            "  (cache hits emit no telemetry record; "
            "low hyde_calls relative to qa_calls = effective cache)"
        )
    else:
        lines.append("HyDE cache: no Q&A traffic in input — hit rate unknown.")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Roll up CODEGUARD telemetry log records from stdin.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a formatted table.",
    )
    args = parser.parse_args()

    records = (rec for rec in (parse_record(line) for line in sys.stdin) if rec)
    data = rollup(records)

    if args.json:
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_report(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
