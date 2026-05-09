"""Pydantic field-level constraint audit.

Sister of `test_pydantic_strictness_audit.py` — that audit pins
`extra="forbid"` at the model-config level. THIS audit pins
field-level constraints: every `str` field has `min_length`/
`max_length` set; every `int` / `float` has `ge` / `le`.

The bug class
-------------
Without `max_length`, a `str` field accepts arbitrarily-large
input. A `name: str` that omits the constraint accepts a 50MB
string and burns parser CPU rendering it. Per-field input
validation is the cheapest layer of DoS defence.

Without `ge` / `le`, a numeric field accepts any value. A
`quantity: int` without `ge=0` lets a client submit `-1` and
sometimes bypass business logic that assumed positive
quantities.

What this audit checks
----------------------
For every Pydantic schema in `apps/api/schemas/*.py`:
  * Every direct `str` field has `min_length` OR `max_length`
    set via `Field(...)`.
  * Every direct `int`/`float` field has `ge`/`le` OR `gt`/`lt`.

What it doesn't check
---------------------
* Optional fields (`str | None`) with default `None` are exempt
  — the constraint applies when the field is set, not when it's
  absent.
* `Literal[...]` types — they're already constrained by the
  literal set.
* `EmailStr` / `HttpUrl` / `UUID` — Pydantic's built-in types
  are already constrained.
* Nested models — recursing into them is the next ratchet.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_SCHEMAS_DIR = _API_ROOT / "schemas"


# Today's baselines. Filled in on first run.
BASELINE_UNCONSTRAINED_STR = 506
BASELINE_UNCONSTRAINED_NUMERIC = 266


# Per-(module, class, field) allowlist for legitimate cases.
# Each entry needs a stated reason.
ALLOWLIST: dict[tuple[str, str, str], str] = {
    # No entries today. Add lazily as legitimate cases surface.
}


def _collect_schemas() -> list[tuple[str, str, type]]:
    """Walk apps/api/schemas/ and return every BaseModel subclass.

    Same shape as `test_pydantic_strictness_audit.py`'s collector.
    """
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


def _resolved_type(annotation):
    """Strip Optional[X] / X | None to inner type. Returns the
    non-None side (or None if both sides are None)."""
    import types
    from typing import get_args, get_origin

    origin = get_origin(annotation)
    if origin is types.UnionType or (origin is not None and str(origin).endswith("Union")):
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
        return None
    return annotation


def _has_str_constraint(field_info) -> bool:
    """True if the field has min_length or max_length set."""
    if getattr(field_info, "metadata", None):
        for c in field_info.metadata:
            cls_name = type(c).__name__
            if cls_name in ("MinLen", "MaxLen", "MinLength", "MaxLength"):
                return True
            # Pydantic v2 stores `min_length` / `max_length` as
            # attributes on a StringConstraints metadata item.
            if hasattr(c, "min_length") and c.min_length is not None:
                return True
            if hasattr(c, "max_length") and c.max_length is not None:
                return True
    return False


def _has_numeric_constraint(field_info) -> bool:
    """True if the field has ge / le / gt / lt set."""
    if getattr(field_info, "metadata", None):
        for c in field_info.metadata:
            cls_name = type(c).__name__
            if cls_name in ("Ge", "Le", "Gt", "Lt"):
                return True
            for attr in ("ge", "le", "gt", "lt"):
                if hasattr(c, attr) and getattr(c, attr) is not None:
                    return True
    return False


def _audit_schema(cls) -> tuple[list[str], list[str]]:
    """Return (str_unconstrained, numeric_unconstrained) lists of
    `module.Class.field_name` strings."""
    from typing import Literal, get_origin

    str_un: list[str] = []
    num_un: list[str] = []

    module_name = cls.__module__.replace("schemas.", "")
    for field_name, field_info in cls.model_fields.items():
        ann = _resolved_type(field_info.annotation)
        if ann is None:
            continue
        # Skip Literals, Enums, and complex types — those have
        # their own implicit constraints.
        if get_origin(ann) is Literal:
            continue
        # Some built-in Pydantic types (EmailStr, HttpUrl) have
        # implicit constraints; skip them.
        type_name = getattr(ann, "__name__", str(ann))
        if type_name in ("EmailStr", "HttpUrl", "AnyUrl", "PostgresDsn", "UUID"):
            continue

        key = (module_name, cls.__name__, field_name)
        if key in ALLOWLIST:
            continue

        if ann is str:
            if not _has_str_constraint(field_info):
                str_un.append(f"schemas.{module_name}.{cls.__name__}.{field_name}")
        elif ann in (int, float):
            if not _has_numeric_constraint(field_info):
                num_un.append(f"schemas.{module_name}.{cls.__name__}.{field_name}")
    return str_un, num_un


def test_every_str_field_has_a_length_constraint():
    """Every direct `str` Pydantic field should have either
    `min_length` or `max_length` set via Field(...). Catches the
    "client submits a 50MB string into a field that expected 200
    chars" DoS shape.

    Failures surface both ratchet directions.
    """
    schemas = _collect_schemas()
    assert schemas, "no schemas found — auditor's path resolution is broken"

    findings: list[str] = []
    for _, _, cls in schemas:
        str_un, _ = _audit_schema(cls)
        findings.extend(str_un)

    n = len(findings)
    if n > BASELINE_UNCONSTRAINED_STR:
        new = n - BASELINE_UNCONSTRAINED_STR
        pytest.fail(
            f"{new} new unconstrained str field(s) "
            f"(total now {n}, baseline {BASELINE_UNCONSTRAINED_STR}):\n  "
            + "\n  ".join(sorted(findings)[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nAdd `min_length` / `max_length` via Field(...):\n"
            "    title: str = Field(..., min_length=1, max_length=200)\n\n"
            "If a field genuinely needs unbounded length (free-text "
            "content body), add it to ALLOWLIST with a stated reason."
        )
    if n < BASELINE_UNCONSTRAINED_STR:
        pytest.fail(
            f"Unconstrained-str count dropped from {BASELINE_UNCONSTRAINED_STR} to {n}. 🎉 Update the baseline."
        )


def test_every_numeric_field_has_a_range_constraint():
    """Every direct `int` or `float` field should have at least
    one of ge/le/gt/lt set via Field(...). Catches the "client
    submits a negative quantity that bypasses business logic" bug.
    """
    schemas = _collect_schemas()
    findings: list[str] = []
    for _, _, cls in schemas:
        _, num_un = _audit_schema(cls)
        findings.extend(num_un)

    n = len(findings)
    if n > BASELINE_UNCONSTRAINED_NUMERIC:
        new = n - BASELINE_UNCONSTRAINED_NUMERIC
        pytest.fail(
            f"{new} new unconstrained numeric field(s) "
            f"(total now {n}, baseline {BASELINE_UNCONSTRAINED_NUMERIC}):\n  "
            + "\n  ".join(sorted(findings)[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nAdd `ge` / `le` (or `gt` / `lt`) via Field(...):\n"
            "    quantity: int = Field(..., ge=0, le=10_000)\n"
            "    rate: float = Field(..., ge=0.0, le=1.0)\n\n"
            "If the field genuinely accepts the full numeric range "
            "(unbounded counter, signed delta), add to ALLOWLIST with "
            "a stated reason."
        )
    if n < BASELINE_UNCONSTRAINED_NUMERIC:
        pytest.fail(
            f"Unconstrained-numeric count dropped from {BASELINE_UNCONSTRAINED_NUMERIC} to {n}. 🎉 Update the baseline."
        )


def test_allowlist_entries_actually_correspond_to_real_fields():
    """Defensive: stale `ALLOWLIST` entries silently mask future
    regressions. Every (module, class, field) tuple must
    correspond to a real Pydantic field.
    """
    schemas = _collect_schemas()
    real_keys: set[tuple[str, str, str]] = set()
    for module_name, class_name, cls in schemas:
        m = module_name
        for field_name in cls.model_fields:
            real_keys.add((m, class_name, field_name))

    stale = [k for k in ALLOWLIST if k not in real_keys]
    assert not stale, (
        f"Stale ALLOWLIST entries: {stale}. Remove them so the allowlist reflects only currently-live exemptions."
    )
