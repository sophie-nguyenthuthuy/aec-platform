"""Audit: every alembic migration's `upgrade()` has a
non-trivial `downgrade()` covering the same DDL (or is
explicitly allowlisted as one-way).

Pairs with `test_alembic_chain_integrity_audit.py` (which catches
chain corruption: orphan revisions, multi-head, dupes); THIS
audit catches the per-migration corruption that breaks rollback:

  * **`upgrade()` creates a table; `downgrade()` is empty.**
    `alembic downgrade -1` doesn't drop the table — and worse,
    re-running `alembic upgrade head` after a rollback attempt
    fails because the table already exists.

  * **`upgrade()` adds a column; `downgrade()` is empty.** Same
    asymmetry; rollback leaves the schema half-applied.

  * **`upgrade()` runs raw SQL (`op.execute(...)`) but
    `downgrade()` doesn't reverse it.** Common case: a CREATE
    POLICY in upgrade with no matching DROP POLICY in downgrade.

Why this matters during incident response:

A bad migration lands in prod. Ops attempts `alembic downgrade -1`
to roll back. The downgrade is empty. The migration is now
"applied" in `alembic_version` but its DDL is still in place.
The fix path requires manual SQL (drop the table by hand) plus
`alembic stamp` to reconcile — a 15-minute incident becomes a
1-hour incident.

The audit's check is structural: AST-parse `upgrade()` and
`downgrade()`, count the number of `op.<verb>(...)` calls in
each. If `upgrade()` has DDL calls AND `downgrade()` has zero
DDL calls AND the migration isn't allowlisted, that's a bug.

This is intentionally coarse — a perfect symmetry checker would
need to match each verb's inverse (create_table ↔ drop_table,
add_column ↔ drop_column, etc.) and that's brittle. The
"non-empty downgrade" floor is the cheap, robust signal.

Allowlist surface:

  * `_ONE_WAY_MIGRATIONS` — migrations that legitimately have
    no downgrade (data-only seed migrations, or migrations
    explicitly documented as forward-only). Each entry needs a
    rationale comment.

This file is read-only — AST-parses migration files. Survives
reverts.
"""

from __future__ import annotations

import ast
from pathlib import Path


# Allowlist of migration filenames that legitimately have empty
# (or trivially `pass`) downgrades. Each entry needs a rationale
# comment naming WHY the migration is forward-only. PR review of
# an addition checks the rationale.
_ONE_WAY_MIGRATIONS: dict[str, str] = {
    # Format: "<filename>.py": "rationale"
    # Today: empty. If a forward-only migration exists, its
    # filename + rationale lands here.
}


# `op.<verb>` call patterns counted as DDL. These cover the
# overwhelming majority of alembic operations:
#
#   * Schema changes: create_table, drop_table, add_column,
#     drop_column, alter_column, rename_table, create_index,
#     drop_index, create_unique_constraint, create_check_constraint,
#     create_foreign_key, drop_constraint, create_primary_key
#   * Raw SQL: execute (covers CREATE POLICY, custom DDL)
#
# Other op.* calls (e.g. op.bulk_insert) count as DDL too — any
# `op.<anything>(...)` is treated as a DDL statement. The audit
# only excludes `op.get_bind()` and similar query helpers (which
# don't mutate schema).
_DDL_VERB_DENYLIST: frozenset[str] = frozenset(
    {
        # Query / introspection helpers — NOT DDL.
        "get_bind",
        "get_context",
        "inline_literal",
        "f",
        "get_current_revision",
    }
)


def _versions_dir() -> Path:
    return Path(__file__).parent.parent / "alembic" / "versions"


def _count_ddl_calls(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Walk the function body for `op.<verb>(...)` calls. Counts
    every call EXCEPT those whose verb is in `_DDL_VERB_DENYLIST`
    (introspection helpers that don't mutate schema)."""
    count = 0
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match `op.<verb>` attribute access.
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "op" and func.attr not in _DDL_VERB_DENYLIST:
                count += 1
    return count


def _extract_upgrade_downgrade(
    tree: ast.Module,
) -> tuple[ast.FunctionDef | None, ast.FunctionDef | None]:
    """Find the top-level `def upgrade()` and `def downgrade()`
    function nodes in a parsed migration. Returns `(upgrade,
    downgrade)` — either may be None if the function isn't
    declared (rare; would be a separate kind of bug)."""
    up: ast.FunctionDef | None = None
    down: ast.FunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name == "upgrade":
                up = node  # type: ignore[assignment]
            elif node.name == "downgrade":
                down = node  # type: ignore[assignment]
    return up, down


def _walk_migrations():
    """Yield `(filename, upgrade_node, downgrade_node)` for every
    migration file. Skips files that fail to parse (the broader
    test suite catches those)."""
    for py_file in sorted(_versions_dir().glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        up, down = _extract_upgrade_downgrade(tree)
        yield py_file.name, up, down


def test_every_migration_has_upgrade_and_downgrade():
    """Every migration file MUST declare BOTH `def upgrade()`
    and `def downgrade()` — even if downgrade is intentionally
    empty (allowlisted via `_ONE_WAY_MIGRATIONS`).

    Missing function declarations are a different bug shape than
    empty bodies; they cause alembic to choke at import time
    rather than at runtime."""
    missing: list[str] = []
    for filename, up, down in _walk_migrations():
        if up is None:
            missing.append(f"{filename}: missing `def upgrade()`")
        if down is None:
            missing.append(f"{filename}: missing `def downgrade()`")

    assert not missing, (
        "These migration files are missing required functions:\n  " + "\n  ".join(sorted(missing)) + "\n\n"
        "Alembic requires both `upgrade()` and `downgrade()` at "
        "module top-level. A migration without either fails at "
        "import time before alembic even decides what to apply."
    )


def test_downgrade_non_empty_when_upgrade_has_ddl():
    """If a migration's `upgrade()` runs DDL operations, its
    `downgrade()` MUST also run DDL operations (or the migration
    must be in `_ONE_WAY_MIGRATIONS` with a rationale).

    The check is coarse: count `op.<verb>(...)` calls in each
    body. Asymmetric counts (upgrade > 0, downgrade = 0) are
    flagged. A perfect inverse-verb checker (create ↔ drop,
    add ↔ remove) would be brittle; the floor of "downgrade
    isn't empty" catches the cases worth catching.

    Resolution paths:
      1. Add the inverse DDL to downgrade(). Common case.
      2. If the migration is intentionally forward-only (data
         seed, immutable history), add the filename to
         `_ONE_WAY_MIGRATIONS` with a rationale comment.
    """
    asymmetric: list[str] = []
    for filename, up, down in _walk_migrations():
        if filename in _ONE_WAY_MIGRATIONS:
            continue
        if up is None or down is None:
            # Caught by the previous test; don't double-report.
            continue
        up_ddl = _count_ddl_calls(up)
        down_ddl = _count_ddl_calls(down)
        if up_ddl > 0 and down_ddl == 0:
            asymmetric.append(f"{filename}: upgrade has {up_ddl} DDL ops, downgrade has 0")

    assert not asymmetric, (
        "These migrations have a non-empty `upgrade()` but an "
        "empty `downgrade()`:\n  " + "\n  ".join(sorted(asymmetric)) + "\n\n"
        "Why this matters: `alembic downgrade -1` will mark the "
        "migration as un-applied in `alembic_version`, but its "
        "DDL stays in the database. Re-running `alembic upgrade "
        "head` then fails on the duplicate-DDL error. During an "
        "incident this turns a 15-minute rollback into a 1-hour "
        "manual-SQL recovery.\n\n"
        "Resolution:\n"
        "  1. Add the inverse DDL to `downgrade()`. For common "
        "verbs:\n"
        "       op.create_table(X) → op.drop_table(X)\n"
        "       op.add_column(T, C) → op.drop_column(T, C.name)\n"
        "       op.create_index(I, T, [C]) → op.drop_index(I, T)\n"
        "       op.execute('CREATE POLICY ...') → op.execute('DROP POLICY ...')\n"
        "  2. If the migration is intentionally forward-only "
        "(data-seed migrations, immutable history), add the "
        "filename to `_ONE_WAY_MIGRATIONS` with a rationale "
        "comment. PR review of THAT addition checks the rationale."
    )


def test_audit_finds_migration_files():
    """Sanity floor — at least a handful of migrations exist.
    If the alembic/versions dir got moved or wiped, this catches
    it before the symmetry assertions silently pass with zero
    files scanned."""
    files = list(_walk_migrations())
    assert len(files) >= 5, (
        f"Audit found {len(files)} migration files — implausibly "
        "few. Either alembic/versions/ moved (update _versions_dir) "
        "or migrations were wiped (broader regression worth surfacing)."
    )


def test_one_way_allowlist_entries_have_rationale():
    """Every `_ONE_WAY_MIGRATIONS` entry has a non-empty rationale.
    The whole point of the allowlist is the WHY next to the
    entry — bare entries without comments defeat the
    review-the-decision design."""
    for filename, rationale in _ONE_WAY_MIGRATIONS.items():
        assert rationale and rationale.strip(), (
            f"_ONE_WAY_MIGRATIONS entry `{filename}` has empty "
            "rationale. PR reviewers need the WHY alongside the entry."
        )


def test_one_way_allowlist_size_is_minimal():
    """The carve-out for forward-only migrations should stay
    small. Pin a low cap so a future addition is reviewed
    deliberately — incident-response ergonomics get worse with
    each one-way migration that lands."""
    assert len(_ONE_WAY_MIGRATIONS) <= 3, (
        f"_ONE_WAY_MIGRATIONS has {len(_ONE_WAY_MIGRATIONS)} entries: "
        f"{list(_ONE_WAY_MIGRATIONS.keys())}. Each forward-only "
        "migration is a rollback hazard — if the migration above "
        "it on the chain has a bug, the only path back is past "
        "this irreversible step. Keep the set small."
    )
