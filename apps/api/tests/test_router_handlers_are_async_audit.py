"""Audit: every FastAPI route handler is `async def`, not `def`.

A sync handler in FastAPI works — the framework auto-detects sync
handlers and runs them in a thread pool — but the consequences
under load are silent and bad:

  * Every `await session.execute(...)` call inside a sync handler
    becomes blocking. The thread pool worker holds the connection
    while the SQL runs, instead of yielding back to the event loop.

  * Under concurrent load, the thread pool saturates faster than
    the async-native path would. Latency tail (p95 / p99) inflates
    quietly. The error rate stays low; the response-time graph
    just slowly drifts up over weeks as the platform scales.

  * No CI test will catch this. The handler returns the right
    response shape; integration tests pass; load tests don't run
    in PR CI. The regression surfaces as "p95 is 800ms now,
    used to be 300ms" — discovered weeks after the bad handler
    landed, with no clear signal of which one.

The audit walks every `routers/*.py` file, AST-parses, finds every
function with a `@router.<method>` decorator, and asserts it's
declared `async def` not `def`.

Allowlist surface:

  * `_LEGITIMATE_SYNC_HANDLERS` — fully-qualified handler names
    (file::function) where sync is intentional. Today: empty.
    Examples of legit sync handlers would be: health-probe-style
    endpoints that return a static dict without touching the DB
    or async I/O. Even those are typically written async for
    consistency.

This file is read-only — AST-parses migration files. Survives
reverts.
"""

from __future__ import annotations

import ast
from pathlib import Path


# Allowlist of sync handlers that are legitimately not async.
# Format: "<filename>::<function_name>" → rationale.
# Today: empty. Every router handler in the codebase is async.
_LEGITIMATE_SYNC_HANDLERS: dict[str, str] = {
    # Format: "filename::function_name": "rationale"
    # Today: none. Adding an entry triggers PR review of the
    # sync-handler choice (it's almost always wrong).
}


# HTTP method-decorator names we recognise on the router. The
# decorator chain is `@router.get("...")`, `@router.post("...")`,
# etc. We also recognise `@router.api_route(...)` for the rare
# multi-method form. Decorators that aren't HTTP-method ones
# (e.g. `@deprecated`, `@cached`) are skipped — only the
# router-method decorator marks the function as a route handler.
_ROUTER_HTTP_METHODS: frozenset[str] = frozenset(
    {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        "trace",
        "api_route",
    }
)


def _routers_dir() -> Path:
    return Path(__file__).parent.parent / "routers"


def _is_router_method_decorator(dec: ast.expr) -> bool:
    """Return True if `dec` is `@<router_obj>.<method>(...)` where
    `<method>` is in `_ROUTER_HTTP_METHODS`.

    Accepts any router-object NAME (the convention is `router`,
    but some files use `quota_router`, `_router`, etc.). What
    matters is the method name on the right side of the dot.
    """
    # Decorator forms:
    #   @router.get("...")           — Call(Attribute(Name, "get"), ...)
    #   @router.api_route("...", methods=["GET"])
    #
    # Bare `@router.get` (no call) is also accepted in principle
    # but doesn't appear in this codebase.
    if isinstance(dec, ast.Call):
        func = dec.func
        if isinstance(func, ast.Attribute):
            if func.attr in _ROUTER_HTTP_METHODS:
                return True
    elif isinstance(dec, ast.Attribute):
        if dec.attr in _ROUTER_HTTP_METHODS:
            return True
    return False


def _walk_router_handlers():
    """Yield `(filename, function_name, is_async)` for every
    function decorated with `@router.<method>` across every
    `routers/*.py` file."""
    for py_file in sorted(_routers_dir().glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not any(_is_router_method_decorator(d) for d in node.decorator_list):
                continue
            is_async = isinstance(node, ast.AsyncFunctionDef)
            yield py_file.name, node.name, is_async


def test_every_router_handler_is_async():
    """SECURITY/PERFORMANCE pin. Every function decorated with
    `@router.<method>` MUST be `async def`. A sync handler:

      1. Blocks the event loop while running. Every `await`
         inside it becomes synchronous, holding a thread-pool
         worker for the duration.
      2. Under load, saturates the thread pool faster than the
         async path. p95 latency drifts up silently as concurrent
         traffic grows.
      3. Has no functional symptom — the response is correct;
         only the latency profile changes — so unit tests miss it.

    Resolution paths:

      1. Convert `def <handler>(...)` to `async def <handler>(...)`.
         Add `await` to the DB / HTTP / file-IO calls inside.
      2. If the handler is genuinely sync-safe (returns a
         static dict, no async I/O), add it to
         `_LEGITIMATE_SYNC_HANDLERS` with a rationale. PR review
         of THAT addition vets the choice. (In practice this is
         almost always wrong; FastAPI's sync support exists for
         migrating legacy code, not for new routes.)
    """
    sync_handlers: list[str] = []
    for filename, func_name, is_async in _walk_router_handlers():
        if is_async:
            continue
        fqn = f"{filename}::{func_name}"
        if fqn in _LEGITIMATE_SYNC_HANDLERS:
            continue
        sync_handlers.append(fqn)

    assert not sync_handlers, (
        "These FastAPI route handlers are declared `def` "
        "(synchronous) — they should be `async def`:\n  " + "\n  ".join(sorted(sync_handlers)) + "\n\n"
        "PERF: a sync handler in FastAPI runs in a thread-pool "
        "worker. Every `await` inside it becomes blocking; "
        "concurrent load saturates the thread pool faster than "
        "the async-native path; p95 latency drifts up silently. "
        "No functional test catches this — only the latency "
        "graph (weeks later) shows the regression.\n\n"
        "Resolution:\n"
        "  1. Change `def` to `async def` and add `await` where "
        "required (DB session calls, httpx requests, mailer/slack "
        "calls).\n"
        "  2. If the handler is genuinely sync-safe (rare; static "
        "dict response, zero async I/O), add it to "
        "`_LEGITIMATE_SYNC_HANDLERS` with a rationale comment."
    )


def test_audit_finds_router_handlers():
    """Sanity floor — the AST walker actually finds router
    handlers. If a future refactor moved every handler out of
    `routers/*.py` (e.g. into a different namespace), the audit
    would silently pass with zero handlers scanned.

    A failure here usually means EITHER (a) the routers/ dir
    moved (update `_routers_dir()`) OR (b) the decorator pattern
    changed (update `_ROUTER_HTTP_METHODS`).
    """
    handlers = list(_walk_router_handlers())
    assert len(handlers) >= 30, (
        f"AST walker found {len(handlers)} router handlers — "
        "implausibly few. Either the routers/ layout changed or "
        "the decorator-detection pattern got out of sync with "
        "the codebase's actual decorator shapes."
    )


def test_legitimate_sync_handler_allowlist_is_minimal():
    """The carve-out for sync handlers should stay empty in
    steady state. Pin a low cap so a future addition is reviewed
    deliberately — async-by-default is the documented norm."""
    assert len(_LEGITIMATE_SYNC_HANDLERS) <= 2, (
        f"_LEGITIMATE_SYNC_HANDLERS has "
        f"{len(_LEGITIMATE_SYNC_HANDLERS)} entries: "
        f"{list(_LEGITIMATE_SYNC_HANDLERS.keys())}. Today should "
        "be 0; if you needed to add one, the rationale is the "
        "PR review trigger. Async-by-default is the documented "
        "norm."
    )


def test_legitimate_sync_handler_entries_have_rationale():
    """Every `_LEGITIMATE_SYNC_HANDLERS` entry has a non-empty
    rationale string. Bare entries without comments defeat the
    review-the-decision design."""
    for fqn, rationale in _LEGITIMATE_SYNC_HANDLERS.items():
        assert rationale and rationale.strip(), (
            f"`_LEGITIMATE_SYNC_HANDLERS` entry `{fqn}` has empty "
            "rationale. PR reviewers need the WHY alongside the "
            "entry."
        )
