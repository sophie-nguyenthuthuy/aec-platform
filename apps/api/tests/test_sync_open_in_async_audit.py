"""Sync `open()` inside `async def` audit.

The bug class
-------------
Standard library `open(...)` is synchronous. Calling it inside
an `async def` blocks the event loop while the kernel does the
file syscall:

    @router.post("/upload")
    async def upload(file: UploadFile):
        with open(f"/tmp/{file.filename}", "wb") as f:  # <-- blocks
            f.write(await file.read())

For a 1KB file it's microseconds and invisible. For a 50MB
upload on a slow disk it's seconds — and during those seconds
the entire event loop stalls. Every other in-flight request
is paused. Every health check past its timeout is killed by
k8s. The pod's "available" status flips to "not ready" mid-
upload, the load balancer pulls it, the upload finishes, the
pod recovers — but the operator sees a confusing health-flap.

Fix shapes:

  1. **`aiofiles.open(...)`** — drop-in async file context
     manager:

         async with aiofiles.open(path, "wb") as f:
             await f.write(data)

  2. **`asyncio.to_thread(...)`** — offload the sync call to
     the thread pool:

         await asyncio.to_thread(_write_sync, path, data)

What this audit checks
----------------------
AST walk over `apps/api/{routers,services,workers,middleware,
core,db}/*.py` plus `apps/worker/*.py`. For every `async def`
function, find every `open(...)` call (bare `Name(id="open")`)
in its body. Recurse through loops + comprehensions but NOT
through nested function defs.

What's NOT checked
------------------
- `aiofiles.open(...)` — async; safe.
- `obj.open(...)` (attribute) — unrelated method.
- Sync `def` functions — they're allowed to block. The bug
  shape is sync-blocking-inside-async-context.
- Test files — out of scope.

Allowlist
---------
Per-(file, line) entries for legitimate cases (rare — usually
boot-time config loading inside an async startup hook where the
file is small enough that the block is negligible). Each needs
a stated reason.

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
BASELINE_SYNC_OPEN_IN_ASYNC = 2  # 2026-05: first-run baseline (drawbridge upload write + probe.py CLI _main); ratchet down by migrating to aiofiles


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
            if "tests" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _is_sync_open_call(node: ast.AST) -> bool:
    """Match `open(...)` — bare Name, not attribute. Excludes
    `aiofiles.open(...)`, `obj.open(...)` etc."""
    if not isinstance(node, ast.Call):
        return False
    return isinstance(node.func, ast.Name) and node.func.id == "open"


def _collect_sync_opens_in_async_function(
    func: ast.AsyncFunctionDef,
) -> list[int]:
    """Return line numbers of every `open(...)` call inside
    `func`'s body. Doesn't descend into nested function defs
    (sync or async) — those have their own audit scope.
    """
    lines: list[int] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            return
        if _is_sync_open_call(node):
            lines.append(node.lineno)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for stmt in func.body:
        visit(stmt)
    return lines


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
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for line in _collect_sync_opens_in_async_function(node):
            if (rel, line) in ALLOWLIST:
                continue
            try:
                source_line = text.splitlines()[line - 1].strip()[:80]
            except IndexError:
                source_line = "<unknown>"
            findings.append(f"{rel}:{line}  in `{node.name}`  {source_line}")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_sync_open_in_async_function():
    """Sync `open(...)` inside `async def` blocks the event
    loop. Use `aiofiles.open(...)` or `asyncio.to_thread(...)`
    instead.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_SYNC_OPEN_IN_ASYNC:
        new = n - BASELINE_SYNC_OPEN_IN_ASYNC
        pytest.fail(
            f"{new} new sync `open(...)` call(s) inside async functions "
            f"(total now {n}, baseline {BASELINE_SYNC_OPEN_IN_ASYNC}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nFix patterns:\n"
            "  • `async with aiofiles.open(path, 'rb') as f:`  — drop-in async\n"
            "  • `await asyncio.to_thread(_sync_helper, path)` — offload to threadpool\n\n"
            "Sync `open()` in an async path holds the event loop for "
            "the duration of the disk I/O. For small reads it's "
            "invisible; for a 50MB upload on a slow disk it's seconds, "
            "and every other request on the same worker stalls.\n\n"
            "If the read is genuinely tiny + boot-time (loading a "
            "config file in startup), add to ALLOWLIST with that "
            "as the stated reason."
        )
    if n < BASELINE_SYNC_OPEN_IN_ASYNC:
        pytest.fail(
            f"Sync-open-in-async count dropped from "
            f"{BASELINE_SYNC_OPEN_IN_ASYNC} to {n}. 🎉 Update "
            f"`BASELINE_SYNC_OPEN_IN_ASYNC` to {n}."
        )


def test_audit_recognises_documented_patterns():
    """Defensive: positive + negative AST fixtures."""
    # Positive: `with open(...)` inside async def.
    pos = ast.parse("async def f(path):\n    with open(path) as fh:\n        return fh.read()\n")
    fn = pos.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    lines = _collect_sync_opens_in_async_function(fn)
    assert len(lines) == 1, f"Expected 1, got {lines}"

    # Positive: `open(path).read()` inline.
    pos2 = ast.parse("async def g(path):\n    return open(path).read()\n")
    fn = pos2.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    lines = _collect_sync_opens_in_async_function(fn)
    assert len(lines) == 1

    # Negative: `aiofiles.open(...)` — attribute call.
    neg = ast.parse(
        "import aiofiles\n"
        "async def h(path):\n"
        "    async with aiofiles.open(path) as fh:\n"
        "        return await fh.read()\n"
    )
    fn = neg.body[1]
    assert isinstance(fn, ast.AsyncFunctionDef)
    lines = _collect_sync_opens_in_async_function(fn)
    assert lines == []

    # Negative: `open()` in sync `def` — out of scope.
    neg2 = ast.parse("def k(path):\n    return open(path).read()\n")
    # We don't pass sync-def into the helper; the audit's caller
    # filters by AsyncFunctionDef. Just confirm the scan-loop
    # only walks AsyncFunctionDef.
    async_funcs = [n for n in ast.walk(neg2) if isinstance(n, ast.AsyncFunctionDef)]
    assert async_funcs == []

    # Negative: nested function — `open()` inside an inner sync
    # `def` shouldn't be counted against the outer `async def`.
    nested = ast.parse("async def outer():\n    def inner(path):\n        return open(path).read()\n    return inner\n")
    fn = nested.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    lines = _collect_sync_opens_in_async_function(fn)
    assert lines == [], f"Audit descended into nested def: {lines}"


def test_allowlist_entries_actually_correspond_to_real_calls():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions.
    """
    if not ALLOWLIST:
        return
    real_calls: set[tuple[str, int]] = set()
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
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for line in _collect_sync_opens_in_async_function(node):
                real_calls.add((rel, line))
    stale = [k for k in ALLOWLIST if k not in real_calls]
    assert not stale, f"Stale ALLOWLIST entries: {stale}."
