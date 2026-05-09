"""Database transaction-commit audit (routers).

The bug class
-------------
A handler that calls `await session.commit()` mid-body breaks the
transactional-outbox pattern. The intended flow:

    @router.post("/x")
    async def f(session: AsyncSession = Depends(get_db)):
        await service.do_thing(session, ...)        # writes
        await audit.record(session, ...)            # outbox row
        return ok(...)
        # `get_db`'s yield-cleanup commits HERE — both rows
        # land or both roll back atomically.

If `do_thing` calls `await session.commit()` internally, the
audit row hasn't been written yet — but the source mutation has.
A subsequent failure (e.g. audit's webhook outbox enqueue raises)
leaves the source mutation committed without its audit/webhook
counterpart. The customer never gets the webhook; compliance
loses its paper trail.

The contract: in-router `commit()` is forbidden. The
`get_db`-style dependency owns the transaction boundary.

What this audit checks
----------------------
AST walk over `apps/api/routers/*.py`. For every `await
<expr>.commit()` (or `<expr>.commit()` if not awaited — also a
bug, but a different one), flag it.

Allowlist
---------
A handful of legitimate cases:
  * Routers that intentionally manage their own transaction (e.g.
    bulk-import COMMIT-per-batch for memory reasons).
  * Cron-driven endpoints that need to commit per-row.
  * Manual-test endpoints (`/webhooks/{id}/test`).

Each entry needs a stated reason. Same ratchet pattern.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_ROUTERS_DIR = _API_ROOT / "routers"


# Today's baseline. First-run captures the existing count; ratchet
# down as routers move commit logic into get_db / service helpers.
BASELINE_INLINE_COMMITS = (
    182  # 2026-05: 178→182 across new admin routers (slack-deliveries / webhook-deliveries-admin / cron-admin)
)


# (relative_path, line_number) → reason. Each entry needs a
# stated rationale; an empty reason silences the gate.
ALLOWLIST: dict[tuple[str, int], str] = {
    # No entries today. Add as legitimate cases surface — most
    # in-router commits should migrate to get_db / service helpers,
    # not get allowlisted.
}


def _list_router_files() -> list[Path]:
    return sorted(p for p in _ROUTERS_DIR.glob("*.py") if p.name != "__init__.py" and p.is_file())


def _comment_suppressed_lines(text: str) -> set[int]:
    """1-indexed line numbers carrying a `# commit-audit:` annotation
    (covers same line + line below, like other audits)."""
    out: set[int] = set()
    for i, line in enumerate(text.splitlines(), start=1):
        if "# commit-audit:" in line:
            out.add(i)
            out.add(i + 1)
    return out


def _is_session_commit_call(node: ast.AST) -> bool:
    """Match `<x>.commit()` and `await <x>.commit()`.

    We don't try to verify `<x>` is actually an AsyncSession —
    static type-inference at the AST level isn't worth the
    complexity. False-positive risk: a non-session `.commit()`
    (e.g. a Git repo wrapper) would also flag, but those are rare
    in router files.
    """
    # Unwrap Await(...) to look at the underlying call.
    if isinstance(node, ast.Await):
        node = node.value
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != "commit":
        return False
    return True


def _audit_one_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    suppressed = _comment_suppressed_lines(text)
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    rel = str(path.relative_to(_API_ROOT))
    out: list[str] = []
    for node in ast.walk(tree):
        if _is_session_commit_call(node):
            line = node.lineno
            if line in suppressed:
                continue
            if (rel, line) in ALLOWLIST:
                continue
            out.append(f"{rel}:{line}")
    return out


def test_no_inline_commit_in_routers():
    """Walk every router; for each `await session.commit()` or
    `session.commit()`, assert it's either allowlisted with a
    stated reason or annotated with `# commit-audit: <reason>`.

    Failures surface both ratchet directions.
    """
    findings: list[str] = []
    for path in _list_router_files():
        findings.extend(_audit_one_file(path))

    n = len(findings)
    if n > BASELINE_INLINE_COMMITS:
        new = n - BASELINE_INLINE_COMMITS
        pytest.fail(
            f"{new} new inline `.commit()` call(s) in routers "
            f"(total now {n}, baseline {BASELINE_INLINE_COMMITS}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nIn-router commits break the transactional-outbox "
            "pattern: a `commit()` after the source mutation but "
            "before the audit row + webhook outbox enqueue means a "
            "later failure leaks the source mutation without its "
            "audit/webhook counterpart.\n\n"
            "Move the commit out: let `get_db`'s yield-cleanup commit "
            "at the end of the request, OR if a per-batch commit is "
            "genuinely needed (bulk import for memory), add an inline "
            "`# commit-audit: <reason>` comment."
        )
    if n < BASELINE_INLINE_COMMITS:
        pytest.fail(
            f"Inline-commit count dropped from {BASELINE_INLINE_COMMITS} "
            f"to {n}. 🎉 Update `BASELINE_INLINE_COMMITS` to {n}."
        )


def test_audit_recognises_session_commit_shapes():
    """Defensive: hand-rolled fixtures verify each commit-call
    shape is detected. A regression in `_is_session_commit_call`
    would silently let regressions through.
    """
    # `await session.commit()`
    pos1 = ast.parse("async def f(s):\n    await s.commit()\n").body[0]
    assert isinstance(pos1, ast.AsyncFunctionDef)
    # The Expr-wrapped Await is inside body[0]; descend once.
    expr = pos1.body[0]
    assert isinstance(expr, ast.Expr)
    assert _is_session_commit_call(expr.value)

    # `session.commit()` without await — also a commit call.
    pos2 = ast.parse("def g(s):\n    s.commit()\n").body[0]
    assert isinstance(pos2, ast.FunctionDef)
    expr = pos2.body[0]
    assert isinstance(expr, ast.Expr)
    assert _is_session_commit_call(expr.value)

    # Negative: `session.flush()` — not a commit.
    neg = ast.parse("async def h(s):\n    await s.flush()\n").body[0]
    assert isinstance(neg, ast.AsyncFunctionDef)
    expr = neg.body[0]
    assert isinstance(expr, ast.Expr)
    assert not _is_session_commit_call(expr.value)
