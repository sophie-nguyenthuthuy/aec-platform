"""`Optional` field without `= None` default audit (Pydantic).

The bug class
-------------
A Pydantic field annotated `Optional[X]` (or `X | None`) but
without `= None` default is REQUIRED at construction time.
Pydantic accepts None as a valid value once present, but the
field itself must be supplied:

    class Foo(BaseModel):
        bar: str | None  # required! must pass `bar=None` or a str

The author almost certainly meant one of:
  * "this field is truly optional from the caller" → add
    `= None` default.
  * "this field is required but the value can be None" → drop
    the `| None` and use a separate sentinel, or document
    explicitly.

The current shape leaves the contract ambiguous: callers omitting
`bar` get a `ValidationError`, but the field's TYPE says None is
allowed. New developers waste time figuring out why the validator
fires on the missing-arg case.

The fix is one annotation change:

    bar: str | None = None    # truly optional
    # or:
    bar: str                  # required, can't be None

Sister of `test_pydantic_strictness_audit.py` (which pins
`extra="forbid"` on the model config) and
`test_pydantic_field_constraint_audit.py` (which pins
`min_length` / `ge` on individual fields).

What this audit checks
----------------------
Walk every Pydantic schema in `apps/api/schemas/*.py`. For each
field whose annotation includes `None` (i.e. `Optional[X]`,
`X | None`, `Union[X, None]`), assert the field has an explicit
default — either `= None`, `= some_value`, or `Field(default=...)`.

What's NOT checked
------------------
- `Optional` types in non-Pydantic classes (regular dataclasses,
  TypedDicts) — out of scope.
- Fields where the type is `None` itself (degenerate).

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_SCHEMAS_DIR = _API_ROOT / "schemas"


# Today's baseline. Filled in on first run.
BASELINE_OPTIONAL_NO_DEFAULT = 30  # 2026-05: first-run baseline; ratchet down by adding `= None` defaults or dropping `| None`


# Per-(module, class, field) allowlist. Each entry needs a stated
# reason. An empty rationale silences the gate.
ALLOWLIST: dict[tuple[str, str, str], str] = {
    # No entries today.
}


def _collect_schemas() -> list[tuple[str, str, type]]:
    from pydantic import BaseModel

    out: list[tuple[str, str, type]] = []
    for info in pkgutil.iter_modules([str(_SCHEMAS_DIR)]):
        if info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"schemas.{info.name}")
        except ImportError:
            continue
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            obj = getattr(module, attr_name)
            if not isinstance(obj, type):
                continue
            if not issubclass(obj, BaseModel) or obj is BaseModel:
                continue
            if obj.__module__ != f"schemas.{info.name}":
                continue
            out.append((info.name, attr_name, obj))
    return out


def _annotation_allows_none(annotation) -> bool:
    """True if the annotation is `Optional[X]`, `X | None`, or
    `Union[X, None]` (or contains None as one of the union arms).
    """
    import types
    from typing import get_args, get_origin

    origin = get_origin(annotation)
    if origin is types.UnionType or (origin is not None and str(origin).endswith("Union")):
        return any(arg is type(None) for arg in get_args(annotation))
    return annotation is type(None)


def _audit_schema(cls) -> list[str]:
    """Return list of `module.Class.field` strings for offenders."""
    from pydantic_core import PydanticUndefined

    out: list[str] = []
    module_name = cls.__module__.replace("schemas.", "")
    for field_name, field_info in cls.model_fields.items():
        ann = field_info.annotation
        if not _annotation_allows_none(ann):
            continue
        # `is_required()` returns True when there's NO default.
        # That's the bug shape we're flagging.
        if not field_info.is_required():
            continue
        if field_info.default is not PydanticUndefined:
            # Has an explicit default that isn't the "no default"
            # sentinel — counts as defaulted.
            continue
        key = (module_name, cls.__name__, field_name)
        if key in ALLOWLIST:
            continue
        out.append(f"schemas.{module_name}.{cls.__name__}.{field_name}")
    return out


def test_every_optional_pydantic_field_has_a_none_default():
    """Every Pydantic field annotated `Optional[X]` / `X | None`
    should have a default — typically `= None`. The bare form is
    REQUIRED-but-nullable, which almost no caller expects.
    """
    schemas = _collect_schemas()
    assert schemas, "no schemas found — the auditor's path resolution is broken"

    findings: list[str] = []
    for _, _, cls in schemas:
        findings.extend(_audit_schema(cls))

    n = len(findings)
    if n > BASELINE_OPTIONAL_NO_DEFAULT:
        new = n - BASELINE_OPTIONAL_NO_DEFAULT
        pytest.fail(
            f"{new} new Optional-but-required field(s) "
            f"(total now {n}, baseline {BASELINE_OPTIONAL_NO_DEFAULT}):\n  "
            + "\n  ".join(sorted(findings)[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nFix one of two ways:\n"
            "    # truly optional — caller can omit:\n"
            "    bar: str | None = None\n"
            "    # required but nullable (rare, document why):\n"
            "    bar: str | None = Field(..., description='caller MUST pass, may be None')\n"
            "    # required and never None:\n"
            "    bar: str\n\n"
            "The bare `bar: str | None` is REQUIRED-but-nullable, "
            "which almost no caller expects. Pydantic accepts None "
            "as a value once present, but the field itself must be "
            "supplied — confusing contract."
        )
    if n < BASELINE_OPTIONAL_NO_DEFAULT:
        pytest.fail(
            f"Optional-no-default count dropped from "
            f"{BASELINE_OPTIONAL_NO_DEFAULT} to {n}. 🎉 Update "
            f"`BASELINE_OPTIONAL_NO_DEFAULT` to {n}."
        )


def test_allowlist_entries_actually_correspond_to_real_fields():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions.
    """
    if not ALLOWLIST:
        return
    schemas = _collect_schemas()
    real_keys: set[tuple[str, str, str]] = set()
    for module_name, class_name, cls in schemas:
        for field_name in cls.model_fields:
            real_keys.add((module_name, class_name, field_name))
    stale = [k for k in ALLOWLIST if k not in real_keys]
    assert not stale, f"Stale ALLOWLIST entries: {stale}."
