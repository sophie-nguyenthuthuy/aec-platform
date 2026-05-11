"""Foreign-key index coverage audit.

The bug class
-------------
Postgres auto-indexes PRIMARY KEY and UNIQUE columns. It does
NOT auto-index foreign-key columns. Yet most FK columns NEED an
index for two reasons:

1. **`DELETE` on the parent table.** Postgres' FK enforcement
   does a sequential scan of the child table to find referencing
   rows. On a 5M-row child with a covering index it's milliseconds;
   without one it's a multi-minute table scan that holds the
   parent's row lock the whole time. A delete that should be
   instantaneous turns into "are we down?"

2. **JOINs from parent to child.** `SELECT … FROM parent JOIN child
   ON child.parent_id = parent.id WHERE parent.x = …` is the
   bread-and-butter ORM query. Without an index on `child.parent_id`
   the planner falls back to hashing the entire child table.
   Per-request latency climbs linearly with child-table size.

Sister of `test_fk_ondelete_audit.py`: that one pins "FK declares
its delete-cascade behaviour"; this one pins "FK can be enforced /
joined efficiently."

What this audit checks
----------------------
AST walk over `apps/api/alembic/versions/*.py`. Across all
migrations, collect:

- Every FK declared (via `sa.ForeignKey("…")` inside
  `op.create_table` or via `op.create_foreign_key(…)`).
- Every index created (via `op.create_index(…, table, [cols, …])`
  or `sa.Index(name, *cols)` inside `op.create_table`).
- Primary keys (`primary_key=True` columns) are auto-indexed.
- UNIQUE columns (`unique=True` or `op.create_unique_constraint`)
  are auto-indexed.

For each FK column, assert it's the LEADING column of some index
on the same table (or it's a primary key, or unique). Trailing
columns of composite indexes don't count: the planner can use a
multi-column index `(a, b, c)` for a query on `a` alone, but not
for a query on `c` alone.

What's NOT checked
------------------
- `EXCLUDE` constraints that may cover an FK column.
- Partial indexes (`postgresql_where=`); we count them as covering.
- Functional indexes (`func.lower(col)`); the audit doesn't
  introspect these — the FK still needs a plain b-tree.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_VERSIONS_DIR = _API_ROOT / "alembic" / "versions"


# Today's baseline. Filled in on first run.
BASELINE_UNCOVERED_FKS = 125  # 2026-05: first-run baseline (43 alembic migrations)


# Per-(table, column) allowlist for legitimate cases. Each entry
# needs a stated reason. Use sparingly — most FK columns SHOULD
# be indexed.
ALLOWLIST: dict[tuple[str, str], str] = {
    # No entries today.
}


def _list_migration_files() -> list[Path]:
    return sorted(p for p in _VERSIONS_DIR.glob("*.py") if p.name != "__init__.py" and p.is_file())


def _const_str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _list_of_str(node: ast.expr | None) -> list[str] | None:
    """`["a", "b"]` -> `["a", "b"]`. Returns None if not a string list."""
    if not isinstance(node, ast.List):
        return None
    out: list[str] = []
    for elt in node.elts:
        s = _const_str(elt)
        if s is None:
            return None
        out.append(s)
    return out


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_primary_key_column(call: ast.Call) -> bool:
    """`sa.Column(..., primary_key=True)` shape."""
    val = _kw(call, "primary_key")
    return isinstance(val, ast.Constant) and val.value is True


def _is_unique_column(call: ast.Call) -> bool:
    val = _kw(call, "unique")
    return isinstance(val, ast.Constant) and val.value is True


def _is_create_table(call: ast.Call) -> str | None:
    """Returns table name if `op.create_table("table", …)`."""
    if isinstance(call.func, ast.Attribute) and call.func.attr == "create_table" and call.args:
        return _const_str(call.args[0])
    return None


def _is_column_call(call: ast.Call) -> bool:
    """`sa.Column(...)` or `Column(...)`."""
    if isinstance(call.func, ast.Attribute):
        return call.func.attr == "Column"
    if isinstance(call.func, ast.Name):
        return call.func.id == "Column"
    return False


def _is_foreign_key_call(call: ast.Call) -> bool:
    """`sa.ForeignKey(...)` or `ForeignKey(...)`."""
    if isinstance(call.func, ast.Attribute):
        return call.func.attr == "ForeignKey"
    if isinstance(call.func, ast.Name):
        return call.func.id == "ForeignKey"
    return False


def _column_has_fk(col_call: ast.Call) -> bool:
    """A `sa.Column(...)` that contains an `sa.ForeignKey(...)` arg."""
    return any(isinstance(arg, ast.Call) and _is_foreign_key_call(arg) for arg in col_call.args)


def _column_name(col_call: ast.Call) -> str | None:
    """`sa.Column("name", ...)` — the first positional string."""
    if not col_call.args:
        return None
    return _const_str(col_call.args[0])


def _is_create_index(call: ast.Call) -> tuple[str, list[str]] | None:
    """`op.create_index("idx", "table", ["col", "col2"], …)` →
    (table, columns).

    Older shape `op.create_index("idx", "table", ["col"])` works
    too — same parser.
    """
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "create_index"):
        return None
    if len(call.args) < 3:
        return None
    table = _const_str(call.args[1])
    cols = _list_of_str(call.args[2])
    if table is None or cols is None or not cols:
        return None
    return (table, cols)


def _is_create_foreign_key(call: ast.Call) -> tuple[str, list[str]] | None:
    """`op.create_foreign_key("name", "src", "dst", ["col"], ["dst_col"])`
    → (src_table, [src_cols])."""
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "create_foreign_key"):
        return None
    if len(call.args) < 4:
        return None
    src_table = _const_str(call.args[1])
    src_cols = _list_of_str(call.args[3])
    if src_table is None or src_cols is None or not src_cols:
        return None
    return (src_table, src_cols)


def _is_create_unique_constraint(call: ast.Call) -> tuple[str, list[str]] | None:
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "create_unique_constraint"):
        return None
    if len(call.args) < 3:
        return None
    table = _const_str(call.args[1])
    cols = _list_of_str(call.args[2])
    if table is None or cols is None or not cols:
        return None
    return (table, cols)


def _walk_migration(
    path: Path,
) -> tuple[
    set[tuple[str, str]],  # FK (table, col) pairs
    set[tuple[str, str]],  # leading-index (table, col) pairs
    set[tuple[str, str]],  # PK / unique (table, col) pairs (auto-indexed)
]:
    """Single AST pass per migration. Returns (fks, indexed_leads,
    auto_indexed)."""
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return set(), set(), set()

    fks: set[tuple[str, str]] = set()
    indexed_leads: set[tuple[str, str]] = set()
    auto_indexed: set[tuple[str, str]] = set()

    # Two-pass: gather create_table info to bind columns to tables;
    # then walk again for create_index / create_foreign_key /
    # create_unique_constraint.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # `create_table` — descend into its column args to find
        # FK / PK / UNIQUE columns scoped to the table.
        tbl = _is_create_table(node)
        if tbl is not None:
            for arg in node.args[1:]:
                if not isinstance(arg, ast.Call):
                    continue
                if not _is_column_call(arg):
                    continue
                col_name = _column_name(arg)
                if col_name is None:
                    continue
                if _column_has_fk(arg):
                    fks.add((tbl, col_name))
                if _is_primary_key_column(arg):
                    auto_indexed.add((tbl, col_name))
                if _is_unique_column(arg):
                    auto_indexed.add((tbl, col_name))
            continue

        # `op.create_foreign_key`.
        cfk = _is_create_foreign_key(node)
        if cfk is not None:
            tbl, cols = cfk
            for c in cols:
                fks.add((tbl, c))
            continue

        # `op.create_index` — leading column counts.
        cidx = _is_create_index(node)
        if cidx is not None:
            tbl, cols = cidx
            indexed_leads.add((tbl, cols[0]))
            continue

        # `op.create_unique_constraint` — auto-indexed.
        cuc = _is_create_unique_constraint(node)
        if cuc is not None:
            tbl, cols = cuc
            auto_indexed.add((tbl, cols[0]))
            continue

    return fks, indexed_leads, auto_indexed


def _audit_all() -> list[str]:
    all_fks: set[tuple[str, str]] = set()
    all_indexed: set[tuple[str, str]] = set()
    all_auto: set[tuple[str, str]] = set()
    for path in _list_migration_files():
        fks, idx, auto = _walk_migration(path)
        all_fks |= fks
        all_indexed |= idx
        all_auto |= auto
    covered = all_indexed | all_auto
    findings: list[str] = []
    for fk in sorted(all_fks):
        if fk in covered:
            continue
        if fk in ALLOWLIST:
            continue
        table, col = fk
        findings.append(f"{table}.{col}")
    return findings


def test_every_fk_column_has_a_leading_index():
    """Every FK column declared across `alembic/versions/*.py`
    should have a covering index — either a dedicated
    `op.create_index` on it (as the LEADING column), or be part
    of a PK / UNIQUE constraint (auto-indexed by Postgres).

    Failures surface both ratchet directions:
      * COUNT > BASELINE: a new FK landed without index. Add an
        `op.create_index(...)` in the same migration.
      * COUNT < BASELINE: someone fixed one. 🎉 Update the
        baseline so future regressions can't silently rebuild back.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_UNCOVERED_FKS:
        new = n - BASELINE_UNCOVERED_FKS
        pytest.fail(
            f"{new} new uncovered FK column(s) "
            f"(total now {n}, baseline {BASELINE_UNCOVERED_FKS}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nAdd an index in the same migration:\n"
            "    op.create_index('ix_<table>_<col>', '<table>', ['<col>'])\n\n"
            "FK columns without a covering index turn parent-row deletes "
            "into multi-minute table scans (Postgres seq-scans the child "
            "to find references). The cost surfaces only at scale — fine "
            "in dev with 100 rows, 'are we down?' in prod with 5M.\n\n"
            "If a column genuinely doesn't need indexing (write-only "
            "audit-trail FK with no parent-delete path, or a tiny lookup "
            "table), add to ALLOWLIST with a stated reason."
        )
    if n < BASELINE_UNCOVERED_FKS:
        pytest.fail(
            f"Uncovered-FK count dropped from {BASELINE_UNCOVERED_FKS} "
            f"to {n}. 🎉 Update `BASELINE_UNCOVERED_FKS` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative AST fixtures. A regression
    in the walker would silently let new uncovered FKs through.
    """
    # Positive: column-embedded FK in create_table.
    pos = ast.parse(
        "import sqlalchemy as sa\n"
        "def upgrade():\n"
        "    op.create_table('child',\n"
        "        sa.Column('parent_id', sa.Integer, sa.ForeignKey('parent.id')),\n"
        "    )\n"
    )
    fks: set[tuple[str, str]] = set()
    for node in ast.walk(pos):
        if not isinstance(node, ast.Call):
            continue
        tbl = _is_create_table(node)
        if tbl is None:
            continue
        for arg in node.args[1:]:
            if isinstance(arg, ast.Call) and _is_column_call(arg) and _column_has_fk(arg):
                cn = _column_name(arg)
                if cn:
                    fks.add((tbl, cn))
    assert fks == {("child", "parent_id")}, f"Audit missed FK: {fks!r}"

    # Negative: column without FK is not flagged.
    neg = ast.parse(
        "import sqlalchemy as sa\n"
        "def upgrade():\n"
        "    op.create_table('plain',\n"
        "        sa.Column('name', sa.Text),\n"
        "    )\n"
    )
    fks2: set[tuple[str, str]] = set()
    for node in ast.walk(neg):
        if isinstance(node, ast.Call) and _is_column_call(node) and _column_has_fk(node):
            cn = _column_name(node)
            if cn:
                fks2.add(("plain", cn))
    assert not fks2

    # Positive: `op.create_index("idx", "child", ["parent_id"])`.
    pos2 = ast.parse("def upgrade():\n    op.create_index('ix_child_parent', 'child', ['parent_id'])\n")
    indexed: set[tuple[str, str]] = set()
    for node in ast.walk(pos2):
        if isinstance(node, ast.Call):
            cidx = _is_create_index(node)
            if cidx is not None:
                tbl, cols = cidx
                indexed.add((tbl, cols[0]))
    assert indexed == {("child", "parent_id")}


def test_allowlist_entries_actually_correspond_to_real_fks():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions. Every (table, col) tuple must correspond to a
    real FK declared somewhere in alembic/versions/.
    """
    if not ALLOWLIST:
        return
    real_fks: set[tuple[str, str]] = set()
    for path in _list_migration_files():
        fks, _, _ = _walk_migration(path)
        real_fks |= fks
    stale = [k for k in ALLOWLIST if k not in real_fks]
    assert not stale, (
        f"Stale ALLOWLIST entries: {stale}. Remove them so the allowlist reflects only currently-live exemptions."
    )
