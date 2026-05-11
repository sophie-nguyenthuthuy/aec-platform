"""Audit metric rollup helper (cycle MM3).

Group-by aggregator for audit row counts. Today the admin
dashboard's "events this week" widget, the audit metric Slack
digest, and the org-level activity report each duplicate the
group-and-count logic inline. This module is the single source
of truth.

  rollup(rows, key_fn)   — RollupResult
  RollupResult           — frozen: (groups, total, distinct_keys)

Composes with Z2 (`audit_action_meta.module_of`): the caller
can pass `module_of` as the `key_fn` to roll up by module
without writing a closure.

Pinned invariants:
  * Output ordering: count DESC primary, key ASC for tie-break.
    Pin so callers can render "top N" lists without re-sorting.
  * Empty input → RollupResult((), 0, 0).
  * Rows where `key_fn` returns None are SKIPPED (not counted
    in `total` either).
  * Empty-string keys ARE counted (distinct from None).

Pure stdlib.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RollupResult:
    """Aggregated rollup output.

    `groups` is a tuple of (key, count) pairs sorted by count
    DESC (primary) then key ASC (tie-break) — pin so the caller
    can render directly without re-sorting.
    `total` is the sum of all counts (excludes None-keyed rows).
    `distinct_keys` is the number of unique keys.
    """

    groups: tuple[tuple[str, int], ...]
    total: int
    distinct_keys: int


def rollup(
    rows: Iterable[T],
    key_fn: Callable[[T], str | None],
) -> RollupResult:
    """Group `rows` by `key_fn(row)` and count occurrences.

    Returns a `RollupResult` with deterministic sort order:
    count DESC, then key ASC for ties.

    Rows where `key_fn` returns None are SKIPPED — they don't
    contribute to `total` or `distinct_keys`. Empty-string keys
    are counted (distinct from None).
    """
    counts: dict[str, int] = {}
    total = 0
    for row in rows:
        key = key_fn(row)
        if key is None:
            continue
        counts[key] = counts.get(key, 0) + 1
        total += 1

    # count DESC primary, key ASC tie-break.
    sorted_groups = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    return RollupResult(
        groups=tuple(sorted_groups),
        total=total,
        distinct_keys=len(counts),
    )
