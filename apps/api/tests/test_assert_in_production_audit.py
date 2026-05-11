"""`assert` in production code audit.

The bug class
-------------
Python's `-O` flag (and the `PYTHONOPTIMIZE` env var) STRIPS
every `assert` statement at compile time. In production with
`-O` set, runtime checks written as asserts silently no-op:

    def transfer(amount: int):
        assert amount > 0  # vanishes under -O
        ...

If `amount=-1` slips through, the original author trusted the
assert to catch it. With `-O` it doesn't, the negative amount
flows downstream, and the bug surfaces somewhere unrelated.

The fix shape: convert runtime checks to explicit raises:

    def transfer(amount: int):
        if amount <= 0:
            raise ValueError("amount must be positive")
        ...

What this audit checks
----------------------
AST walk over `apps/api/{routers,services,workers,middleware,
core,db}/*.py`. Flag every `ast.Assert` node.

What's NOT checked
------------------
- Models / schemas — Pydantic / SQLAlchemy mostly use
  `model_validator` raises, not asserts. (Walked anyway; the
  audit just expects 0 in there.)
- Test files — asserts ARE the test contract; they're the WHOLE
  POINT of `pytest`.
- Alembic migrations — out of scope.

Allowlist
---------
Per-(file, line) entries for legitimate cases:
  * `assert isinstance(...)` for type-narrowing in code paths
    where the type is structurally guaranteed and the assert is
    purely for the static type-checker. These are common after
    deserialisation; mark explicitly.

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
BASELINE_PRODUCTION_ASSERTS = 8  # 2026-05: first-run baseline (mostly `assert job is not None` type-narrows after arq.enqueue_job); ratchet down by migrating to ALLOWLIST or explicit raise


# Per-(relative_posix_path, line) allowlist. Each entry needs a
# stated reason. An empty rationale silences the gate.
ALLOWLIST: dict[tuple[str, int], str] = {
    # No entries today.
}


def _scan_files() -> list[Path]:
    out: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            # Test files — asserts ARE the test contract.
            # `apps/worker/tests/` is reachable from `apps/worker`
            # rglob; exclude here.
            if "tests" in p.parts:
                continue
            out.append(p)
    return sorted(out)


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
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        line = node.lineno
        if (rel, line) in ALLOWLIST:
            continue
        # Surface the assert's source line to make the failure
        # message actionable.
        try:
            source_line = text.splitlines()[line - 1].strip()[:80]
        except IndexError:
            source_line = "<unknown>"
        findings.append(f"{rel}:{line}  {source_line}")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_assert_statements_in_production_code():
    """Every runtime check written as `assert ...` should be a
    proper `raise` instead — Python's `-O` strips asserts.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_PRODUCTION_ASSERTS:
        new = n - BASELINE_PRODUCTION_ASSERTS
        pytest.fail(
            f"{new} new `assert` in production code "
            f"(total now {n}, baseline {BASELINE_PRODUCTION_ASSERTS}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace with an explicit raise:\n"
            "    # was:\n"
            "    assert amount > 0\n"
            "    # use:\n"
            "    if amount <= 0:\n"
            "        raise ValueError('amount must be positive')\n\n"
            "Python's `-O` flag strips asserts at compile time. The "
            "check that worked locally vanishes in any prod runtime "
            "that sets `-O` or `PYTHONOPTIMIZE`, and the wrapped "
            "value silently flows downstream.\n\n"
            "If the assert is purely for static-type narrowing "
            "(`assert isinstance(x, Foo)` after deserialisation), "
            "add it to ALLOWLIST with that as the stated reason."
        )
    if n < BASELINE_PRODUCTION_ASSERTS:
        pytest.fail(
            f"Production-assert count dropped from "
            f"{BASELINE_PRODUCTION_ASSERTS} to {n}. 🎉 Update "
            f"`BASELINE_PRODUCTION_ASSERTS` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative fixtures."""
    # Positive: plain assert.
    pos = ast.parse("def f(x):\n    assert x > 0\n")
    asserts = [n for n in ast.walk(pos) if isinstance(n, ast.Assert)]
    assert len(asserts) == 1

    # Positive: assert with message.
    pos2 = ast.parse("def g(x):\n    assert x > 0, 'x must be positive'\n")
    asserts = [n for n in ast.walk(pos2) if isinstance(n, ast.Assert)]
    assert len(asserts) == 1

    # Negative: `if … raise …` is fine.
    neg = ast.parse("def h(x):\n    if x <= 0:\n        raise ValueError('bad')\n")
    asserts = [n for n in ast.walk(neg) if isinstance(n, ast.Assert)]
    assert asserts == []


def test_allowlist_entries_actually_correspond_to_real_asserts():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions.
    """
    if not ALLOWLIST:
        return
    real_asserts: set[tuple[str, int]] = set()
    for path in _scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                real_asserts.add((rel, node.lineno))
    stale = [k for k in ALLOWLIST if k not in real_asserts]
    assert not stale, f"Stale ALLOWLIST entries: {stale}."
