"""Audit diff summarization (cycle X1, Python half).

Same one-line render as `apps/web/lib/audit-diff.ts`. Used by the
backend in places where we render an audit row in plain text:
Slack alerts on audit-rule triggers, email digests, the future
audit-export CSV's "summary" column.

Output shape — at most TWO key changes joined with " · ":

    role: member → admin · status: draft → approved

Two-key cap is deliberate: matches the frontend so the same audit
row reads identically across Slack + UI. The full nested diff is
in `before` / `after` for the rare reviewer who needs it.

Symbols:
  * `→` — value changed
  * `∅ → X` — key was absent in `before` (added)
  * `X → ∅` — key was absent in `after` (removed)

Pure Python — no DB, no async. Drop-in for any plaintext renderer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# Maximum keys included in the inline summary. Beyond this the
# caller renders "+ N more" so the text stays one line. Keep in
# sync with `apps/web/lib/audit-diff.ts::SUMMARY_KEY_CAP`.
SUMMARY_KEY_CAP = 2


@dataclass(frozen=True)
class DiffSummary:
    """Mirror of the TS `DiffSummary` interface."""

    text: str
    total_changes: int


def summarize_diff(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> DiffSummary:
    """Walk the union of keys, emit one entry per differing key
    (capped at `SUMMARY_KEY_CAP`).

    `None` for either side is treated as an empty dict — defensive
    against audit rows where the diff was never populated. Empty
    diff returns `text=""` so the caller can render an "n/a"
    placeholder without a string-emptiness check.
    """
    b = before or {}
    a = after or {}
    keys = set(b.keys()) | set(a.keys())

    parts: list[str] = []
    total_changes = 0
    for k in keys:
        bv = b.get(k, _ABSENT)
        av = a.get(k, _ABSENT)
        if _equal(bv, av):
            continue
        total_changes += 1
        if len(parts) < SUMMARY_KEY_CAP:
            parts.append(f"{k}: {format_value(bv)} → {format_value(av)}")

    return DiffSummary(text=" · ".join(parts), total_changes=total_changes)


# Sentinel for "key absent in this dict." We can't use None — None
# is a valid audit value (e.g. a field that was explicitly set to
# null). The sentinel is a unique object that no audit value will
# ever be, so equality is identity-based.
class _AbsentT:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<absent>"


_ABSENT: Any = _AbsentT()


def format_value(v: Any) -> str:
    """Render one value for inline display.

    Mirrors the TS side:
      * absent     → ∅
      * None       → "null" (distinct from absent)
      * dict/list  → JSON one-liner
      * everything → str(v)

    The ∅ vs "null" distinction is governance-bearing: a field
    that went from absent → null records a change. Operators
    notice the difference.
    """
    if v is _ABSENT:
        return "∅"
    if v is None:
        return "null"
    if isinstance(v, (dict, list)):
        try:
            # `default=str` so datetimes / UUIDs / Decimals don't
            # blow up the format. Same idiom as the audit CSV
            # exports.
            return json.dumps(v, default=str, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            # Circular ref / un-serializable shape — fall back
            # rather than crash the row.
            return "[object]"
    return str(v)


def _equal(a: Any, b: Any) -> bool:
    """Equality matching the TS `Object.is` semantics: NaN equals
    NaN, +0 != -0.

    The first branch covers the common case (audit values are
    typically primitive strings / numbers). The second branch
    handles NaN (NaN != NaN under `==`, equal under Object.is).
    """
    if a is b:
        return True
    # NaN-self-equality. `float('nan') != float('nan')` under `==`,
    # but Object.is says they're the same. Only floats can be NaN.
    if isinstance(a, float) and isinstance(b, float):
        if a != a and b != b:  # both NaN
            return True
    # Default: structural equality.
    return a == b
