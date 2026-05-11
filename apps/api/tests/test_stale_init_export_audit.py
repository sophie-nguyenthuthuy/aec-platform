"""Stale `__init__.py` re-export audit.

The bug class
-------------
A package's `__init__.py` contains:

    from .foo import Foo, Bar

A later refactor renames `Bar` to `BarV2` in `foo.py` but
forgets to update `__init__.py`. Importing
`from package import Bar` now fails at runtime with
`ImportError: cannot import name 'Bar'`.

For app code, the import error surfaces immediately and
someone fixes it. For optional / lazily-imported packages
(test fixtures, admin tools), the broken re-export sits there
silently until someone tries to use the package — usually weeks
or months after the rename.

What this audit checks
----------------------
For every `__init__.py` under `apps/api/{schemas,services,
routers,models,middleware}` plus `apps/worker/`:

  1. Parse each `from .<module> import <names>` statement.
  2. Parse the imported module's AST (`<module>.py` in the
     same package directory).
  3. For every imported name, assert it's defined as a top-
     level name in the module — either an import, an assignment,
     or a `def` / `class` / `async def` declaration.

What's NOT checked
------------------
- Star imports (`from .x import *`) — checked by Python at
  import time.
- Conditional imports inside `if TYPE_CHECKING:` — those don't
  affect runtime behaviour.
- Deep package imports (`from .x.y import Z`) — we only walk
  one level deep; the inner package's `__init__.py` has its
  own audit pass.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_ROOT = _REPO_ROOT / "apps" / "api"
_SCAN_ROOTS: list[Path] = [
    _API_ROOT / "schemas",
    _API_ROOT / "services",
    _API_ROOT / "routers",
    _API_ROOT / "models",
    _API_ROOT / "middleware",
    _API_ROOT / "core",
    _REPO_ROOT / "apps" / "worker",
]


# Today's baseline. Filled in on first run.
BASELINE_STALE_INIT_EXPORTS = 0


# Per-(init_path, exported_name) allowlist. Each entry needs a
# stated reason. An empty rationale silences the gate.
ALLOWLIST: dict[tuple[str, str], str] = {
    # No entries today.
}


def _list_init_files() -> list[Path]:
    out: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("__init__.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _module_top_level_names(path: Path) -> set[str]:
    """Return the set of top-level names defined in `path`.
    Includes:
      * imports (`import x`, `from y import z`)
      * assignments (`X = ...`, `X: T = ...`)
      * function / class / async-function defs
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return set()
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
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    # We can't statically know what * imports.
                    # The audit accepts this gap.
                    continue
                names.add(alias.asname or alias.name)
    return names


def _audit_init(init_path: Path) -> list[str]:
    """Return list of `path::imported_name` strings for stale
    re-exports."""
    try:
        text = init_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(text, filename=str(init_path))
    except SyntaxError:
        return []
    rel_init = init_path.relative_to(_REPO_ROOT).as_posix()
    pkg_dir = init_path.parent
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        # Only interested in `from .submodule import X` (level >= 1
        # AND a single-name relative module).
        if node.level < 1 or not node.module:
            continue
        # Resolve the relative module to a `.py` file in pkg_dir.
        # `from .x import Y` → pkg_dir/x.py.
        # `from .x.y import Y` → pkg_dir/x/y.py — out of scope.
        if "." in node.module:
            continue
        target_file = pkg_dir / f"{node.module}.py"
        if not target_file.exists():
            # Could be a sub-package (a directory with __init__.py).
            sub_pkg = pkg_dir / node.module / "__init__.py"
            if sub_pkg.exists():
                target_file = sub_pkg
            else:
                # Module not found — that's a different bug shape;
                # the failing-import audit would catch it. Skip.
                continue
        defined_names = _module_top_level_names(target_file)
        for alias in node.names:
            if alias.name == "*":
                continue
            if alias.name not in defined_names:
                key = (rel_init, alias.name)
                if key in ALLOWLIST:
                    continue
                findings.append(
                    f"{rel_init}::{alias.name}  (not found in {target_file.relative_to(_REPO_ROOT).as_posix()})"
                )
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for init in _list_init_files():
        out.extend(_audit_init(init))
    return out


def test_no_stale_init_reexports():
    """Every `from .x import Y` in an __init__.py should resolve
    to a real top-level name `Y` in `x.py`. Stale re-exports
    silently 500 at runtime when the package is imported.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_STALE_INIT_EXPORTS:
        new = n - BASELINE_STALE_INIT_EXPORTS
        pytest.fail(
            f"{new} new stale __init__.py re-export(s) "
            f"(total now {n}, baseline {BASELINE_STALE_INIT_EXPORTS}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nFix one of two ways:\n"
            "  * Add the missing name back to the source module, OR\n"
            "  * Remove the stale `from .x import Y` line from "
            "__init__.py.\n\n"
            "A stale re-export silently breaks `from package import Y` "
            "at runtime — only surfaces when someone imports the "
            "package. For sparingly-used packages, the bug can sit "
            "for months."
        )
    if n < BASELINE_STALE_INIT_EXPORTS:
        pytest.fail(
            f"Stale-init-export count dropped from "
            f"{BASELINE_STALE_INIT_EXPORTS} to {n}. 🎉 Update "
            f"`BASELINE_STALE_INIT_EXPORTS` to {n}."
        )


def test_audit_recognises_documented_shapes(tmp_path):
    """Defensive: positive + negative fixtures using a tmp dir."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    # Module that defines Foo but NOT Bar.
    (pkg / "foo.py").write_text("class Foo:\n    pass\n")
    # __init__.py that re-exports both.
    (pkg / "__init__.py").write_text("from .foo import Foo, Bar\n")

    # Use the tmp init's _audit_init directly. We need to patch
    # _REPO_ROOT computation — easier to just test the helper.
    init_path = pkg / "__init__.py"
    # Manually invoke the audit's logic on the tmp init file.
    # Simulate: parse imports, check defined names.
    text = init_path.read_text()
    tree = ast.parse(text)
    foo_defined = _module_top_level_names(pkg / "foo.py")
    assert "Foo" in foo_defined
    assert "Bar" not in foo_defined

    # Check the audit walker would catch the missing `Bar`.
    found_stale: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "foo":
            for alias in node.names:
                if alias.name not in foo_defined:
                    found_stale.append(alias.name)
    assert found_stale == ["Bar"], f"Expected ['Bar'], got {found_stale}"


def test_allowlist_entries_actually_correspond_to_real_imports():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions.
    """
    if not ALLOWLIST:
        return
    real_imports: set[tuple[str, str]] = set()
    for init in _list_init_files():
        try:
            tree = ast.parse(init.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = init.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    real_imports.add((rel, alias.name))
    stale = [k for k in ALLOWLIST if k not in real_imports]
    assert not stale, f"Stale ALLOWLIST entries: {stale}."
