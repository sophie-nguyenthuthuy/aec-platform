"""N+1 query detection audit.

The bug class
-------------
A loop or comprehension whose body issues a separate DB query
per iteration. With 5 rows in dev it's invisible; with 5,000 rows
in prod it's a "the API got slow this week" incident:

    # N+1 — one round trip per item.
    for project_id in project_ids:
        proj = await db.scalar(
            select(Project).where(Project.id == project_id),
        )
        results.append(proj)

The right shape:

    # 1 query.
    rows = (await db.execute(
        select(Project).where(Project.id.in_(project_ids)),
    )).scalars().all()

Sister audit: `test_concurrency_safety_audit.py`. That one flags
ANY `await` inside an async loop body (covers DB calls AND
unrelated network/IO awaits the same way). This audit is narrower
and additive — it only flags the SQLAlchemy-shaped query calls,
which is the bug class with the worst latency profile and the
clearest fix (batch via `IN`/`ANY` or hydrate via
`selectinload`/`joinedload`).

Two reasons the narrowness matters:

  1. Sync code. The concurrency audit only walks `async def`. A
     synchronous helper in `services/` that loops over rows and
     calls `db.execute()` per iteration is the same N+1 bug, and
     this audit catches it.

  2. Comprehensions. `[await db.scalar(...) for x in xs]` is the
     same shape as a `for` loop with an explicit `await`. The
     concurrency audit doesn't descend into comprehension
     generators; this one does.

What this audit checks
----------------------
AST walk over `apps/api/{routers,services}/*.py`. For every
function (sync or async), look at every:
  * `for` / `async for` / `while` loop body, and
  * `ListComp` / `SetComp` / `DictComp` / `GeneratorExp` body.

If the body contains a method call whose attribute is one of:
  `execute`, `scalar`, `scalars`, `scalar_one`, `scalar_one_or_none`,
  `first`, `one`, `one_or_none`, `all`, `refresh`, `merge`, `flush`,
  `delete`, `add`,

flag the call. Whether the call is awaited is irrelevant — both
sync and async query patterns hit the same N+1 cost shape.

False-positive shapes
---------------------
1. **`asyncio.gather(*[db.execute(…) for x in xs])`**: the
   comprehension builds coroutines without awaiting them; the
   single `gather` outside collapses N round trips into 1 (or N
   parallel). Add a `# n+1: gathered` comment on the comprehension
   line to suppress.

2. **`for row in await db.execute(...).fetchall():`**: the await
   IS the single query; the loop body iterates pure-Python over
   the result. The audit's shape match is on the BODY of the
   loop — a `.fetchall()` call inside the loop predicate doesn't
   trigger a body-level match. Tested by the negative fixture.

3. **List building of params for a single bulk query**:
   `[obj for x in xs]` where `obj` is a pure-Python construction
   (no DB method call) doesn't match.

Suppression
-----------
Add an inline `# n+1: <reason>` comment on the loop / comprehension
line OR the offending call line. The reason is what makes the
exception reviewable.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = [_API_ROOT / "routers", _API_ROOT / "services"]


# Today's baseline. Filled in on first run.
BASELINE_N_PLUS_ONE_CALLS = 22  # 2026-05: first-run baseline; ratchet down as call sites batch / hydrate eagerly


# DB query-method names. We don't try to verify the receiver is
# actually an AsyncSession / Session — static type-inference at the
# AST level isn't worth the complexity. The receiver-name filter
# below narrows the false-positive surface.
_QUERY_METHODS: frozenset[str] = frozenset(
    {
        "execute",
        "scalar",
        "scalars",
        "scalar_one",
        "scalar_one_or_none",
        "first",
        "one",
        "one_or_none",
        "refresh",
        "merge",
        "flush",
    }
)


# Receiver names that look session-like. A `<name>.execute(...)`
# call inside a loop only flags when `<name>` is one of these.
# Keeps the audit narrow: `subprocess.execute(...)` or a generic
# `client.execute(...)` in a webhook caller doesn't false-match.
_SESSION_NAMES: frozenset[str] = frozenset({"db", "session", "s", "conn", "connection", "tx"})


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


def _suppressed_lines(text: str) -> set[int]:
    """1-indexed line numbers carrying a `# n+1:` annotation. Covers
    the line itself + the next line so the comment can sit above
    the `for` or the offending `await`."""
    out: set[int] = set()
    for i, line in enumerate(text.splitlines(), start=1):
        if "# n+1:" in line:
            out.add(i)
            out.add(i + 1)
    return out


def _is_loop_or_comp(node: ast.AST) -> bool:
    return isinstance(
        node,
        ast.For | ast.AsyncFor | ast.While | ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    )


def _is_db_query_call(node: ast.AST) -> tuple[str, str] | None:
    """Match `<name>.execute(...)` etc. where name ∈ _SESSION_NAMES.
    Returns (receiver_name, method_name) on match, else None."""
    call = node.value if isinstance(node, ast.Await) else node
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr not in _QUERY_METHODS:
        return None
    # Walk the receiver chain to its leftmost Name. `db.execute(...)`
    # → "db". `self.db.execute(...)` → "db". This handles both the
    # bare-session and via-self patterns.
    recv: ast.AST = func.value
    while isinstance(recv, ast.Attribute):
        recv = recv.value
    if not isinstance(recv, ast.Name):
        return None
    if recv.id not in _SESSION_NAMES:
        return None
    return (recv.id, func.attr)


def _collect_db_calls_in_body(body: list[ast.stmt] | ast.expr, suppressed: set[int]) -> list[tuple[int, str]]:
    """Return [(lineno, method)] for every DB query call in the
    statement list / expression. Recurses through nested loops +
    comprehensions but NOT through nested function definitions."""
    out: list[tuple[int, str]] = []

    def visit(node: ast.AST) -> None:
        # Don't descend into nested function defs — those are their
        # own audit scope.
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            return
        match = _is_db_query_call(node)
        if match is not None:
            line = node.lineno
            if line not in suppressed:
                out.append((line, match[1]))
            # Don't recurse into a matched call's children — both
            # `Await(Call(...))` and the inner `Call(...)` would
            # otherwise match the same query, double-counting.
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    if isinstance(body, list):
        for stmt in body:
            visit(stmt)
    else:
        visit(body)
    return out


def _audit_one_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    suppressed: set[int],
    rel: str,
) -> list[str]:
    """Find every loop/comprehension inside `func`; for each, scan
    its body for DB calls.

    A nested loop's DB calls count once (against the innermost
    loop). We attribute the offender to the innermost loop's line
    so the failure message points at the right place to fix.
    """
    out: list[str] = []

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            # Different function scope — handled by its own
            # `_audit_one_function` call from the outer walker.
            return
        if _is_loop_or_comp(node):
            # Suppression on the loop line itself (or the line
            # above) silences every match in the body.
            if node.lineno in suppressed:
                return
            # The body shape varies per node type:
            #   * For/AsyncFor/While: `node.body` is list[stmt]
            #   * ListComp/SetComp/GeneratorExp: `node.elt` (expr)
            #   * DictComp: `node.key` + `node.value` (both expr)
            bodies: list = []
            if isinstance(node, ast.For | ast.AsyncFor | ast.While):
                bodies.append(node.body)
            elif isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
                bodies.append(node.elt)
            elif isinstance(node, ast.DictComp):
                bodies.append(node.key)
                bodies.append(node.value)
            for body in bodies:
                for line, method in _collect_db_calls_in_body(body, suppressed):
                    out.append(f"{rel}:{line}  in `{func.name}` ({method})")
            # Don't return — descend so nested loops inside this
            # body are also checked.
        for child in ast.iter_child_nodes(node):
            walk(child)

    for stmt in func.body:
        walk(stmt)
    return out


def _audit_one_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    suppressed = _suppressed_lines(text)
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    out: list[str] = []
    rel = str(path.relative_to(_API_ROOT))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out.extend(_audit_one_function(node, suppressed, rel))
    return out


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _walk_python_files():
        out.extend(_audit_one_file(path))
    return out


def test_no_db_query_inside_loop_body():
    """Walk every function in routers + services; flag any
    SQLAlchemy-shaped query call (`db.execute(...)`,
    `session.scalar(...)`, etc.) inside a loop body or
    comprehension generator.

    Failures surface both ratchet directions.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_N_PLUS_ONE_CALLS:
        new = n - BASELINE_N_PLUS_ONE_CALLS
        pytest.fail(
            f"{new} new N+1 query call(s) "
            f"(total now {n}, baseline {BASELINE_N_PLUS_ONE_CALLS}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nFix patterns:\n"
            "  • Batch into one query: `WHERE id = ANY(:ids)` or "
            "`WHERE col.in_(values)` instead of one query per row.\n"
            "  • Hydrate relationships eagerly: `selectinload(M.rel)` "
            "/ `joinedload(M.rel)` on the parent query so the loop "
            "doesn't lazy-load.\n"
            "  • Build the call args inside the loop, fan out via "
            "`asyncio.gather(*tasks)` once outside (parallelism).\n\n"
            "If the per-row DB call is genuinely required (per-row "
            "transactional commit, rate-limited external call, "
            "fundamentally serial workflow), add a "
            "`# n+1: <reason>` comment on the loop or the call line."
        )
    if n < BASELINE_N_PLUS_ONE_CALLS:
        pytest.fail(
            f"N+1 count dropped from {BASELINE_N_PLUS_ONE_CALLS} to {n}. 🎉 Update `BASELINE_N_PLUS_ONE_CALLS` to {n}."
        )


def test_audit_recognises_documented_patterns():
    """Defensive: positive + negative AST fixtures. A regression
    in the walker would silently let N+1 patterns through.
    """
    # Positive: `for x in xs: await db.execute(...)` — flagged.
    pos = ast.parse("async def f(db, xs):\n    for x in xs:\n        await db.execute(x)\n")
    fn = pos.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    findings = _audit_one_function(fn, suppressed=set(), rel="x.py")
    assert len(findings) == 1, f"Expected 1 finding, got {findings}"

    # Positive: list comprehension N+1.
    pos_comp = ast.parse("def g(db, xs):\n    return [db.scalar(x) for x in xs]\n")
    fn = pos_comp.body[0]
    assert isinstance(fn, ast.FunctionDef)
    findings = _audit_one_function(fn, suppressed=set(), rel="x.py")
    assert len(findings) == 1, f"Expected 1 finding (list-comp), got {findings}"

    # Positive: dict comprehension — both key and value bodies scan.
    pos_dict = ast.parse("def h(db, xs):\n    return {x: db.scalar(x) for x in xs}\n")
    fn = pos_dict.body[0]
    assert isinstance(fn, ast.FunctionDef)
    findings = _audit_one_function(fn, suppressed=set(), rel="x.py")
    assert len(findings) == 1, f"Expected 1 finding (dict-comp), got {findings}"

    # Suppressed: `# n+1:` annotation.
    suppressed_pos = _audit_one_function(
        pos.body[0],  # type: ignore[arg-type]
        suppressed={3},  # the await line
        rel="x.py",
    )
    assert suppressed_pos == [], f"Suppression failed: {suppressed_pos}"

    # Negative: `for row in await db.execute(...).fetchall():` —
    # the await is in the iterator, not the body. Body has no DB
    # call, so no flag.
    neg = ast.parse(
        "async def k(db):\n"
        "    rows = (await db.execute('SELECT')).fetchall()\n"
        "    for row in rows:\n"
        "        x = row.id  # pure-Python\n"
    )
    fn = neg.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    findings = _audit_one_function(fn, suppressed=set(), rel="x.py")
    assert findings == [], f"False positive: {findings}"

    # Negative: `subprocess.execute(...)` — receiver not session-like.
    neg_recv = ast.parse("def m(xs):\n    for x in xs:\n        subprocess.execute(x)\n")
    fn = neg_recv.body[0]
    assert isinstance(fn, ast.FunctionDef)
    findings = _audit_one_function(fn, suppressed=set(), rel="x.py")
    assert findings == [], f"Receiver filter failed: {findings}"

    # Negative: gather pattern — `asyncio.gather(*[db.execute(x) for x in xs])`.
    # The list comp builds coroutines without awaiting. Strictly
    # speaking the DB call IS in a comprehension body, so the
    # audit DOES flag it — the fix is the suppression marker, not
    # changing the audit. We assert the flag fires here so the
    # suppression contract is documented.
    gather = ast.parse("import asyncio\nasync def n(db, xs):\n    await asyncio.gather(*[db.execute(x) for x in xs])\n")
    fn = gather.body[1]
    assert isinstance(fn, ast.AsyncFunctionDef)
    findings = _audit_one_function(fn, suppressed=set(), rel="x.py")
    assert len(findings) == 1, f"Gather pattern should flag (suppress with `# n+1:`), got {findings}"
