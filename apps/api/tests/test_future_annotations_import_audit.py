"""Audit: every Python file under `apps/api/` has
`from __future__ import annotations` near the top.

PEP 563 (postponed evaluation of annotations) makes type
annotations lazy strings rather than eager runtime expressions.
Concrete benefits in this codebase:

  * **Cheaper imports.** Every annotation resolves only when
    something explicitly calls `get_type_hints()`. Without
    `__future__ annotations`, every type referenced in a
    signature must be importable at module-load time, even if
    it's only used for typing.

  * **Forward references work without quotes.** A class can
    reference itself or a forward-declared sibling without
    `"ClassName"` string-quoting:
      ```python
      class Node:
          parent: Node | None  # works without quotes
      ```

  * **Cycle-breaking via `if TYPE_CHECKING:`.** Mutual imports
    that exist only for typing don't run at module load.
    Without `__future__ annotations`, the
    `if TYPE_CHECKING: from x import Y` pattern is more
    fragile.

The convention in this codebase is: every `.py` file under
`apps/api/` (except auto-generated migration files which alembic
controls) starts with the import. Drift here is silent — code
runs fine without it for now, but the imports get heavier
over time, and forward references silently re-introduce import
cycles.

Failure mode this catches:

  * **A new file shipped without the import.** Its annotations
    are eager; if it imports a heavy module just for typing,
    every consumer of the new file pays the import cost. Adds
    up across hundreds of imports per worker boot.

  * **A refactor that moved code AND lost the import.** Common
    when copy-pasting between modules and stripping headers.

This file is read-only — AST-parses every `.py` file. Survives
reverts.
"""

from __future__ import annotations

import ast
from pathlib import Path


# Files (relative to apps/api/) that legitimately don't need
# the import. Most should — this list captures the genuine
# exceptions.
_NO_FUTURE_ANNOTATIONS_REQUIRED: frozenset[str] = frozenset(
    {
        # Empty or near-empty `__init__.py` files don't have
        # type annotations, so the import would be dead. Listed
        # explicitly to keep the audit's intent clear (vs a
        # blanket "skip all `__init__.py`" rule which would
        # also miss `__init__.py` files that DO have type
        # annotations).
    }
)


# Directories under apps/api/ that the audit skips wholesale.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        # Alembic-generated migration files have their own
        # template — they include the import in the canonical
        # template but a single legacy migration without it
        # isn't worth a fix-it cascade. Skip the whole dir;
        # the migration symmetry + chain audits cover the
        # operational concerns there.
        "alembic",
        # __pycache__ + .pytest_cache + similar runtime artefacts.
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)


def _api_dir() -> Path:
    return Path(__file__).parent.parent


def _has_future_annotations(tree: ast.Module) -> bool:
    """Return True if the module body contains
    `from __future__ import annotations` as a top-level
    statement.

    Only top-level: an import nested inside a function or
    class body doesn't count (and wouldn't have the right
    semantics anyway — `__future__` imports must be
    module-level)."""
    for node in tree.body:
        # Skip module docstring.
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                for alias in node.names:
                    if alias.name == "annotations":
                        return True
        # Stop scanning at the first non-import / non-docstring
        # statement — `__future__` imports MUST come first.
        if not isinstance(node, ast.Import | ast.ImportFrom):
            break
    return False


def _walk_python_files():
    """Yield `(rel_path, ast_tree)` for every `.py` file under
    `apps/api/` except those in `_SKIP_DIRS` and packaging-only
    `__init__.py` files (which legitimately have no annotations
    and the import would be dead).

    A non-empty `__init__.py` with annotations would slip
    through this skip — the trade-off is acceptable because
    those are rare and the per-file allowlist
    (`_NO_FUTURE_ANNOTATIONS_REQUIRED`) can override the skip
    if a specific `__init__.py` does need pinning.
    """
    api_dir = _api_dir()
    for py_file in api_dir.rglob("*.py"):
        rel_parts = py_file.relative_to(api_dir).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        # Packaging-only __init__.py files: skip by default
        # because they typically have zero annotations and the
        # import would be dead. The allowlist exists to add any
        # specific `__init__.py` BACK to the audit if it does
        # have annotations worth pinning.
        if py_file.name == "__init__.py":
            continue
        rel = "/".join(rel_parts)
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        yield rel, tree


def test_every_python_file_has_future_annotations():
    """Every `.py` file under `apps/api/` (excluding
    `_SKIP_DIRS`) MUST have `from __future__ import annotations`
    at the top.

    Resolution paths on a failing file:

      1. **Add the import.** Place it directly after the module
         docstring (if any), before any other imports:
            ```python
            \"\"\"Module docstring.\"\"\"

            from __future__ import annotations

            import ...
            ```
      2. **If the file genuinely has no annotations** (e.g. a
         data-only constants module), add it to
         `_NO_FUTURE_ANNOTATIONS_REQUIRED`. Today the
         allowlist is empty — every Python file in this
         codebase has annotations.
    """
    missing: list[str] = []
    for rel_path, tree in _walk_python_files():
        if rel_path in _NO_FUTURE_ANNOTATIONS_REQUIRED:
            continue
        if not _has_future_annotations(tree):
            missing.append(rel_path)

    assert not missing, (
        "These Python files don't have "
        "`from __future__ import annotations` near the top:\n  " + "\n  ".join(sorted(missing)) + "\n\n"
        "The convention in this codebase is that every Python "
        "file under apps/api/ uses PEP 563 postponed annotations. "
        "Add the import directly after the module docstring (if "
        "any), before any other import.\n\n"
        "If the file genuinely has no annotations and the import "
        "would be dead, add it to "
        "`_NO_FUTURE_ANNOTATIONS_REQUIRED` in this audit file. "
        "PR review of THAT addition checks the rationale."
    )


def test_audit_finds_python_files():
    """Sanity floor — the audit's iteration finds at least a
    handful of files. If `apps/api/` got moved or wiped, this
    catches it before the import check silently passes with zero
    files scanned."""
    files = list(_walk_python_files())
    assert len(files) >= 50, (
        f"Audit found {len(files)} Python files — implausibly few. "
        "Either apps/api/ moved (update _api_dir) or the codebase "
        "got drastically smaller (broader regression worth "
        "surfacing)."
    )
