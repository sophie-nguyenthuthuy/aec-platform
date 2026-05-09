"""`==` against None/True/False audit.

The bug class
-------------
`x == None` is two characters longer than `x is None` AND
semantically different:
  * `is` checks object identity. There's exactly one `None` in
    the runtime, so `x is None` is unambiguous.
  * `==` calls `__eq__`. A class can implement `__eq__` to
    return True for `== None` (deliberately or by accident).
    The check then succeeds for objects that aren't actually
    None.

The same logic applies to `True` and `False`: there's exactly
one of each. `is True` and `is False` are unambiguous; `== True`
calls `__eq__` and any truthy-equality custom logic.

PEP 8 codifies this: "Comparisons to singletons like None should
always be done with is or is not, never the equality operators."

Ruff's E711 / E712 catch this; this audit ratchets in case the
rule is ever disabled or the check drifts.

What this audit checks
----------------------
AST walk over `apps/api/{core,db,middleware,models,routers,
schemas,services,workers}/*.py` plus `apps/worker/*.py`. For
every `ast.Compare`, find any comparator that is `Constant(None)`,
`Constant(True)`, or `Constant(False)` paired with an `==` or
`!=` operator. Flag the call.

What's NOT checked
------------------
- `is` / `is not` against the singletons — correct.
- `==` against arbitrary literals (`x == 0`, `s == "ok"`) —
  legitimate; we only flag the three singletons.
- Test files — out of scope.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_ROOT = _REPO_ROOT / "apps" / "api"
_SCAN_ROOTS: list[Path] = [
    _API_ROOT / "core",
    _API_ROOT / "db",
    _API_ROOT / "middleware",
    _API_ROOT / "models",
    _API_ROOT / "routers",
    _API_ROOT / "schemas",
    _API_ROOT / "services",
    _API_ROOT / "workers",
    _REPO_ROOT / "apps" / "worker",
]


# Today's baseline. Filled in on first run.
BASELINE_SINGLETON_EQ = 0


# Per-(file, line) allowlist. Each entry needs a stated reason.
ALLOWLIST: dict[tuple[str, int], str] = {
    # No entries today.
}


_SINGLETONS: tuple[object, ...] = (None, True, False)


def _scan_files() -> list[Path]:
    out: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts or "tests" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _is_singleton_constant(node: ast.expr) -> bool:
    """`Constant(None|True|False)`. Note: `True` and `False` are
    `Constant` with bool value; `None` is `Constant(None)`. Need
    to distinguish from `Constant(0)` / `Constant(1)` — Python's
    bool is a subclass of int but `Constant.value` preserves the
    bool type when the source was literal True/False.
    """
    if not isinstance(node, ast.Constant):
        return False
    val = node.value
    if val is None:
        return True
    return type(val) is bool


def _collect_offenders(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, comparator_repr) for every singleton-eq
    Compare in the tree."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # Compare's structure: `left op1 right1 op2 right2 …`.
        # Each sub-comparison is `<prev> <op> <right>` where prev
        # is `node.left` for the first sub-comparison and the
        # previous comparator for the rest.
        prev = node.left
        for op, right in zip(node.ops, node.comparators, strict=True):
            if isinstance(op, ast.Eq | ast.NotEq):
                for side in (prev, right):
                    if _is_singleton_constant(side):
                        val = side.value if isinstance(side, ast.Constant) else None
                        out.append((node.lineno, repr(val)))
                        break
            prev = right
    return out


def _scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    rel = path.relative_to(_REPO_ROOT).as_posix()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    findings: list[str] = []
    for line, val_repr in _collect_offenders(tree):
        if (rel, line) in ALLOWLIST:
            continue
        try:
            source_line = text.splitlines()[line - 1].strip()[:80]
        except IndexError:
            source_line = "<unknown>"
        findings.append(f"{rel}:{line}  [{val_repr}]  {source_line}")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_eq_against_singletons():
    """`x == None`, `x == True`, `x == False` should be `is` /
    `is not`. PEP 8: comparisons to singletons use identity, not
    equality.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_SINGLETON_EQ:
        new = n - BASELINE_SINGLETON_EQ
        pytest.fail(
            f"{new} new `==` against None/True/False "
            f"(total now {n}, baseline {BASELINE_SINGLETON_EQ}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace with `is`:\n"
            "    # was:\n"
            "    if x == None: ...\n"
            "    if flag == True: ...\n"
            "    # use:\n"
            "    if x is None: ...\n"
            "    if flag: ...           # truthy is usually intended\n"
            "    if flag is True: ...   # exact-True if needed\n\n"
            "PEP 8: comparisons to singletons should use `is` / "
            "`is not`. Object identity bypasses any custom "
            "`__eq__` override; equality calls it."
        )
    if n < BASELINE_SINGLETON_EQ:
        pytest.fail(
            f"Singleton-eq count dropped from {BASELINE_SINGLETON_EQ} "
            f"to {n}. 🎉 Update `BASELINE_SINGLETON_EQ` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative AST fixtures."""
    # Positive: == None.
    pos1 = ast.parse("x == None\n")
    assert _collect_offenders(pos1) == [(1, "None")]

    # Positive: != True.
    pos2 = ast.parse("flag != True\n")
    assert _collect_offenders(pos2) == [(1, "True")]

    # Positive: None == x (left side).
    pos3 = ast.parse("None == x\n")
    assert _collect_offenders(pos3) == [(1, "None")]

    # Positive: chained — `x == None == y`. Both sub-comparisons
    # involve None.
    pos4 = ast.parse("x == None == y\n")
    assert len(_collect_offenders(pos4)) == 2

    # Negative: `is None`.
    neg1 = ast.parse("x is None\n")
    assert _collect_offenders(neg1) == []

    # Negative: `== 0` (numeric, not singleton).
    neg2 = ast.parse("count == 0\n")
    assert _collect_offenders(neg2) == []

    # Negative: `== 1` — bool != int. `1 == True` is True at runtime
    # but the audit only flags `Constant(value=True)` (bool type),
    # not `Constant(value=1)` (int type).
    neg3 = ast.parse("count == 1\n")
    assert _collect_offenders(neg3) == []
