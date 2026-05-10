"""Audit: no mutable default arguments in function signatures.

Python evaluates default arguments ONCE at function definition
time, not per-call. A mutable default (`list`, `dict`, `set`,
or a call to a mutable factory) is shared across every
invocation that doesn't supply the argument.

Classic footgun:

    def append_to(item, target=[]):  # default list shared!
        target.append(item)
        return target

    append_to(1)  # → [1]
    append_to(2)  # → [1, 2]   surprise

The intended pattern uses an immutable sentinel:

    def append_to(item, target=None):
        if target is None:
            target = []
        target.append(item)
        return target

Failure mode this catches:

  * **A handler with `data=[]` default** — every request that
    doesn't supply `data` shares the same list. Stale data
    bleeds across requests; race conditions on append.

  * **A factory with `config={}` default** — first call
    populates the dict; subsequent calls see whatever the
    first call left behind. Tests pass in isolation, fail
    when run in any order.

The audit walks every `.py` file under `apps/api/`,
AST-parses, and flags every `FunctionDef` /
`AsyncFunctionDef` whose `args.defaults` or `args.kw_defaults`
contains a Mutable form:

  * `ast.List`, `ast.Dict`, `ast.Set` literals.
  * `ast.Call` to a known mutable factory (`list()`, `dict()`,
    `set()`, `[]`, `{}`, etc.).

Common safe forms (FastAPI `Depends(...)`, `Field(...)`,
`Annotated[...]`, `Query(...)`, etc.) are explicitly skipped —
they construct dependency descriptors, not mutable state shared
across calls.

Today's baseline is 0 — the codebase is clean. Ships as a
strict-zero ratchet.

This file is read-only — AST-walks. Survives reverts.
"""

from __future__ import annotations

import ast
from pathlib import Path


# Allowlist for `<rel_path>:<line>` entries where a mutable
# default is intentional and the immutable-sentinel pattern
# isn't applicable. Today: empty.
_MUTABLE_DEFAULT_ALLOWLIST: dict[str, str] = {}


# Function names that take a mutable-shaped default but don't
# actually share state across calls — these are FastAPI / pydantic
# DSL constructors that build dependency descriptors. Skipping
# them avoids drowning the audit in false positives.
_SAFE_FACTORY_NAMES: frozenset[str] = frozenset(
    {
        # FastAPI parameter declarations.
        "Depends",
        "Annotated",
        "Query",
        "Path",
        "Body",
        "Header",
        "Cookie",
        "File",
        "Form",
        "Security",
        # Pydantic field declarations.
        "Field",
        # Generic factory wrappers; if they were genuinely
        # mutating shared state the broader test suite would
        # surface that.
        "frozenset",
        "tuple",
        "field",  # dataclasses.field(default_factory=...)
    }
)


# Directories the audit doesn't walk.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "tests",
        "alembic",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)


def _api_dir() -> Path:
    return Path(__file__).parent.parent


def _is_mutable_default(default: ast.expr) -> bool:
    """Return True if `default` is a literal list / dict / set,
    or a call to a known mutable factory.

    `Annotated[...]`, `Depends(...)`, `Field(...)` and other
    FastAPI / pydantic DSL constructors are explicitly NOT
    flagged — they're declarative shape, not state-bearing
    mutables.
    """
    # Literals.
    if isinstance(default, ast.List | ast.Dict | ast.Set):
        return True
    # Calls.
    if isinstance(default, ast.Call):
        func = default.func
        if isinstance(func, ast.Name):
            if func.id in _SAFE_FACTORY_NAMES:
                return False
            # `list()`, `dict()`, `set()` — explicit mutables.
            if func.id in {"list", "dict", "set"}:
                return True
            # Any other bare-name call: treat as opaque, don't
            # flag (could be `frozenset()`, an enum constructor,
            # etc.). The literal-form check above covers the
            # high-confidence cases.
            return False
        # Attribute calls (e.g. `mod.func()`) — opaque; skip.
        return False
    return False


def _find_mutable_defaults(tree: ast.Module) -> list[tuple[int, str]]:
    """Return `(line, function_name)` for every function with a
    mutable default arg.
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for default in node.args.defaults:
            if _is_mutable_default(default):
                hits.append((node.lineno, node.name))
                break  # one hit per function is enough
        # kw_defaults can contain None for kw-only args without
        # a default — filter those out.
        for default in node.args.kw_defaults:
            if default is None:
                continue
            if _is_mutable_default(default):
                hits.append((node.lineno, node.name))
                break
    return hits


def _walk_python_files():
    """Yield `(rel_path, ast_tree)` for every `.py` file under
    `apps/api/` excluding `_SKIP_DIRS`."""
    api_dir = _api_dir()
    for py_file in api_dir.rglob("*.py"):
        rel_parts = py_file.relative_to(api_dir).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        rel = "/".join(rel_parts)
        yield rel, tree


def test_no_mutable_default_arguments():
    """Every function under `apps/api/` (excluding tests/ and
    alembic/) MUST NOT have a mutable default argument.

    Resolution paths on a failing entry:

      1. **Use an immutable sentinel** — the canonical fix.
         Replace `def f(x=[]):` with:
            ```python
            def f(x=None):
                if x is None:
                    x = []
                ...
            ```
         The sentinel ensures every call gets a fresh empty
         list; the original mutable list is never shared.

      2. **Use `dataclasses.field(default_factory=...)`** if
         the mutable lives on a dataclass.

      3. **Genuine need for the mutable default** (extremely
         rare; must be a memoization / caching scheme that
         INTENDS to share state across calls) — add to
         `_MUTABLE_DEFAULT_ALLOWLIST` with a rationale.

    Why the audit cares: a test suite catches the obvious
    cases of mutable-default state-bleed, but the subtle cases
    (handler called from N test files, all reading from the
    same default dict) only surface as flaky-test reports
    that nobody can reproduce locally.
    """
    bad: list[str] = []
    for rel_path, tree in _walk_python_files():
        for line, name in _find_mutable_defaults(tree):
            site = f"{rel_path}:{line} {name}"
            site_key = f"{rel_path}:{line}"
            if site_key in _MUTABLE_DEFAULT_ALLOWLIST:
                continue
            bad.append(site)

    assert not bad, (
        "These functions have mutable default arguments — "
        "a list / dict / set in the signature is shared across "
        "every call that doesn't override it:\n  " + "\n  ".join(sorted(bad)) + "\n\n"
        "Resolution:\n"
        "  1. Use an immutable sentinel (`x=None`) and build "
        "the mutable inside the function body.\n"
        "  2. For dataclasses, use "
        "`dataclasses.field(default_factory=list)`.\n"
        "  3. If the shared state IS the intent (rare), add "
        "the file:line to `_MUTABLE_DEFAULT_ALLOWLIST` with a "
        "rationale.\n\n"
        "Why this matters: state-bleed across calls produces "
        "flaky tests that pass in isolation and fail under "
        "ordering changes. The bug surfaces hours after the "
        "PR lands."
    )


def test_mutable_default_allowlist_entries_have_rationale():
    """Every `_MUTABLE_DEFAULT_ALLOWLIST` value must be a
    non-empty rationale string.
    """
    bare: list[str] = []
    for site, rationale in _MUTABLE_DEFAULT_ALLOWLIST.items():
        if not rationale or not rationale.strip():
            bare.append(site)
    assert not bare, (
        "These `_MUTABLE_DEFAULT_ALLOWLIST` entries are missing "
        "a rationale:\n  " + "\n  ".join(sorted(bare)) + "\n\n"
        "Each entry must explain WHY the shared mutable default "
        "is intentional (e.g. memoization). Rationale-free "
        "entries silence the audit without a reviewable reason."
    )


def test_audit_finds_python_files():
    """Sanity floor — the iteration finds files. Without this,
    a refactor that moved `apps/api/` would let the
    mutable-default check silently pass with zero files scanned.
    """
    files = list(_walk_python_files())
    assert len(files) >= 50, (
        f"Audit found {len(files)} Python files — implausibly few. "
        "Either apps/api/ moved (update _api_dir) or the codebase "
        "got drastically smaller."
    )
