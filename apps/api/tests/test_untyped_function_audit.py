"""Untyped function-signature audit.

The bug class
-------------
Functions in `routers/` and `services/` are the API surface
between the inbound request and the database. A missing
type annotation:

    def list_projects(db, org_id):  # <-- both untyped
        ...

means:

  * Refactors that change the inbound shape don't surface as
    typecheck errors. A caller updating one route's request
    schema can silently break a service helper because mypy
    can't see the connection.

  * Reviewers can't tell at a glance whether `org_id` is a
    `UUID`, a `str`, or a `tuple[UUID, ...]`. They have to
    chase the call sites.

  * IDE autocomplete on `db.<TAB>` returns junk because mypy
    has no idea `db` is `AsyncSession`.

The fix is one annotation per arg + one return type:

    async def list_projects(
        db: AsyncSession, org_id: UUID
    ) -> list[Project]:
        ...

What this audit checks
----------------------
AST walk over `apps/api/routers/*.py` plus `apps/api/services/*.py`.
For every top-level function (sync or async) AND every method on a
class, count:

  * Args without annotations (excluding `self` / `cls` / `*args` /
    `**kwargs`).
  * Missing return annotation.

The returned baseline is the SUM of all unannotated arg slots
plus all missing return annotations. Each slot ratchets independently:
adding a typed function reduces the count; adding an untyped
function increases it.

What's NOT checked
------------------
- Test files (`tests/**`) — out of scope.
- Inner functions inside another function — the audit only
  walks module-level + class-method functions.
- Lambda expressions.
- `*args` / `**kwargs` — convention varies; mypy handles them
  via `*args: Any` if you really want it.

Allowlist
---------
Per-(file, function name) for legitimate cases. Each entry needs
a stated reason. Keep narrow — the dominant case is "type me."

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = [_API_ROOT / "routers", _API_ROOT / "services"]


# Today's baseline. Filled in on first run.
BASELINE_UNTYPED_SLOTS = 39  # 2026-05: 58 → 56 → 39 after further typing passes across routers/services


# Per-(relative_path, function_name) allowlist. Each entry needs
# a stated reason. An empty rationale silences the gate.
ALLOWLIST: dict[tuple[str, str], str] = {
    # No entries today. The 204-DELETE handlers that previously
    # lived here (punchlist::delete_item, schedulepilot::
    # {delete_activity, delete_dependency}) now declare
    # `response_model=None` on the decorator — which suppresses
    # FastAPI's response-model inference from the return annotation —
    # and carry an explicit `-> None`. Same handler behaviour, slot
    # now countably typed. (The webhooks::delete_webhook handler
    # was never in this allowlist because it returned `None` literals
    # rather than implicit-None; it got the same treatment for
    # consistency and because `-> None` would otherwise trip the same
    # FastAPI startup check.)
}


def _walk_python_files() -> list[Path]:
    out: list[Path] = []
    for d in _SCAN_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _count_untyped_slots(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Per function, count:
      * `args.args` without annotation (excluding self/cls)
      * `args.kwonlyargs` without annotation
      * `args.posonlyargs` without annotation
      * Missing return annotation (the `-> X` part)

    `*args` / `**kwargs` aren't counted.
    """
    count = 0
    args = func.args
    # Positional + keyword-or-positional args.
    for i, arg in enumerate(args.args):
        if i == 0 and arg.arg in ("self", "cls"):
            continue
        if arg.annotation is None:
            count += 1
    for arg in args.kwonlyargs:
        if arg.annotation is None:
            count += 1
    for arg in args.posonlyargs:
        if arg.annotation is None:
            count += 1
    # Return annotation. Missing on `__init__` is conventional
    # (returns None implicitly); skip it.
    if func.returns is None and func.name != "__init__":
        count += 1
    return count


def _walk_audited_functions(tree: ast.Module):
    """Yield every function definition we care about: top-level
    + class methods. Inner functions and lambdas skipped."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield child


def _audit_one_file(path: Path) -> list[tuple[str, str, int]]:
    """Return [(rel_path, func_name, untyped_count)] for every
    function with at least one untyped slot."""
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    rel = str(path.relative_to(_API_ROOT))
    out: list[tuple[str, str, int]] = []
    for func in _walk_audited_functions(tree):
        if (rel, func.name) in ALLOWLIST:
            continue
        n = _count_untyped_slots(func)
        if n > 0:
            out.append((rel, func.name, n))
    return out


def _audit_all() -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    for path in _walk_python_files():
        out.extend(_audit_one_file(path))
    return out


def test_untyped_function_slot_count_does_not_grow():
    """Walk every router + service function; sum of unannotated
    arg slots + missing return annotations should not exceed the
    pinned baseline.

    Failures surface both ratchet directions.
    """
    findings = _audit_all()
    n = sum(count for _, _, count in findings)
    if n > BASELINE_UNTYPED_SLOTS:
        new = n - BASELINE_UNTYPED_SLOTS
        # Show the top-N functions by untyped count for fastest
        # remediation: type the chunkiest first.
        top = sorted(findings, key=lambda r: -r[2])[:20]
        rendered = [f"{rel}::{name}  ({c} slot(s))" for rel, name, c in top]
        pytest.fail(
            f"{new} new untyped slot(s) "
            f"(total now {n}, baseline {BASELINE_UNTYPED_SLOTS}). "
            f"Top {len(top)} offenders by slot count:\n  "
            + "\n  ".join(rendered)
            + (f"\n  … {len(findings) - len(top)} more functions" if len(findings) > len(top) else "")
            + "\n\nFix patterns:\n"
            "    # was:\n"
            "    def list_projects(db, org_id):\n"
            "        ...\n"
            "    # use:\n"
            "    async def list_projects(\n"
            "        db: AsyncSession, org_id: UUID\n"
            "    ) -> list[Project]:\n"
            "        ...\n\n"
            "Each unannotated arg + each missing return type counts "
            "as one slot. The audit is a sum, so typing one chunky "
            "function with 5 args + missing return is worth 6 slots.\n\n"
            "If a function genuinely can't be typed (dynamic dispatch, "
            "pre-typed third-party callable), add to ALLOWLIST with a "
            "stated reason."
        )
    if n < BASELINE_UNTYPED_SLOTS:
        pytest.fail(
            f"Untyped-slot count dropped from {BASELINE_UNTYPED_SLOTS} "
            f"to {n}. 🎉 Update `BASELINE_UNTYPED_SLOTS` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative AST fixtures."""
    # Positive: untyped args + missing return.
    pos = ast.parse("def f(a, b, c=1): return a + b + c\n")
    fn = pos.body[0]
    assert isinstance(fn, ast.FunctionDef)
    # 3 untyped args + 1 missing return = 4 slots.
    assert _count_untyped_slots(fn) == 4

    # Negative: fully typed.
    neg = ast.parse("def g(a: int, b: int) -> int: return a + b\n")
    fn = neg.body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert _count_untyped_slots(fn) == 0

    # Self / cls don't count.
    cls = ast.parse(
        "class C:\n"
        "    def m(self, x: int) -> int:\n"
        "        return x\n"
        "    @classmethod\n"
        "    def c(cls, x: int) -> int:\n"
        "        return x\n"
    )
    cls_def = cls.body[0]
    assert isinstance(cls_def, ast.ClassDef)
    for child in cls_def.body:
        if isinstance(child, ast.FunctionDef):
            assert _count_untyped_slots(child) == 0

    # `__init__` without `-> None` is fine (conventional).
    init = ast.parse("class D:\n    def __init__(self, x: int):\n        self.x = x\n")
    cls_def = init.body[0]
    assert isinstance(cls_def, ast.ClassDef)
    init_fn = cls_def.body[0]
    assert isinstance(init_fn, ast.FunctionDef)
    assert _count_untyped_slots(init_fn) == 0

    # Async def works.
    asyn = ast.parse("async def f(x): return x\n")
    fn = asyn.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    # 1 untyped arg + 1 missing return = 2.
    assert _count_untyped_slots(fn) == 2


def test_allowlist_entries_actually_correspond_to_real_functions():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions.
    """
    if not ALLOWLIST:
        return
    real_keys: set[tuple[str, str]] = set()
    for path in _walk_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        rel = str(path.relative_to(_API_ROOT))
        for func in _walk_audited_functions(tree):
            real_keys.add((rel, func.name))
    stale = [k for k in ALLOWLIST if k not in real_keys]
    assert not stale, f"Stale ALLOWLIST entries: {stale}."
