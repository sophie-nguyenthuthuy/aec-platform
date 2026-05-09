"""`requests.<verb>(...)` (or other sync HTTP) in async function audit.

The bug class
-------------
The `requests` library is synchronous. Calling
`requests.get(...)` inside an `async def` blocks the event loop
until the HTTP round trip completes:

    @router.post("/proxy")
    async def proxy(url: str):
        r = requests.get(url, timeout=10)  # <-- blocks ~100ms-10s
        return r.json()

Same shape as the `sync open()` audit — during the block, every
other in-flight request on the same worker stalls. With a slow
upstream (or a network blip), the stall is seconds.

Sister audits:
  * `urllib.request.urlopen(...)` — same problem, different lib.
  * `http.client.HTTPConnection(...)` — same problem.

Fix shapes:
  * `await httpx.AsyncClient().get(url)` — already used elsewhere
    in this codebase.
  * `await asyncio.to_thread(requests.get, url)` — offload to
    threadpool if the sync API is required (e.g. a SDK that
    only ships sync).

What this audit checks
----------------------
AST walk over `apps/api/{routers,services,workers,middleware,
core,db}/*.py` plus `apps/worker/*.py`. For every `async def`,
walk the body for:
  * `requests.<verb>(...)` where verb ∈ standard HTTP set.
  * `urllib.request.urlopen(...)`.

Doesn't descend into nested functions (sync helpers inside
async are someone else's problem).

What's NOT checked
------------------
- `httpx.AsyncClient(...).get(...)` — async; safe.
- `aiohttp.ClientSession(...).get(...)` — async; safe.
- `requests.<verb>(...)` in sync `def` — they're allowed to
  block.
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
BASELINE_SYNC_HTTP_IN_ASYNC = 0


# Per-(file, line) allowlist. Each entry needs a stated reason.
ALLOWLIST: dict[tuple[str, int], str] = {
    # No entries today.
}


_HTTP_VERBS: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "request", "session", "Session"}
)


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


def _is_sync_http_call(node: ast.AST) -> str | None:
    """Match `requests.<verb>(...)` or `urllib.request.urlopen(...)`.
    Returns a label (`"requests.get"` etc.) on match, else None.
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    # `requests.<verb>(...)`: receiver is a bare Name `requests`.
    if isinstance(func.value, ast.Name) and func.value.id == "requests":
        if func.attr in _HTTP_VERBS:
            return f"requests.{func.attr}"
    # `urllib.request.urlopen(...)`: receiver is `urllib.request`.
    if (
        func.attr == "urlopen"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "request"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "urllib"
    ):
        return "urllib.request.urlopen"
    return None


def _collect_in_async_function(func: ast.AsyncFunctionDef) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            return
        label = _is_sync_http_call(node)
        if label is not None:
            out.append((node.lineno, label))
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for stmt in func.body:
        visit(stmt)
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
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for line, label in _collect_in_async_function(node):
            if (rel, line) in ALLOWLIST:
                continue
            try:
                source_line = text.splitlines()[line - 1].strip()[:80]
            except IndexError:
                source_line = "<unknown>"
            findings.append(f"{rel}:{line}  in `{node.name}`  [{label}]  {source_line}")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_sync_http_in_async_function():
    """Sync `requests.<verb>(...)` / `urllib.request.urlopen(...)`
    inside an async function blocks the event loop. Use
    `httpx.AsyncClient` or `asyncio.to_thread` instead.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_SYNC_HTTP_IN_ASYNC:
        new = n - BASELINE_SYNC_HTTP_IN_ASYNC
        pytest.fail(
            f"{new} new sync HTTP call(s) inside async functions "
            f"(total now {n}, baseline {BASELINE_SYNC_HTTP_IN_ASYNC}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nFix patterns:\n"
            "  • httpx (already in this codebase):\n"
            "        async with httpx.AsyncClient() as c:\n"
            "            r = await c.get(url, timeout=10)\n"
            "  • Or offload sync to threadpool:\n"
            "        r = await asyncio.to_thread(requests.get, url)\n\n"
            "Sync HTTP in an async path holds the event loop for the "
            "round-trip duration. With a slow upstream, every other "
            "in-flight request on the worker stalls."
        )
    if n < BASELINE_SYNC_HTTP_IN_ASYNC:
        pytest.fail(
            f"Sync-HTTP-in-async count dropped from "
            f"{BASELINE_SYNC_HTTP_IN_ASYNC} to {n}. 🎉 Update "
            f"`BASELINE_SYNC_HTTP_IN_ASYNC` to {n}."
        )


def test_audit_recognises_documented_patterns():
    """Defensive: positive + negative AST fixtures."""
    # Positive: requests.get inside async.
    pos = ast.parse(
        "import requests\n"
        "async def f(url):\n"
        "    return requests.get(url).json()\n"
    )
    fn = pos.body[1]
    assert isinstance(fn, ast.AsyncFunctionDef)
    out = _collect_in_async_function(fn)
    assert len(out) == 1 and out[0][1] == "requests.get"

    # Positive: urllib.request.urlopen.
    pos2 = ast.parse(
        "import urllib.request\n"
        "async def g(url):\n"
        "    return urllib.request.urlopen(url).read()\n"
    )
    fn = pos2.body[1]
    assert isinstance(fn, ast.AsyncFunctionDef)
    out = _collect_in_async_function(fn)
    assert len(out) == 1 and out[0][1] == "urllib.request.urlopen"

    # Negative: httpx.AsyncClient.
    neg = ast.parse(
        "import httpx\n"
        "async def h(url):\n"
        "    async with httpx.AsyncClient() as c:\n"
        "        return await c.get(url)\n"
    )
    fn = neg.body[1]
    assert isinstance(fn, ast.AsyncFunctionDef)
    out = _collect_in_async_function(fn)
    assert out == []

    # Negative: requests.get in sync def — out of audit scope.
    neg2 = ast.parse(
        "import requests\n"
        "def k(url):\n"
        "    return requests.get(url).json()\n"
    )
    async_funcs = [
        n for n in ast.walk(neg2) if isinstance(n, ast.AsyncFunctionDef)
    ]
    assert async_funcs == []

    # Negative: nested sync def inside async — sync's blocking
    # is the inner function's concern.
    nested = ast.parse(
        "import requests\n"
        "async def outer():\n"
        "    def inner(url):\n"
        "        return requests.get(url)\n"
        "    return inner\n"
    )
    fn = nested.body[1]
    assert isinstance(fn, ast.AsyncFunctionDef)
    out = _collect_in_async_function(fn)
    assert out == [], f"Audit descended into nested def: {out}"
