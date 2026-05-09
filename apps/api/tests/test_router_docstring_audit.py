"""Per-router docstring completeness audit.

Sister of `test_openapi_route_docs_audit.py` from an earlier round
— that one pins `summary` + `response_model` in the route
decorator metadata. THIS one walks the actual handler source.

The bug class
-------------
Decorator-level `summary=` is FastAPI-introspectable; an empty
docstring on the handler is invisible at the schema layer. But
the docstring is what the next contributor reads when they're
trying to figure out what an endpoint does. A handler whose body
is 100 lines of business logic with no docstring is the bug
shape: the intent is buried in the implementation, and the next
modifier has to reverse-engineer it.

What this audit checks
----------------------
1. Every `apps/api/routers/*.py` module has a non-empty
   module-level docstring (the file's intent — "this router owns
   the X workflow").
2. Every function decorated with `@router.X(...)` has a non-empty
   docstring. Heuristic for "decorated with @router.X": AST walk;
   look for a Call decorator whose attribute name is in
   {get, post, put, patch, delete, head, options}.

What it doesn't check
---------------------
Docstring quality. A one-line docstring satisfies the gate. The
audit's purpose is "is the field populated at all" — quality
review is a code-review concern. Empty docstrings are the bug
class; perfunctory ones aren't.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_ROUTERS_DIR = _API_ROOT / "routers"


# Today's baseline — filled in on first run. Same ratchet shape
# as the other audits.
BASELINE_MODULES_NO_DOCSTRING = 1
BASELINE_HANDLERS_NO_DOCSTRING = 133


_HTTP_METHOD_NAMES = frozenset(["get", "post", "put", "patch", "delete", "head", "options"])


def _list_router_files() -> list[Path]:
    return sorted(p for p in _ROUTERS_DIR.glob("*.py") if p.name != "__init__.py" and p.is_file())


def _has_module_docstring(tree: ast.Module) -> bool:
    """The first statement is an Expr whose value is a string constant."""
    if not tree.body:
        return False
    first = tree.body[0]
    if not isinstance(first, ast.Expr):
        return False
    if not isinstance(first.value, ast.Constant):
        return False
    return isinstance(first.value.value, str) and first.value.value.strip() != ""


def _is_router_decorator(dec: ast.expr) -> bool:
    """`@router.get(...)` / `@router.post(...)` / etc.

    Recognises the standard form (`router` is a `Name`, the
    decorator is a `Call` to one of the HTTP method attrs). Also
    accepts `_router.get(...)` / `r.get(...)` etc. — any name
    ending in or equal to "router" is treated as the router.
    """
    if not isinstance(dec, ast.Call):
        return False
    func = dec.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in _HTTP_METHOD_NAMES:
        return False
    target = func.value
    while isinstance(target, ast.Attribute):
        target = target.value
    if not isinstance(target, ast.Name):
        return False
    return target.id.lower().endswith("router")


def _collect_undocumented_handlers(tree: ast.Module, file_label: str) -> list[str]:
    """Walk top-level (and one level deep) function defs; return
    `file:line  handler_name` for those that:
      * Are decorated with @router.X(...)
      * AND have no non-empty docstring.
    """
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_router_decorator(d) for d in node.decorator_list):
            continue
        doc = ast.get_docstring(node)
        if doc is None or doc.strip() == "":
            out.append(f"{file_label}:{node.lineno}  {node.name}")
    return out


def test_every_router_module_has_a_docstring():
    """Each `apps/api/routers/*.py` should have a non-empty
    module-level docstring describing the router's scope.

    Same ratchet pattern: additions red-gate, reductions celebrate.
    """
    missing: list[str] = []
    for path in _list_router_files():
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        if not _has_module_docstring(tree):
            missing.append(str(path.relative_to(_API_ROOT)))

    n = len(missing)
    if n > BASELINE_MODULES_NO_DOCSTRING:
        new = n - BASELINE_MODULES_NO_DOCSTRING
        pytest.fail(
            f"{new} new router module(s) without a top-level docstring "
            f"(total now {n}, baseline {BASELINE_MODULES_NO_DOCSTRING}):\n  "
            + "\n  ".join(missing)
            + '\n\nAdd a `"""…"""` at the top of each file describing '
            "the router's scope (which workflow it owns, what's covered, "
            "what's deliberately not). The module docstring is the first "
            "thing the next contributor reads."
        )
    if n < BASELINE_MODULES_NO_DOCSTRING:
        pytest.fail(
            f"Module-docstring missing-count dropped from "
            f"{BASELINE_MODULES_NO_DOCSTRING} to {n}. 🎉 Update the baseline."
        )


def test_every_router_handler_has_a_docstring():
    """Every `@router.X(...)`-decorated handler should have a non-
    empty docstring. The docstring is what the next contributor
    reads when modifying an endpoint; a missing one buries the
    intent in the implementation.
    """
    undocumented: list[str] = []
    for path in _list_router_files():
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        rel = str(path.relative_to(_API_ROOT))
        undocumented.extend(_collect_undocumented_handlers(tree, rel))

    n = len(undocumented)
    if n > BASELINE_HANDLERS_NO_DOCSTRING:
        new = n - BASELINE_HANDLERS_NO_DOCSTRING
        pytest.fail(
            f"{new} new handler(s) without a docstring "
            f"(total now {n}, baseline {BASELINE_HANDLERS_NO_DOCSTRING}):\n  "
            + "\n  ".join(undocumented[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nAdd a non-empty docstring to each. Even one line "
            '(`"""Create a new task."""`) is enough — the bug class '
            "is empty docstrings, not perfunctory ones."
        )
    if n < BASELINE_HANDLERS_NO_DOCSTRING:
        pytest.fail(
            f"Undocumented-handler count dropped from {BASELINE_HANDLERS_NO_DOCSTRING} to {n}. 🎉 Update the baseline."
        )


def test_audit_recognises_router_decorator_shapes():
    """Defensive: hand-rolled fixtures for the AST detector. A
    regression that broke `_is_router_decorator` (e.g. failed to
    recognise `@admin_router.post(...)`) would silently let
    undocumented handlers through.
    """
    # Standard `@router.post(...)`.
    src1 = ast.parse("from fastapi import APIRouter\nrouter = APIRouter()\n@router.post('/x')\nasync def f(): pass\n")
    fn = src1.body[-1]
    assert isinstance(fn, ast.AsyncFunctionDef)
    assert _is_router_decorator(fn.decorator_list[0])

    # Suffix-named router (`@admin_router.get(...)`).
    src2 = ast.parse(
        "from fastapi import APIRouter\nadmin_router = APIRouter()\n@admin_router.get('/y')\ndef g(): pass\n"
    )
    fn = src2.body[-1]
    assert isinstance(fn, ast.FunctionDef)
    assert _is_router_decorator(fn.decorator_list[0])

    # Negative: a non-router decorator should NOT match.
    src3 = ast.parse("@something.unrelated\ndef h(): pass\n")
    fn = src3.body[-1]
    assert isinstance(fn, ast.FunctionDef)
    assert not _is_router_decorator(fn.decorator_list[0])
