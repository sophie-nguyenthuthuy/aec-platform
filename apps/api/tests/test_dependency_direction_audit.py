"""Dependency-direction audit (layered-architecture pin).

The bug class
-------------
Architectural drift is invisible until you try to extract a
package. Today `services/` imports nothing from `routers/` — a
service can be re-used from a worker, a CLI, or a test. The
moment one service does `from routers.foo import x`, the
service stops being a service: it can't run outside the FastAPI
process, every test of the service has to drag in the FastAPI
machinery, and the dependency graph turns into spaghetti.

The fix is cheap: enforce a layer ordering and reject upward
imports at audit time. The architecture *intent* gets pinned
before someone draws an arrow the wrong way for "just one
file."

Layer ordering (bottom → top)
-----------------------------
  0. `core/`, `db/`         — foundation. No domain knowledge.
  1. `models/`, `schemas/`  — data shape. Depend on foundation only.
  2. `services/`            — domain logic. Depend on data + foundation.
  3. `middleware/`,         — transport-adjacent helpers. Depend on
     `workers/`               services + below.
  4. `routers/`             — HTTP transport. Depend on anything below.
  5. `main.py`              — wiring. Depends on everything.

A module at tier N may import from tiers ≤ N. Anything else is
an upward edge — the audit fails on every such edge.

What this audit checks
----------------------
For every `.py` file under `apps/api/`, parse the AST, walk
top-level + nested `import`/`from … import` statements, and
flag any import that goes against the layer ordering.

What it doesn't check
---------------------
* Imports inside `if TYPE_CHECKING:` blocks — type-only deps
  are erased at runtime and don't create a real dependency.
* Tests (`tests/`) — they import from anywhere by design.
* Scripts (`scripts/`) — same.
* Lazy imports inside function bodies are flagged the same as
  top-level — if you need to break the cycle with a deferred
  import, add it to ALLOWLIST with a stated reason.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent


# Layer ordering. Each entry is (tier, [package_name, ...]).
# Lower-tier packages must not import from higher-tier ones.
_LAYERS: list[tuple[int, tuple[str, ...]]] = [
    (0, ("core", "db")),
    (1, ("models", "schemas")),
    (2, ("services",)),
    (3, ("middleware", "workers")),
    (4, ("routers",)),
]


# Flat lookup: package → tier.
_PKG_TIER: dict[str, int] = {pkg: tier for tier, pkgs in _LAYERS for pkg in pkgs}


# Today's baseline.
#
# 5 upward edges today, all from lower-tier modules importing
# `AuthContext` (and `Role`) out of `middleware/`. Those types are
# conceptually data-shape (caller identity, role enum) and arguably
# belong at tier 0 — when they get refactored down, this counter
# drops and the ratchet flags it. Until then the audit pins at 5
# so a *new* upward edge fails immediately.
BASELINE_UPWARD_EDGES = 5


# Per-(file_relpath, imported_module) allowlist. Each entry needs
# a stated reason. No entries today.
ALLOWLIST: dict[tuple[str, str], str] = {
    # No entries today. Add lazily as legitimate cases surface
    # (e.g. a service that genuinely needs a worker enqueue helper
    # — though even then, prefer extracting the helper into a lower
    # tier rather than allowlisting the upward edge).
}


def _python_files() -> list[Path]:
    """All `.py` files under apps/api/, excluding tests, scripts,
    alembic, generated dirs."""
    out: list[Path] = []
    skip_dirs = {"tests", "scripts", "alembic", "__pycache__"}
    for p in _API_ROOT.rglob("*.py"):
        if any(part in skip_dirs for part in p.relative_to(_API_ROOT).parts):
            continue
        out.append(p)
    return sorted(out)


def _file_tier(rel_path: Path) -> int | None:
    """Tier of the file based on its top-level package directory.
    `main.py` is tier 5 (entrypoint); everything else maps via
    its first directory component."""
    parts = rel_path.parts
    if len(parts) == 1 and parts[0].endswith(".py"):
        # Top-level files like main.py — entrypoint, may import
        # anything.
        return 5
    pkg = parts[0]
    return _PKG_TIER.get(pkg)


def _imported_pkg(node: ast.Import | ast.ImportFrom) -> str | None:
    """Top-level package of an import statement, or None if it's
    not a project-internal import we care about (e.g. third-party,
    `from . import …` relative)."""
    if isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            # Relative import — `from .foo import x`. Follow only
            # if it resolves into a tracked package; we conservatively
            # ignore here because relative imports stay within their
            # own package and don't cross layers.
            return None
        if not node.module:
            return None
        return node.module.split(".", 1)[0]
    # ast.Import — `import core.config` etc.
    if not node.names:
        return None
    return node.names[0].name.split(".", 1)[0]


def _is_type_checking_block(stmt: ast.stmt) -> bool:
    """Recognises `if TYPE_CHECKING:` so we can skip type-only
    imports."""
    if not isinstance(stmt, ast.If):
        return False
    test = stmt.test
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    return False


def _walk_imports(tree: ast.Module):
    """Yield (lineno, ImportNode) for every import outside
    `if TYPE_CHECKING` blocks. Walks nested function bodies too —
    a lazy import inside a function still creates a runtime edge.
    """

    def visit(body: list[ast.stmt]):
        for stmt in body:
            if _is_type_checking_block(stmt):
                continue
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                yield stmt
            # Recurse into anything that has a body.
            for attr in ("body", "orelse", "finalbody"):
                inner = getattr(stmt, attr, None)
                if isinstance(inner, list):
                    yield from visit(inner)
            for handler in getattr(stmt, "handlers", []) or []:
                yield from visit(handler.body)

    yield from visit(tree.body)


def _audit_file(path: Path) -> list[str]:
    """Return a list of `relpath:lineno  imports X (tier A → tier B)`
    strings, one per upward-edge violation."""
    rel = path.relative_to(_API_ROOT)
    file_tier = _file_tier(rel)
    if file_tier is None:
        # File isn't in a tracked layer (e.g. _pulse_smoke_app.py
        # at the root) — skip.
        return []

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []

    out: list[str] = []
    for stmt in _walk_imports(tree):
        pkg = _imported_pkg(stmt)
        if pkg is None or pkg not in _PKG_TIER:
            continue
        imported_tier = _PKG_TIER[pkg]
        if imported_tier > file_tier:
            key = (str(rel), pkg)
            if key in ALLOWLIST:
                continue
            out.append(f"{rel}:{stmt.lineno}  imports `{pkg}` (tier {file_tier} → tier {imported_tier})")
    return out


def _audit_all() -> list[str]:
    findings: list[str] = []
    for path in _python_files():
        findings.extend(_audit_file(path))
    return findings


def test_no_upward_layer_imports():
    """No file in a lower tier imports from a higher tier.

    A `services/` file importing from `routers/` is the canonical
    smell: the service stops being a service the moment it depends
    on the FastAPI app object. Routers depend on services; services
    don't depend on routers.

    Same ratchet pattern as the prior audits.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_UPWARD_EDGES:
        new = n - BASELINE_UPWARD_EDGES
        layer_summary = "\n".join(f"  tier {tier}: {', '.join(pkgs)}" for tier, pkgs in _LAYERS)
        pytest.fail(
            f"{new} new upward layer-import edge(s) "
            f"(total now {n}, baseline {BASELINE_UPWARD_EDGES}):\n  "
            + "\n  ".join(sorted(findings)[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nLayer ordering (bottom → top):\n"
            + layer_summary
            + "\n\nA module at tier N may import only from tiers ≤ N.\n"
            "Fixes (in order of preference):\n"
            "  1. Move the imported helper down a tier so the call site\n"
            "     no longer needs the upward edge.\n"
            "  2. Extract the shared logic into a new helper at the\n"
            "     lower tier; both layers import it.\n"
            "  3. If genuinely architecturally required, add a key to\n"
            "     ALLOWLIST with a stated reason."
        )
    if n < BASELINE_UPWARD_EDGES:
        pytest.fail(
            f"Upward-edge count dropped from {BASELINE_UPWARD_EDGES} to {n}. 🎉 Update `BASELINE_UPWARD_EDGES` to {n}."
        )


def test_allowlist_entries_correspond_to_real_files():
    """Defensive: stale `ALLOWLIST` entries silently mask future
    regressions. Every (file, package) tuple must point at a real
    file."""
    real_files = {str(p.relative_to(_API_ROOT)) for p in _python_files()}
    stale = [k for k in ALLOWLIST if k[0] not in real_files]
    assert not stale, (
        f"Stale ALLOWLIST entries (file no longer exists): {stale}. "
        "Remove them so the allowlist reflects only currently-live "
        "exemptions."
    )


def test_layer_lookup_is_consistent():
    """Defensive: every package in `_LAYERS` should map to exactly
    one tier, and every tier should be unique. A typo that
    duplicated a package across two tiers would let upward edges
    through silently.
    """
    seen: dict[str, int] = {}
    for tier, pkgs in _LAYERS:
        for pkg in pkgs:
            assert pkg not in seen, (
                f"Package `{pkg}` appears in tier {seen[pkg]} and "
                f"tier {tier} — a package must belong to exactly one tier."
            )
            seen[pkg] = tier


def test_audit_recognises_documented_import_shapes():
    """Defensive: positive + negative AST fixtures. A regression
    in `_imported_pkg` or `_is_type_checking_block` would silently
    let upward edges through.
    """
    # `from routers.x import y` — package = "routers".
    src = "from routers.foo import bar\n"
    tree = ast.parse(src)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.ImportFrom)
    assert _imported_pkg(stmt) == "routers"

    # `import services.x` — package = "services".
    src = "import services.foo\n"
    tree = ast.parse(src)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Import)
    assert _imported_pkg(stmt) == "services"

    # `from . import x` — relative import, returns None (skipped).
    src = "from . import foo\n"
    tree = ast.parse(src)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.ImportFrom)
    assert _imported_pkg(stmt) is None

    # `if TYPE_CHECKING:` block recognised.
    src = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from routers.foo import bar\n"
    tree = ast.parse(src)
    # The `if` statement is body[1].
    assert _is_type_checking_block(tree.body[1])

    # Non-TYPE_CHECKING `if` not treated as such.
    src = "if True:\n    pass\n"
    tree = ast.parse(src)
    assert not _is_type_checking_block(tree.body[0])
