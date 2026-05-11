"""`datetime.fromtimestamp(x)` without `tz=` audit.

The bug class
-------------
`datetime.fromtimestamp(unix_seconds)` returns a NAIVE datetime
in the LOCAL timezone of the host. Two compounding problems:

1. **Naive.** Same problem as `datetime.utcnow()` — caught by
   `test_naive_datetime_audit.py`. Mixed comparison with
   timezone-aware datetimes raises TypeError at runtime.

2. **Local time.** Two services running on hosts in different
   timezones — or the same host before/after a DST change —
   produce different datetimes for the same unix_seconds input.
   A row written on a UTC container and a row written on a
   non-UTC laptop look like they were written at different
   wall-clock times. Sort order silently scrambles.

Fix: pass `tz=UTC` (or any explicit timezone). The result is
both timezone-aware AND consistent across hosts:

    dt = datetime.fromtimestamp(unix_seconds, tz=UTC)

This is the documented modern API; Python 3.12+ deprecates
`datetime.utcfromtimestamp(x)` in favor of
`datetime.fromtimestamp(x, UTC)`.

What this audit checks
----------------------
AST walk over `apps/api/{core,db,middleware,models,routers,
schemas,services,workers}/*.py` plus `apps/worker/*.py`. Flag
every `datetime.fromtimestamp(<x>)` call that doesn't have a
`tz=` keyword OR a second positional argument.

Sister of `test_naive_datetime_audit.py` (which catches
`utcnow()` + zero-arg `now()`). Together they cover the three
ways to accidentally produce a naive datetime in stdlib.

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
BASELINE_NAIVE_FROMTIMESTAMP = 0


# Per-(file, line) allowlist. Each entry needs a stated reason.
ALLOWLIST: dict[tuple[str, int], str] = {
    # No entries today.
}


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


def _is_naive_fromtimestamp(node: ast.AST) -> bool:
    """`datetime.fromtimestamp(x)` / `dt.fromtimestamp(x)` with
    no `tz=` keyword AND no second positional. Returns True if
    naive, False if explicit-tz form OR not a fromtimestamp call.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "fromtimestamp":
        return False
    recv = func.value
    if not isinstance(recv, ast.Name) or recv.id not in ("datetime", "dt"):
        return False
    # Has explicit `tz=` keyword?
    if any(kw.arg == "tz" for kw in node.keywords):
        return False
    # Second positional arg (the tz)?
    if len(node.args) >= 2:
        return False
    return True


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
        if not _is_naive_fromtimestamp(node):
            continue
        line = node.lineno
        if (rel, line) in ALLOWLIST:
            continue
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


def test_no_naive_fromtimestamp_calls():
    """Every `datetime.fromtimestamp(x)` should pass `tz=UTC`
    (or another explicit timezone). The bare form returns a
    naive datetime in LOCAL time — silently host-dependent.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_NAIVE_FROMTIMESTAMP:
        new = n - BASELINE_NAIVE_FROMTIMESTAMP
        pytest.fail(
            f"{new} new naive `datetime.fromtimestamp(...)` call(s) "
            f"(total now {n}, baseline {BASELINE_NAIVE_FROMTIMESTAMP}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace with the timezone-aware form:\n"
            "    # was:\n"
            "    datetime.fromtimestamp(unix_seconds)\n"
            "    # use:\n"
            "    datetime.fromtimestamp(unix_seconds, tz=UTC)\n\n"
            "The bare form returns a naive datetime in LOCAL time. "
            "Two hosts in different timezones (or the same host "
            "before/after a DST change) produce different datetimes "
            "for the same input — sort order silently scrambles."
        )
    if n < BASELINE_NAIVE_FROMTIMESTAMP:
        pytest.fail(
            f"Naive-fromtimestamp count dropped from "
            f"{BASELINE_NAIVE_FROMTIMESTAMP} to {n}. 🎉 Update "
            f"`BASELINE_NAIVE_FROMTIMESTAMP` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative AST fixtures."""
    # Positive: bare fromtimestamp.
    pos = ast.parse("datetime.fromtimestamp(1234567890)\n")
    calls = [n for n in ast.walk(pos) if _is_naive_fromtimestamp(n)]
    assert len(calls) == 1

    # Positive: dt-aliased.
    pos2 = ast.parse("dt.fromtimestamp(x)\n")
    calls = [n for n in ast.walk(pos2) if _is_naive_fromtimestamp(n)]
    assert len(calls) == 1

    # Negative: tz= keyword.
    neg = ast.parse("datetime.fromtimestamp(x, tz=UTC)\n")
    calls = [n for n in ast.walk(neg) if _is_naive_fromtimestamp(n)]
    assert calls == []

    # Negative: positional tz arg.
    neg2 = ast.parse("datetime.fromtimestamp(x, UTC)\n")
    calls = [n for n in ast.walk(neg2) if _is_naive_fromtimestamp(n)]
    assert calls == []

    # Negative: unrelated `obj.fromtimestamp` (not on datetime/dt).
    neg3 = ast.parse("custom.fromtimestamp(x)\n")
    calls = [n for n in ast.walk(neg3) if _is_naive_fromtimestamp(n)]
    assert calls == []
