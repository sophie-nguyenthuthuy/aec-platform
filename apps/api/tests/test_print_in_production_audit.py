"""`print(...)` in production code audit.

The bug class
-------------
A `print(...)` call left over from debugging:

    async def submit_proposal(payload):
        print("DEBUG payload =", payload)  # <-- forgot to remove
        ...

Three real costs:

1. **Log discipline.** Production logs ship to centralised
   aggregation (Sentry, Datadog, CloudWatch). `print()` writes
   to stdout but bypasses the logger config — no level filtering,
   no JSON formatting, no request-ID correlation. The line still
   shows up in the runner's stdout but nobody is searching there.

2. **Sensitive data in stdout.** The example above prints the
   full request payload. If the runner's stdout is mirrored to
   any persistence (k8s pod logs, Docker logs, CI artifacts),
   the payload — possibly including PII or auth headers — leaks
   to anyone with cluster log access.

3. **Performance under high QPS.** `print()` flushes synchronously
   by default, blocking the event loop. A debug print inside a
   request handler at 100 RPS is 100 sync writes per second on
   the same goroutine.

The fix is one substitution: `logger.info(...)` (or `.debug` /
`.warning` etc.) instead of `print(...)`. Every router /
service / worker module already imports a module-level
`logger = logging.getLogger(__name__)`.

What this audit checks
----------------------
AST walk over `apps/api/{core,db,middleware,models,routers,
schemas,services,workers}/*.py` plus `apps/worker/*.py`. Flag
every top-level function call to `print` (i.e. `ast.Call` with
`func=ast.Name(id="print")`).

What's NOT checked
------------------
- `tests/` — print is occasionally legitimate in test fixtures
  for debugging.
- `scripts/` — CLI tools (e.g. seed-demo) use print to surface
  output to the operator running them.
- Alembic migrations — same logic as scripts.
- `obj.print(...)` (attribute call) — unrelated.

Allowlist
---------
Per-(file, line) entries for legitimate cases:
  * Operator-facing surfaces (a CLI mode in a production module
    that prints help/version when run directly).

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
BASELINE_PRODUCTION_PRINTS = 4  # 2026-05: first-run baseline (services/price_scrapers/probe.py is a CLI in disguise; operator-facing prints); ratchet down by moving probe.py to scripts/ or migrating to logger


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
            # Test files — print is occasionally legitimate.
            if "tests" in p.parts:
                continue
            # Scripts — CLI tools surface output via print.
            if "scripts" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _is_print_call(node: ast.AST) -> bool:
    """Match a bare `print(...)` call. `obj.print(...)` doesn't
    count — print as an attribute is unrelated.
    """
    if not isinstance(node, ast.Call):
        return False
    return isinstance(node.func, ast.Name) and node.func.id == "print"


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
        if not _is_print_call(node):
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


def test_no_print_calls_in_production_code():
    """Every `print(...)` in production code should be a logger
    call instead — print bypasses log levels, structured
    formatting, and request-ID correlation.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_PRODUCTION_PRINTS:
        new = n - BASELINE_PRODUCTION_PRINTS
        pytest.fail(
            f"{new} new `print(...)` call(s) in production code "
            f"(total now {n}, baseline {BASELINE_PRODUCTION_PRINTS}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace with the module logger:\n"
            "    # was:\n"
            "    print(f'received {payload}')\n"
            "    # use:\n"
            "    logger.info('received payload', extra={'payload': payload})\n\n"
            "Every router/service/worker module already has a "
            "module-level `logger = logging.getLogger(__name__)`. "
            "Logger calls are level-filtered, JSON-structured, and "
            "carry the request-ID middleware injects.\n\n"
            "If a print is genuinely operator-facing (CLI help "
            "output, etc.), add it to ALLOWLIST with that as the "
            "stated reason."
        )
    if n < BASELINE_PRODUCTION_PRINTS:
        pytest.fail(
            f"Production-print count dropped from "
            f"{BASELINE_PRODUCTION_PRINTS} to {n}. 🎉 Update "
            f"`BASELINE_PRODUCTION_PRINTS` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative fixtures."""
    # Positive: bare print call.
    pos = ast.parse("print('hi')\n")
    calls = [n for n in ast.walk(pos) if _is_print_call(n)]
    assert len(calls) == 1

    # Positive: print with multiple args + kwargs.
    pos2 = ast.parse("print('a', 'b', sep='-', file=sys.stderr)\n")
    calls = [n for n in ast.walk(pos2) if _is_print_call(n)]
    assert len(calls) == 1

    # Negative: attribute call.
    neg = ast.parse("printer.print('hi')\n")
    calls = [n for n in ast.walk(neg) if _is_print_call(n)]
    assert calls == []

    # Negative: print as identifier reference (not a call).
    neg2 = ast.parse("fn = print\n")
    calls = [n for n in ast.walk(neg2) if _is_print_call(n)]
    assert calls == []

    # Negative: logger.info.
    neg3 = ast.parse("logger.info('hi')\n")
    calls = [n for n in ast.walk(neg3) if _is_print_call(n)]
    assert calls == []


def test_allowlist_entries_actually_correspond_to_real_prints():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions.
    """
    if not ALLOWLIST:
        return
    real_prints: set[tuple[str, int]] = set()
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
            if _is_print_call(node):
                real_prints.add((rel, node.lineno))
    stale = [k for k in ALLOWLIST if k not in real_prints]
    assert not stale, f"Stale ALLOWLIST entries: {stale}."
