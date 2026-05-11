"""Audit: every name in a module's `__all__` MUST exist as a
top-level symbol in that module.

`__all__` is the documented public-API surface of a Python
module. Two distinct failure modes a regression here can
produce:

  * **`__all__` references a name that doesn't exist in the
    module.** Importing the module via `from x import *`
    raises `AttributeError`. CI tests that don't use
    star-imports never trigger it; the regression surfaces in
    a downstream consumer's CI hours later.

  * **`__all__` lists a private name (leading underscore).**
    Either the underscore is a typo (the symbol was meant to
    be public) or someone is intentionally exposing internals.
    Either case deserves PR review; the audit surfaces it.

The audit's check:

  1. AST-parse each `apps/api/**/*.py` file.
  2. Find the top-level `__all__ = [...]` assignment.
  3. For each string in the list, assert it matches a
     top-level symbol in the file (function def, class def,
     variable assignment, or import alias).
  4. Flag underscore-prefixed names in `__all__` (intentional
     private-leak; rare but worth surfacing).

This file is read-only. Survives reverts.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Files (relative to apps/api/) where `__all__` legitimately
# references something the static AST walker can't see — e.g.
# names exported via runtime side-effects, dynamic re-exports.
# Today: empty.
_SKIP_FILES: frozenset[str] = frozenset()


# Directories the audit doesn't walk. Same set as the
# future-annotations audit.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "alembic",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)


def _api_dir() -> Path:
    return Path(__file__).parent.parent


def _extract_dunder_all(tree: ast.Module) -> list[str] | None:
    """Find a module-level `__all__ = ["x", "y", ...]` assignment.

    Returns the list of strings if present, None if absent OR if
    the value is a non-literal expression (e.g. computed via
    concatenation — the audit can't statically resolve those).

    Tuples of strings are also accepted (`__all__ = ("x", "y")`)."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != "__all__":
            continue

        value = node.value
        if isinstance(value, ast.List | ast.Tuple):
            names: list[str] = []
            for elt in value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    names.append(elt.value)
                else:
                    # Non-literal entry (e.g. a variable name);
                    # bail out — the static check can't resolve.
                    return None
            return names
        # Non-list / non-tuple form (e.g. concatenation, splat).
        return None

    return None


def _collect_top_level_names(tree: ast.Module) -> set[str]:
    """Collect every top-level symbol in the module:
    * `def name(...)` — function definitions
    * `async def name(...)` — async function definitions
    * `class name(...)` — class definitions
    * `name = ...` — module-level variable assignments
    * `from x import name` and `from x import name as alias` —
      the binding name is the alias if present, else the
      imported name
    * `import x as alias` — the alias is the binding
    * `import x` — `x` is the binding (top-level package only)
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                elif isinstance(target, ast.Tuple | ast.List):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            names.add(elt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # `import x.y.z` binds `x` at the top-level. The
                # alias takes precedence: `import x.y.z as foo`
                # binds `foo`.
                bound = alias.asname or alias.name.split(".", 1)[0]
                names.add(bound)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    # `from x import *` — can't statically know
                    # what's bound. Skip.
                    continue
                names.add(alias.asname or alias.name)
    return names


def _walk_modules_with_dunder_all():
    """Yield `(rel_path, dunder_all, top_level_names)` for every
    Python file under `apps/api/` that has a static `__all__`."""
    api_dir = _api_dir()
    for py_file in api_dir.rglob("*.py"):
        rel_parts = py_file.relative_to(api_dir).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        rel = "/".join(rel_parts)
        if rel in _SKIP_FILES:
            continue
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        names = _extract_dunder_all(tree)
        if names is None:
            continue
        yield rel, names, _collect_top_level_names(tree)


def test_every_name_in_dunder_all_resolves_to_a_top_level_symbol():
    """Every entry in a module's `__all__` MUST match a top-level
    symbol declared in that module.

    Resolution paths on a failing entry:

      1. **Typo in `__all__`**: fix the string.
      2. **Symbol was renamed; `__all__` not updated**: same fix
         pattern as a typo.
      3. **Symbol is dynamically created** (rare; e.g. populated
         via metaclass machinery): add the file to `_SKIP_FILES`
         in this audit with a rationale comment.
    """
    bad_entries: list[str] = []
    for rel_path, dunder_all, top_level in _walk_modules_with_dunder_all():
        for name in dunder_all:
            if name not in top_level:
                bad_entries.append(f"{rel_path}: __all__ has {name!r} but no such top-level symbol")

    assert not bad_entries, (
        "These `__all__` entries don't match any top-level symbol "
        "in the module:\n  " + "\n  ".join(sorted(bad_entries)) + "\n\n"
        "Resolution:\n"
        "  1. If it's a typo, fix the string in `__all__`.\n"
        "  2. If the symbol was renamed, update both sides.\n"
        "  3. If the symbol IS created dynamically (rare), add "
        "the file to `_SKIP_FILES` in this audit with a "
        "rationale.\n\n"
        "Why this matters: importing the module via "
        "`from x import *` raises AttributeError on an unresolved "
        "name in `__all__`. The audit catches the regression "
        "before a downstream consumer's CI does."
    )


def test_no_underscore_names_in_dunder_all():
    """`__all__` lists the PUBLIC API. A leading-underscore name
    in `__all__` is either:

      1. A typo (the symbol was meant to be public; remove the
         underscore from both the symbol and `__all__`).
      2. An intentional private-export (rare; deserves PR
         review).

    Either way, surface the case so it's reviewed deliberately
    rather than slipping in by copy-paste.
    """
    private_in_all: list[str] = []
    for rel_path, dunder_all, _top in _walk_modules_with_dunder_all():
        for name in dunder_all:
            if name.startswith("_"):
                private_in_all.append(f"{rel_path}: __all__ exposes {name!r}")

    assert not private_in_all, (
        "These `__all__` entries are leading-underscore (private) "
        "names:\n  " + "\n  ".join(sorted(private_in_all)) + "\n\n"
        "If the underscore is a typo (the symbol IS supposed to "
        "be public), remove the underscore from both the symbol "
        "and the `__all__` entry. If the private export is "
        "intentional, that's worth a comment explaining why."
    )


def test_audit_finds_at_least_one_dunder_all():
    """Sanity floor — at least a handful of modules have
    `__all__`. Without this, a refactor that wiped every
    `__all__` would let the per-name check silently pass with
    zero modules scanned.
    """
    count = sum(1 for _ in _walk_modules_with_dunder_all())
    assert count >= 3, (
        f"Audit found {count} modules with `__all__` — "
        "implausibly few. Either every module dropped its "
        "`__all__` (unlikely) or the AST-extract helper "
        "stopped recognising the assignment shape."
    )
