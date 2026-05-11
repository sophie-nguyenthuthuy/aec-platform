"""Webhook delivery latency bucketizer (cycle XX2).

Pinned seams:
  1. LATENCY_BUCKETS = 8 entries in low-to-high order.
  2. None → "timeout".
  3. Negative → "unknown".
  4. Half-open bucket boundaries [lo, hi).
  5. Deterministic.
"""

from __future__ import annotations

from services.latency_bucket import LATENCY_BUCKETS, bucket_label

# ---------- Constants ----------


def test_buckets_canonical_order():
    """8-bucket closed set in low-to-high latency order."""
    assert LATENCY_BUCKETS == (
        "<100ms",
        "100-500ms",
        "500ms-1s",
        "1-5s",
        "5-30s",
        ">=30s",
        "timeout",
        "unknown",
    )


def test_buckets_count():
    assert len(LATENCY_BUCKETS) == 8


# ---------- None / negative ----------


def test_none_returns_timeout():
    """Cardinal pin: None means no response received → timeout
    (operationally meaningful, distinct from `unknown`)."""
    assert bucket_label(None) == "timeout"


def test_negative_returns_unknown():
    """Cardinal pin: negative latency means clock skew →
    `unknown` (distinct from `timeout` since the request
    DID complete, just with broken timing)."""
    assert bucket_label(-1) == "unknown"
    assert bucket_label(-1000) == "unknown"


# ---------- Boundaries ----------


def test_zero_is_under_100ms():
    assert bucket_label(0) == "<100ms"


def test_99_under_100ms():
    assert bucket_label(99) == "<100ms"


def test_99_99_under_100ms():
    """Float input — 99.99 still under 100."""
    assert bucket_label(99.99) == "<100ms"


def test_100_starts_next_bucket():
    """Cardinal pin: half-open boundary. 100 is NOT in
    `<100ms` — it starts the next bucket."""
    assert bucket_label(100) == "100-500ms"


def test_499_in_100_500ms():
    assert bucket_label(499) == "100-500ms"


def test_500_starts_next():
    assert bucket_label(500) == "500ms-1s"


def test_999_in_500ms_1s():
    assert bucket_label(999) == "500ms-1s"


def test_1000_starts_1_5s():
    assert bucket_label(1000) == "1-5s"


def test_4999_in_1_5s():
    assert bucket_label(4999) == "1-5s"


def test_5000_starts_5_30s():
    assert bucket_label(5000) == "5-30s"


def test_29999_in_5_30s():
    assert bucket_label(29999) == "5-30s"


def test_30000_starts_30s_plus():
    assert bucket_label(30000) == ">=30s"


def test_60000_in_30s_plus():
    assert bucket_label(60000) == ">=30s"


def test_huge_latency_in_30s_plus():
    """No upper bound — multi-minute latency still in `>=30s`."""
    assert bucket_label(1_000_000) == ">=30s"


# ---------- Determinism ----------


def test_same_input_same_bucket():
    for latency in [0, 50, 100, 500, 1000, 5000, 30000]:
        a = bucket_label(latency)
        b = bucket_label(latency)
        assert a == b


# ---------- Float input ----------


def test_float_latency_works():
    assert bucket_label(99.5) == "<100ms"
    assert bucket_label(100.5) == "100-500ms"


# ---------- All buckets returnable ----------


def test_all_buckets_reachable():
    """Pin: every bucket in LATENCY_BUCKETS is reachable from
    some input. Defends against an unreachable bucket sneaking
    into the registry."""
    inputs_to_buckets = {
        50: "<100ms",
        200: "100-500ms",
        700: "500ms-1s",
        2000: "1-5s",
        10000: "5-30s",
        60000: ">=30s",
        None: "timeout",
        -1: "unknown",
    }
    seen = set()
    for input_val, expected in inputs_to_buckets.items():
        result = bucket_label(input_val)
        assert result == expected
        seen.add(result)
    assert seen == set(LATENCY_BUCKETS)


# ---------- Composes with MM3 (rollup) ----------


def test_composes_with_mm3_rollup():
    """Realistic use: pass `bucket_label` as the key_fn to MM3
    `rollup` to get a latency histogram from a list of latency
    values."""
    from services.audit_rollup import rollup

    latencies = [50, 50, 200, 200, 200, 700, 1500, 1500, None, -1]
    result = rollup(latencies, bucket_label)
    # Buckets: <100ms=2, 100-500ms=3, 500ms-1s=1, 1-5s=2, timeout=1, unknown=1
    groups_dict = dict(result.groups)
    assert groups_dict["<100ms"] == 2
    assert groups_dict["100-500ms"] == 3
    assert groups_dict["500ms-1s"] == 1
    assert groups_dict["1-5s"] == 2
    assert groups_dict["timeout"] == 1
    assert groups_dict["unknown"] == 1
    assert result.total == 10
