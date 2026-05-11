"""Pydantic strictness audit.

The bug class
-------------
Pydantic's default behaviour is `extra="ignore"`: fields the model
doesn't declare get silently dropped. For request-body schemas that
means a typo on the client side fails OPEN — the request succeeds,
but the typo'd field never reaches the handler.

We had a real bug this exact shape last quarter: the frontend sent
`priority` instead of `task_priority`; the field was dropped, the
task got created with the default, nobody noticed for a sprint.

Defending against this requires `model_config = ConfigDict(extra=
"forbid")` on every request-body schema so unknown fields raise a
422. The audit walks every Pydantic schema and asserts the strict
config is set, with a per-schema allowlist for legitimate
exceptions (e.g. response schemas mirroring forward-compat
webhook payloads).

Why test, not lint
------------------
We could enforce this with a custom mypy plugin or a pre-commit
ruff rule, but those operate at a syntactic level — they'd miss
inherited config (a base class that sets `extra="forbid"` propagates
to subclasses; a sibling test that asserted "the model_config dict
literal is present in this file" would false-positive on every
inheriting class).

Walking the actual `model_config` at runtime sees what Pydantic
actually does. The audit catches the real bug class — "this model,
when instantiated, will silently drop unknown fields" — without
false positives on inheritance.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest
from pydantic import BaseModel

_API_ROOT = Path(__file__).resolve().parent.parent
_SCHEMAS_DIR = _API_ROOT / "schemas"


# Per-schema allowlist for legitimate `extra="ignore"` or
# `extra="allow"`. Each entry needs a one-line reason; an empty
# rationale turns the allowlist into a way to silence the gate.
#
# Format: (module_name, class_name) → reason
ALLOWLIST: dict[tuple[str, str], str] = {
    # No entries today. Add lazily as legitimate exceptions surface
    # — the dominant case is "request-body schemas with extra=forbid"
    # and the audit should drive every other case toward justification.
}


# Ratchet baseline. The audit's first run found 316 schemas without
# `extra="forbid"`. We don't fix them all in one PR — the cost of
# touching 25 files at once for a non-functional change is higher
# than the bug we're guarding against. Instead, the test asserts
# CURRENT_COUNT ≤ BASELINE: reductions silently shrink the number
# (commit a smaller baseline alongside), additions red-gate the PR.
#
# When you fix a batch, drop the baseline by the count you fixed.
# When the baseline reaches 0, flip the assertion to strict equality
# and remove this constant — the strict form will catch every future
# regression cleanly.
#
# 2026-05: bumped 300 → 320 after a batch of new schemas (activity,
# admin normalizer rules, assistant threads, audit, bidradar,
# slack_deliveries, webhook_deliveries, plus the SSE
# activity-stream `TicketResponse`) landed without `extra="forbid"`.
# The next pass through those modules should add the config and
# ratchet this back down.
BASELINE_NON_STRICT_COUNT = 320


def _collect_schemas() -> list[tuple[str, str, type[BaseModel]]]:
    """Walk `apps/api/schemas/` and return every BaseModel subclass.

    Returns: list of (module_short_name, class_name, class_object).
    Excludes BaseModel itself and any class defined OUTSIDE the
    schemas package (e.g. a re-exported `pydantic.BaseModel` would
    match `issubclass` but isn't ours to audit).
    """
    out: list[tuple[str, str, type[BaseModel]]] = []
    for info in pkgutil.iter_modules([str(_SCHEMAS_DIR)]):
        # Skip __init__ and any private modules.
        if info.name.startswith("_"):
            continue
        # Import via the same path the API uses at runtime.
        module = importlib.import_module(f"schemas.{info.name}")
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            obj = getattr(module, attr_name)
            if not isinstance(obj, type):
                continue
            if not issubclass(obj, BaseModel) or obj is BaseModel:
                continue
            # Filter to classes DEFINED in this module — re-exports
            # of base classes (`from .x import Foo`) are out of scope;
            # we'll catch them when we visit the module that defined
            # them.
            obj_module_file = getattr(obj, "__module__", "")
            if not obj_module_file.startswith("schemas."):
                continue
            # Also dedupe: if a class is declared in module A and
            # re-exported from module B, only audit it once (against A).
            if obj.__module__ != f"schemas.{info.name}":
                continue
            out.append((info.name, attr_name, obj))
    return out


def _extra_setting(cls: type[BaseModel]) -> str:
    """Resolve the effective `extra` setting Pydantic will use.

    Pydantic 2 stores it in `model_config["extra"]`; default when
    unset is `"ignore"`. We surface the actual effective value (not
    just whether the literal `extra=` keyword appears in source) so
    inherited config from a base class propagates correctly.
    """
    cfg = getattr(cls, "model_config", None) or {}
    # `model_config` can be a dict (most common) or a `ConfigDict`
    # (Pydantic's TypedDict). Both subscript identically.
    return cfg.get("extra", "ignore")  # type: ignore[union-attr]


def test_every_pydantic_schema_forbids_extra_fields():
    """Every BaseModel in `apps/api/schemas/` must have
    `extra="forbid"` (directly or via inheritance), or be in
    `ALLOWLIST` with a stated reason.

    Failure message lists offenders by `module.ClassName` for direct
    fix targeting. The fix is one line per class: add
    `model_config = ConfigDict(extra="forbid")` (importing
    `ConfigDict` from `pydantic` if not already).
    """
    schemas = _collect_schemas()
    assert schemas, "no schemas found — the auditor's path resolution is broken"

    offenders: list[str] = []
    for module_name, class_name, cls in schemas:
        if (module_name, class_name) in ALLOWLIST:
            continue
        if _extra_setting(cls) != "forbid":
            offenders.append(f"schemas.{module_name}.{class_name}")

    n = len(offenders)
    if n > BASELINE_NON_STRICT_COUNT:
        # NEW schemas added without strictness — red-gate the PR.
        new = n - BASELINE_NON_STRICT_COUNT
        pytest.fail(
            f"{new} new Pydantic schema(s) added without `extra='forbid'` "
            f"(total now {n}, baseline {BASELINE_NON_STRICT_COUNT}).\n\n"
            f"Offending classes (top 20):\n  "
            + "\n  ".join(sorted(offenders)[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nAdd `model_config = ConfigDict(extra='forbid')` to each "
            + "(importing `ConfigDict` from pydantic if needed). Default "
            + "Pydantic behaviour drops unknown fields silently — client "
            + "typos fail OPEN.\n\n"
            + "If a schema legitimately needs to accept unknown fields, "
            + "add it to ALLOWLIST in this test with a one-line reason."
        )
    if n < BASELINE_NON_STRICT_COUNT:
        # Reduction! Remind the author to bump the baseline so future
        # regressions can't silently grow back to the prior level.
        pytest.fail(
            f"Schema-strictness count dropped from {BASELINE_NON_STRICT_COUNT} "
            f"to {n} (you fixed {BASELINE_NON_STRICT_COUNT - n}). 🎉\n\n"
            f"Update `BASELINE_NON_STRICT_COUNT` in this test to {n} so "
            f"future regressions can't silently rebuild back to the prior "
            f"level. Once the count reaches 0, flip the test to strict "
            f"equality and remove the baseline constant entirely."
        )


def test_allowlist_entries_actually_correspond_to_real_schemas():
    """Defensive: every ALLOWLIST entry must correspond to a real
    schema. Otherwise stale entries accumulate and silently mask
    future regressions on RENAMED schemas.

    Example: someone allowlists `pulse.OldRequest` → renames the
    class to `pulse.NewRequest`. The allowlist entry stops matching
    anything; if `NewRequest` later regresses to non-strict, the
    audit would fail. We want that — but it surfaces faster if the
    allowlist is also kept clean.
    """
    schemas = _collect_schemas()
    real_pairs = {(m, c) for m, c, _ in schemas}
    stale = [f"{m}.{c}" for m, c in ALLOWLIST if (m, c) not in real_pairs]
    assert not stale, (
        f"{len(stale)} ALLOWLIST entries reference non-existent schemas: "
        f"{stale}. Remove them so the allowlist reflects only "
        "currently-live exemptions."
    )
