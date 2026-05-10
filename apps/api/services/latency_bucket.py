"""Webhook delivery latency bucketizer (cycle XX2).

Given a latency in milliseconds, return a closed histogram
bucket label. Used by:

  * The Slack alert digest's "p95 latency last 24h" widget.
  * The dashboard latency histogram.
  * The audit metric rollup (composes with MM3 — pass
    `bucket_label(row.latency_ms)` as the rollup key_fn).

  bucket_label(latency_ms)  — bucket name string
  LATENCY_BUCKETS           — closed ordered tuple

Bucket ranges (ms, half-open `[lo, hi)`):
  * `<100ms`     — [0, 100)
  * `100-500ms`  — [100, 500)
  * `500ms-1s`   — [500, 1000)
  * `1-5s`       — [1000, 5000)
  * `5-30s`      — [5000, 30000)
  * `>=30s`      — [30000, ∞)
  * `timeout`    — None (no response received)
  * `unknown`    — negative (clock skew defense)

Pinned invariants:
  * Closed 8-bucket set — pin against silent expansion to
    finer-grained buckets that would invalidate dashboard
    historicals.
  * Boundaries match standard SRE histograms (P50/P95/P99
    land cleanly).
  * None → `"timeout"` (operationally meaningful).
  * Negative → `"unknown"` (clock skew, distinct from timeout).
  * Deterministic — same latency always same bucket.
  * Order in `LATENCY_BUCKETS` is the canonical display order
    (low to high latency).

Pure stdlib.
"""

from __future__ import annotations

# Closed bucket tuple in display order (fastest → slowest →
# operationally weird). Pin order so dashboards render bars
# in low-to-high latency order without re-sorting.
LATENCY_BUCKETS: tuple[str, ...] = (
    "<100ms",
    "100-500ms",
    "500ms-1s",
    "1-5s",
    "5-30s",
    ">=30s",
    "timeout",
    "unknown",
)


def bucket_label(latency_ms: int | float | None) -> str:
    """Return the histogram bucket label for `latency_ms`.

    None → `"timeout"`.
    Negative → `"unknown"` (clock skew).
    """
    if latency_ms is None:
        return "timeout"
    if latency_ms < 0:
        return "unknown"
    if latency_ms < 100:
        return "<100ms"
    if latency_ms < 500:
        return "100-500ms"
    if latency_ms < 1000:
        return "500ms-1s"
    if latency_ms < 5000:
        return "1-5s"
    if latency_ms < 30000:
        return "5-30s"
    return ">=30s"
