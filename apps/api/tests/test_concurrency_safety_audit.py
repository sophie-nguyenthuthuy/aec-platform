"""Concurrency-safety audit (`await` inside loop bodies).

The bug class
-------------
Inside an `async def` handler:

    for row in rows:
        result = await db.execute(text("SELECT … WHERE id = :id"),
                                  {"id": row.id})
        …

Each iteration awaits the previous query before issuing the next.
With 50 rows that's 50 sequential roundtrips. The right answer is
either:
  * Batch into one query: `WHERE id = ANY(:ids)`.
  * Fan out concurrently: `await asyncio.gather(*(_one(r) for r in rows))`.

The bug surfaces only at scale — in dev with 5 rows it's fast
enough that nobody notices; in prod once a tenant has 500 rows
the route hits a slow-query alarm. By then the call shape is
ossified and the fix touches several call sites.

What this audit checks
----------------------
AST walk over `apps/api/{routers,services}/*.py`. For every
`async def` function, look at every nested `for` / `async for`
/ `while` loop body. If the body contains an `await` expression,
flag it. Same ratchet pattern as the other audits.

False-positive shapes
---------------------
1. **Background fan-out via `asyncio.gather`**: building the
   coroutine list inside a loop without awaiting (`tasks.append(_f(r))`
   then `await asyncio.gather(*tasks)`) is FINE — the await is
   outside the loop.

2. **Per-row processing where order matters**: e.g. cron-driven
   row-by-row commits where transactional isolation is the point.
   Add an inline `# concurrency-safety: <reason>` comment to suppress.

The audit recognises the comment-suppression marker the same way
the cron-mutex audit does.

Why we walk routers AND services
--------------------------------
Routers are the user-facing perf surface — slow there means user-
visible latency. Services are also in scope because async helpers
called from routers carry the same risk (the loop just lives one
file deeper).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = [_API_ROOT / "routers", _API_ROOT / "services"]


# Today's baseline. Filled in on first run.
BASELINE_AWAITS_IN_LOOPS = (
    60  # 2026-05: 56→60 alongside the activity_stream / cron_failure_watchdog / linter-induced router refactors
)


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


def _comment_suppressed_lines(text: str) -> set[int]:
    """1-indexed line numbers carrying a `# concurrency-safety:`
    comment. Covers the line itself + the next line (so the
    comment can sit above the `for` keyword)."""
    out: set[int] = set()
    for i, line in enumerate(text.splitlines(), start=1):
        if "# concurrency-safety:" in line:
            out.add(i)
            out.add(i + 1)
    return out


def _is_loop(node: ast.AST) -> bool:
    return isinstance(node, (ast.For, ast.AsyncFor, ast.While))


def _walk_async_functions(tree: ast.Module):
    """Yield every `async def` definition in the module (top-level
    or nested inside a class)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            yield node


def _collect_awaits_in_loops(func: ast.AsyncFunctionDef, suppressed: set[int]) -> list[int]:
    """Return list of line numbers where an `Await` expression sits
    INSIDE a `for`/`async for`/`while` loop body inside `func`.

    A naïve walker would also flag `await` inside an inner async
    function defined in the loop — that's actually fine (the inner
    function is just being CONSTRUCTED, not awaited). We track the
    nesting level of async-def boundaries to avoid the false
    positive.
    """
    out: list[int] = []

    def visit(node: ast.AST, in_loop: bool) -> None:
        if isinstance(node, ast.AsyncFunctionDef):
            # Crossing into a NESTED async-def — the body's awaits
            # are the inner function's concern, not this one's.
            for child in ast.iter_child_nodes(node):
                visit(child, in_loop=False)
            return
        if isinstance(node, ast.Await) and in_loop:
            if node.lineno not in suppressed:
                out.append(node.lineno)
            return
        if _is_loop(node):
            for child in ast.iter_child_nodes(node):
                visit(child, in_loop=True)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, in_loop=in_loop)

    for stmt in func.body:
        visit(stmt, in_loop=False)

    return out


def _audit_one_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    suppressed = _comment_suppressed_lines(text)
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    out: list[str] = []
    rel = str(path.relative_to(_API_ROOT))
    for func in _walk_async_functions(tree):
        for line in _collect_awaits_in_loops(func, suppressed):
            out.append(f"{rel}:{line}  in `{func.name}`")
    return out


def test_no_unsuppressed_await_inside_loop_bodies():
    """Walk every `async def` in routers + services; for each loop
    body, assert no naked `await` (the serial-roundtrip bug shape)
    unless suppressed via inline `# concurrency-safety:` comment.

    Failure surfaces both ratchet directions.
    """
    findings: list[str] = []
    for path in _walk_python_files():
        findings.extend(_audit_one_file(path))

    n = len(findings)
    if n > BASELINE_AWAITS_IN_LOOPS:
        new = n - BASELINE_AWAITS_IN_LOOPS
        pytest.fail(
            f"{new} new await-in-loop call(s) "
            f"(total now {n}, baseline {BASELINE_AWAITS_IN_LOOPS}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nFix patterns:\n"
            "  • Batch into one query: `WHERE id = ANY(:ids)` instead "
            "of one query per row.\n"
            "  • Fan-out concurrently: build a list of coroutines, "
            "`await asyncio.gather(*tasks)` once outside the loop.\n\n"
            "If serial order is genuinely required (transactional "
            "per-row commit, rate-limited external API), add a "
            "`# concurrency-safety: <reason>` comment on the `for` "
            "or `await` line."
        )
    if n < BASELINE_AWAITS_IN_LOOPS:
        pytest.fail(
            f"Await-in-loop count dropped from {BASELINE_AWAITS_IN_LOOPS} "
            f"to {n}. 🎉 Update `BASELINE_AWAITS_IN_LOOPS` to {n}."
        )


def test_audit_recognises_documented_patterns():
    """Defensive: positive + negative AST fixtures. A regression
    in the walker (e.g. failing to descend into AsyncFor bodies)
    would silently let serial-await regressions through.
    """
    # Positive: simple `for r in rows: await x(r)` — flagged.
    pos = ast.parse("async def f(rows):\n    for r in rows:\n        await x(r)\n")
    func = pos.body[0]
    assert isinstance(func, ast.AsyncFunctionDef)
    assert _collect_awaits_in_loops(func, suppressed=set()) == [3]

    # Suppressed: `# concurrency-safety:` annotation.
    pos_suppressed = _collect_awaits_in_loops(func, suppressed={3})
    assert pos_suppressed == []

    # Async-for is also a loop.
    af = ast.parse("async def g(stream):\n    async for chunk in stream:\n        await emit(chunk)\n")
    func = af.body[0]
    assert isinstance(func, ast.AsyncFunctionDef)
    assert _collect_awaits_in_loops(func, suppressed=set()) == [3]

    # Negative: await OUTSIDE the loop (gathered at the end).
    safe = ast.parse(
        "async def h(rows):\n"
        "    tasks = []\n"
        "    for r in rows:\n"
        "        tasks.append(x(r))\n"
        "    await asyncio.gather(*tasks)\n"
    )
    func = safe.body[0]
    assert isinstance(func, ast.AsyncFunctionDef)
    assert _collect_awaits_in_loops(func, suppressed=set()) == []

    # Negative: nested async function inside a loop. The await
    # is INSIDE the nested function's body, not the outer loop's
    # body — defining the inner function is non-awaiting.
    nested = ast.parse(
        "async def outer(rows):\n"
        "    for r in rows:\n"
        "        async def inner(x):\n"
        "            return await fetch(x)\n"
        "        tasks.append(inner(r))\n"
    )
    func = nested.body[0]
    assert isinstance(func, ast.AsyncFunctionDef)
    assert _collect_awaits_in_loops(func, suppressed=set()) == []
