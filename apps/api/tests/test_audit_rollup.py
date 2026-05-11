"""Audit metric rollup helper (cycle MM3).

Pinned seams:
  1. Output sorted: count DESC primary, key ASC tie-break.
  2. Empty input → RollupResult((), 0, 0).
  3. None keys SKIPPED (not counted in total).
  4. Empty-string keys ARE counted (distinct from None).
  5. Composes with Z2 module_of.
"""

from __future__ import annotations

from services.audit_action_meta import module_of
from services.audit_rollup import RollupResult, rollup

# ---------- Empty ----------


def test_empty_input():
    result = rollup([], lambda x: x)
    assert result == RollupResult(groups=(), total=0, distinct_keys=0)


# ---------- Basic counting ----------


def test_simple_counts():
    result = rollup(["a", "b", "a", "c", "a"], lambda x: x)
    assert result.total == 5
    assert result.distinct_keys == 3
    assert result.groups == (
        ("a", 3),
        ("b", 1),
        ("c", 1),
    )


def test_single_value():
    result = rollup(["only"], lambda x: x)
    assert result.groups == (("only", 1),)
    assert result.total == 1
    assert result.distinct_keys == 1


# ---------- Sort order ----------


def test_count_desc_is_primary():
    """Higher count first."""
    result = rollup(["b", "b", "b", "a", "c"], lambda x: x)
    assert result.groups == (
        ("b", 3),
        ("a", 1),
        ("c", 1),
    )


def test_key_asc_tie_breaks():
    """Cardinal pin: tied counts sort by key ASCENDING.
    Pin so a refactor to descending tie-break surfaces here —
    the dashboard renders "top N" expecting alphabetical
    tie-break to feel stable."""
    result = rollup(["c", "a", "b"], lambda x: x)
    assert result.groups == (("a", 1), ("b", 1), ("c", 1))


def test_combined_count_desc_key_asc():
    rows = ["a", "a", "b", "c", "c", "d", "e", "e"]
    # Counts: a=2, b=1, c=2, d=1, e=2
    # Sort: count DESC (2s first), key ASC: a, c, e (count 2); b, d (count 1)
    result = rollup(rows, lambda x: x)
    assert result.groups == (
        ("a", 2),
        ("c", 2),
        ("e", 2),
        ("b", 1),
        ("d", 1),
    )


# ---------- None handling ----------


def test_none_keys_skipped():
    """Pin: rows where key_fn returns None are skipped — not
    counted in total or distinct_keys."""
    result = rollup([1, 2, 3, 4, 5], lambda x: str(x) if x % 2 == 0 else None)
    assert result.total == 2  # only 2 and 4
    assert result.distinct_keys == 2
    assert result.groups == (("2", 1), ("4", 1))


def test_all_none_returns_empty_result():
    result = rollup([1, 2, 3], lambda x: None)
    assert result == RollupResult(groups=(), total=0, distinct_keys=0)


def test_empty_string_keys_are_counted():
    """Pin: empty string keys are DISTINCT from None — they are
    counted in the rollup. Defends against a refactor that
    treats falsy as None."""
    result = rollup(["", "", "a"], lambda x: x)
    assert result.total == 3
    assert result.distinct_keys == 2
    # Empty string sorts before "a" alphabetically.
    assert result.groups == (
        ("", 2),
        ("a", 1),
    )


# ---------- Custom key function ----------


def test_key_fn_extraction():
    """Real-world shape: rows are dicts, key_fn extracts a field."""
    rows = [
        {"action": "create", "actor": "alice"},
        {"action": "create", "actor": "bob"},
        {"action": "delete", "actor": "alice"},
    ]
    result = rollup(rows, lambda r: r["actor"])
    assert result.groups == (("alice", 2), ("bob", 1))


# ---------- Iterable input ----------


def test_accepts_generator_input():
    """Pin Iterable parameter — supports generators/lazy
    iteration."""

    def gen():
        yield "a"
        yield "b"
        yield "a"

    result = rollup(gen(), lambda x: x)
    assert result.groups == (("a", 2), ("b", 1))


# ---------- Cross-cycle composition (Z2) ----------


def test_composes_with_z2_module_of():
    """Cardinal cross-cycle pin: composes with Z2's module_of
    to roll up audit actions by module — exercises the
    cross-cycle composition without mocks."""
    actions = [
        "pulse.change_order.approve",
        "pulse.change_order.reject",
        "punchlist.list.create",
        "admin.cron.run_now",
        "pulse.change_order.create",
    ]
    result = rollup(actions, module_of)
    # Module counts: pulse=3, admin=1, punchlist=1
    # Sort: count DESC (pulse first), then key ASC for ties (admin, punchlist).
    assert result.groups == (
        ("pulse", 3),
        ("admin", 1),
        ("punchlist", 1),
    )
    assert result.total == 5
    assert result.distinct_keys == 3


# ---------- Frozen ----------


def test_rollup_result_is_frozen():
    r = RollupResult(groups=(), total=0, distinct_keys=0)
    try:
        r.total = 10  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("RollupResult should be frozen")
