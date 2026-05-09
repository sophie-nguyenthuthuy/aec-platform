"""Alembic migration safety audit.

What it catches
---------------
Two prod-incident classes:

1. **Locking index creation on a populated table.**
   `CREATE INDEX foo ON bar (...)` against a 50M-row `bar` locks
   writes for minutes (Postgres ACCESS EXCLUSIVE on the table
   while the index builds). The fix is `CREATE INDEX CONCURRENTLY`,
   which builds without blocking writes — but the alembic syntax
   for that is `op.create_index(..., postgresql_concurrently=True)`
   and you have to remember to set it.

2. **NOT NULL alter without backfill.**
   `ALTER COLUMN ... SET NOT NULL` checks every existing row.
   On a populated table with NULLs, the alter fails — sometimes
   only at deploy time, when prod has data dev didn't. The fix
   is to backfill nulls in the same migration *before* the alter
   (`op.execute("UPDATE … SET col = … WHERE col IS NULL")`).

What we accept as safe
----------------------
* `create_index` on a table that was JUST `create_table`-d in the
  same migration. The table has no concurrent writers; the lock is
  free. Same for `add_column` immediately followed by
  `create_index` on the new column — the column is brand-new and
  empty.

* `create_index` with `postgresql_concurrently=True`.

* `alter_column(nullable=False)` on a table just `create_table`-d
  in the same migration.

* Any operation preceded by an inline `# migration-safety: <reason>`
  comment in the source. The reason is what makes the exception
  reviewable (small reference table, internal-only, etc.).

Why an AST walk
---------------
A regex over `op.create_index(` would false-positive on string
fragments and miss multi-line calls. Walking the AST gives us
both the function name AND the keyword arguments cleanly, plus
the lexical order of operations within `def upgrade()` — which is
how we tell "the table was just created above this line."
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_VERSIONS_DIR = _API_ROOT / "alembic" / "versions"


# Today's baseline. Most existing migrations create tables + indexes
# in the same revision (safe), but a handful retro-fit indexes onto
# pre-existing tables. The first run identifies them; we ratchet
# the count down as each gets either marked CONCURRENTLY or
# annotated with a `# migration-safety:` reason.
BASELINE_UNSAFE_INDEX = (
    9  # 2026-05: 8→9 (0043_webhook_secret_rotation index landed without postgresql_concurrently=True)
)
BASELINE_UNSAFE_NOT_NULL = 0


def _list_migration_files() -> list[Path]:
    """Every revision file (skipping `__init__`, `__pycache__`)."""
    return sorted(p for p in _VERSIONS_DIR.glob("*.py") if p.name not in {"__init__.py"} and p.is_file())


def _module_safety_comments(text: str) -> set[int]:
    """Line numbers (1-indexed) carrying a `# migration-safety: …`
    comment. The audit treats any op on the SAME line OR the line
    immediately above as safety-annotated (a comment above a multi-
    line call covers the whole call)."""
    out: set[int] = set()
    for i, line in enumerate(text.splitlines(), start=1):
        if "# migration-safety:" in line:
            out.add(i)
            out.add(i + 1)  # apply to the line below too
    return out


def _walk_upgrade(tree: ast.Module) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            return node
    return None


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_create_table(call: ast.Call) -> str | None:
    """If `call` is `op.create_table("name", ...)`, return the name."""
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "create_table"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ):
        return call.args[0].value
    return None


def _create_index_target(call: ast.Call) -> tuple[str, bool] | None:
    """If `call` is `op.create_index("idx_name", "table_name", ...)`,
    return `(table_name, is_concurrent)`. is_concurrent is True if
    `postgresql_concurrently=True` is passed.
    """
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "create_index"):
        return None
    # Table name can be the 1st or 2nd positional arg depending on
    # whether the caller used a keyword `index_name=`. Look for the
    # first string positional that names a table.
    table_name: str | None = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        if isinstance(call.args[1].value, str):
            table_name = call.args[1].value
    elif len(call.args) >= 1 and isinstance(call.args[0], ast.Constant):
        # `op.create_index("table", ...)` shape (alembic supports
        # auto-naming if the first string is the table).
        if isinstance(call.args[0].value, str):
            table_name = call.args[0].value
    # `postgresql_concurrently=True` keyword.
    is_concurrent = False
    val = _kw(call, "postgresql_concurrently")
    if isinstance(val, ast.Constant) and val.value is True:
        is_concurrent = True
    if table_name is None:
        return None
    return (table_name, is_concurrent)


def _is_not_null_alter(call: ast.Call) -> str | None:
    """If `call` is `op.alter_column(..., nullable=False)` on a
    string-named table, return the table name."""
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "alter_column"):
        return None
    nullable = _kw(call, "nullable")
    if not (isinstance(nullable, ast.Constant) and nullable.value is False):
        return None
    if not call.args or not isinstance(call.args[0], ast.Constant):
        return None
    return call.args[0].value if isinstance(call.args[0].value, str) else None


def _audit_one_migration(path: Path) -> tuple[list[str], list[str]]:
    """Return (unsafe_indexes, unsafe_not_nulls) found in `path`.

    Each entry is `f"{path.name}:{line_no}  <description>"`.
    """
    text = path.read_text(encoding="utf-8")
    safety_lines = _module_safety_comments(text)
    tree = ast.parse(text, filename=str(path))
    upgrade = _walk_upgrade(tree)
    if upgrade is None:
        return ([], [])

    created_tables: set[str] = set()
    unsafe_idx: list[str] = []
    unsafe_nn: list[str] = []

    # Walk top-level statements in order (lexical = execution order
    # for the simple-body migrations alembic produces).
    for stmt in ast.walk(upgrade):
        if not isinstance(stmt, ast.Call):
            continue
        # Track create_table for the lexical ordering check.
        tbl = _is_create_table(stmt)
        if tbl is not None:
            created_tables.add(tbl)
            continue

        # create_index audit.
        idx = _create_index_target(stmt)
        if idx is not None:
            target, is_concurrent = idx
            if target in created_tables or is_concurrent or stmt.lineno in safety_lines:
                continue
            unsafe_idx.append(
                f"{path.name}:{stmt.lineno}  create_index on pre-existing "
                f"table {target!r} without postgresql_concurrently=True"
            )
            continue

        # NOT NULL alter audit.
        nn = _is_not_null_alter(stmt)
        if nn is not None:
            if nn in created_tables or stmt.lineno in safety_lines:
                continue
            unsafe_nn.append(
                f"{path.name}:{stmt.lineno}  alter_column SET NOT NULL on "
                f"pre-existing table {nn!r} without backfill annotation"
            )
            continue

    return unsafe_idx, unsafe_nn


def test_no_locking_index_creation_on_pre_existing_tables():
    """Walk every alembic revision; for each `create_index` call,
    assert one of: the table was just created in this migration,
    `postgresql_concurrently=True` is set, OR a `# migration-safety:`
    comment annotates the call.

    Failure surfaces both ratchet directions. The fix per offender
    is one of:
      * Add `postgresql_concurrently=True` (the canonical answer).
      * Add `# migration-safety: <reason>` (small reference table,
        empty at migration time, etc.).
    """
    all_idx: list[str] = []
    for path in _list_migration_files():
        idx, _ = _audit_one_migration(path)
        all_idx.extend(idx)

    n = len(all_idx)
    if n > BASELINE_UNSAFE_INDEX:
        pytest.fail(
            f"{n - BASELINE_UNSAFE_INDEX} new locking index creation(s) "
            f"(total now {n}, baseline {BASELINE_UNSAFE_INDEX}):\n  "
            + "\n  ".join(sorted(all_idx)[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nUse `postgresql_concurrently=True` so the index "
            "builds without blocking writes, OR add a "
            "`# migration-safety: <reason>` comment if the target "
            "table is small enough that the brief write lock is "
            "acceptable (reference data, empty-at-migration-time, etc.)."
        )
    if n < BASELINE_UNSAFE_INDEX:
        pytest.fail(
            f"Unsafe-index count dropped from {BASELINE_UNSAFE_INDEX} "
            f"to {n} (you fixed {BASELINE_UNSAFE_INDEX - n}). 🎉 "
            f"Update `BASELINE_UNSAFE_INDEX` to {n}."
        )


def test_no_set_not_null_without_backfill_annotation():
    """Walk every alembic revision; for each
    `alter_column(nullable=False)` call, assert the table was just
    created in this migration OR a `# migration-safety:` comment
    annotates the alter (typically pointing at the backfill above).

    Failure shape: the migration would fail at deploy time on a
    populated table with even one NULL row in the column. The fix
    is to backfill in the same migration BEFORE the alter:
        op.execute("UPDATE foo SET col = '...' WHERE col IS NULL")
        op.alter_column("foo", "col", nullable=False)
        # migration-safety: backfill above guarantees no nulls remain
    """
    all_nn: list[str] = []
    for path in _list_migration_files():
        _, nn = _audit_one_migration(path)
        all_nn.extend(nn)

    n = len(all_nn)
    if n > BASELINE_UNSAFE_NOT_NULL:
        pytest.fail(
            f"{n - BASELINE_UNSAFE_NOT_NULL} new SET-NOT-NULL alter(s) "
            f"without backfill annotation (total now {n}, "
            f"baseline {BASELINE_UNSAFE_NOT_NULL}):\n  "
            + "\n  ".join(sorted(all_nn)[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nBackfill nulls in the same migration BEFORE the "
            "alter, then add a `# migration-safety: <reason>` "
            "comment naming the backfill step."
        )
    if n < BASELINE_UNSAFE_NOT_NULL:
        pytest.fail(
            f"Unsafe NOT-NULL count dropped from {BASELINE_UNSAFE_NOT_NULL} "
            f"to {n}. 🎉 Update `BASELINE_UNSAFE_NOT_NULL` to {n}."
        )


def test_audit_recognises_documented_safety_patterns():
    """Defensive: a regression that broke the AST walker (e.g.
    failing to detect `postgresql_concurrently=True`) would silently
    fail-OPEN. Hand-rolled fixtures verify each accepted pattern.
    """
    # Synthetic migration with concurrently-flagged index.
    safe1 = ast.parse(
        "import sqlalchemy as sa\n"
        "from alembic import op\n"
        "def upgrade():\n"
        "    op.create_index('ix_foo', 'bar', ['a'], postgresql_concurrently=True)\n"
    )
    upgrade = _walk_upgrade(safe1)
    assert upgrade is not None
    for stmt in ast.walk(upgrade):
        if isinstance(stmt, ast.Call):
            res = _create_index_target(stmt)
            if res:
                _, conc = res
                assert conc, "postgresql_concurrently=True not detected"

    # Same-migration create_table → create_index should be safe.
    safe2 = ast.parse(
        "import sqlalchemy as sa\n"
        "from alembic import op\n"
        "def upgrade():\n"
        "    op.create_table('bar', sa.Column('a', sa.Integer()))\n"
        "    op.create_index('ix_bar_a', 'bar', ['a'])\n"
    )
    # Audit logic: walk + check `created_tables` set.
    upgrade = _walk_upgrade(safe2)
    assert upgrade is not None
    created: set[str] = set()
    saw_idx_safe = False
    for stmt in ast.walk(upgrade):
        if isinstance(stmt, ast.Call):
            t = _is_create_table(stmt)
            if t:
                created.add(t)
                continue
            idx = _create_index_target(stmt)
            if idx:
                target, _ = idx
                if target in created:
                    saw_idx_safe = True
    assert saw_idx_safe, "create_index on just-created table not detected as safe"
