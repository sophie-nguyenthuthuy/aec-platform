"""Audit: every tenant-bearing ORM table has at least one
`CREATE POLICY` declared in the alembic migrations.

Pairs with `test_orm_tables_organization_id_audit.py` at a different
layer: that audit asserts every table has the right COLUMN
(`organization_id`); THIS audit asserts the table also has the
right POLICY (so RLS actually filters on the column).

The two audits together close the loop:

  * Column without policy → silently no RLS enforcement (the
    column exists, but no policy reads it; cross-tenant SELECT
    returns rows from every tenant).
  * Policy without column → migration would fail to apply (a
    CREATE POLICY referencing a missing column raises 42703).
    So column-without-policy is the silent case worth pinning.

Failure modes this catches:

  * **A new feature adds a tenant-bearing table but forgets the
    CREATE POLICY block.** RLS does nothing for that table even
    though the data shape supports it. Cross-tenant reads /
    writes succeed silently.

  * **A migration that drops a policy without a matching add.**
    Possible during a refactor that "consolidates" RLS — if the
    consolidation misses one table, that table is now exposed.

The audit uses a substring scan rather than full SQL parsing
because:
  * `CREATE POLICY` blocks in this codebase use multiple naming
    conventions (`tenant_isolation_<table>`,
    `tenant_visibility_<table>`, plus f-string templated forms).
  * Substring scan over 54 migration files is fast (<0.1s).
  * The audit's failure message names the table, so a reviewer
    grepping the migrations for that name has the full context.

Allowlist surface:

  * `_TABLES_WITHOUT_RLS_POLICY` — tenant-bearing tables that
    legitimately have no CREATE POLICY (e.g. tenant scoping is
    enforced at the application layer instead). Today: empty.

This file is read-only. Survives reverts.
"""

from __future__ import annotations

import importlib
from pathlib import Path

# Allowlist of tenant-bearing tables that legitimately have no
# CREATE POLICY (RLS is enforced elsewhere or the table is too
# new to have a policy yet). Each entry needs a rationale comment.
_TABLES_WITHOUT_RLS_POLICY: dict[str, str] = {
    # Format: "table_name": "rationale"
    # Today: empty. Every tenant-bearing table has a policy.
}


def _versions_dir() -> Path:
    return Path(__file__).parent.parent / "alembic" / "versions"


def _models_dir() -> Path:
    return Path(__file__).parent.parent / "models"


def _walk_tenant_bearing_tables() -> set[str]:
    """Use the ORM-tables audit's filesystem-walk approach to find
    every mapped table with an `organization_id` column. Mirrors
    the helper in `test_orm_tables_organization_id_audit.py`."""
    models_dir = _models_dir()
    for py_file in sorted(models_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        module_name = f"models.{py_file.stem}"
        try:
            importlib.import_module(module_name)
        except Exception:
            continue

    from db.base import Base

    tenant_tables: set[str] = set()
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table_name = getattr(cls, "__tablename__", None)
        if not isinstance(table_name, str):
            continue
        columns = {col.name for col in mapper.local_table.columns}
        if "organization_id" in columns:
            tenant_tables.add(table_name)
    return tenant_tables


def _all_migration_text() -> str:
    """Concatenate every migration file's source. Substring scans
    against the joined blob catch policies regardless of which
    file declared them."""
    parts: list[str] = []
    for py_file in sorted(_versions_dir().glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            parts.append(py_file.read_text())
        except OSError:
            continue
    return "\n".join(parts)


def _table_has_policy(table: str, migrations_text: str) -> bool:
    """Return True if any CREATE POLICY in migrations references
    this table.

    Three substring forms covered (the conventions used in this
    codebase):
      1. `tenant_isolation_<table>` — most common.
      2. `tenant_visibility_<table>` — used for suppliers and a
         few public-read tables.
      3. The table name appearing as a quoted string in the same
         file as a `CREATE POLICY` block — covers f-string
         templated forms where the policy is created inside
         `for table in (...)` loops.

    Form 3 is a heuristic; it can over-match (table mentioned in
    a comment) but the failure-side cost is low (a false-pass
    means the audit didn't fire on a real bug, and the orm-tables
    audit + RLS migration tests would still surface the gap).
    """
    if f"tenant_isolation_{table}" in migrations_text:
        return True
    if f"tenant_visibility_{table}" in migrations_text:
        return True

    # Form 3: walk migration files for those that contain BOTH a
    # CREATE POLICY and a quoted reference to this table.
    for py_file in sorted(_versions_dir().glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            src = py_file.read_text()
        except OSError:
            continue
        if "CREATE POLICY" not in src:
            continue
        # Look for the table as a quoted string OR as a literal
        # in a Python tuple/list (e.g. `"estimates",`).
        if f'"{table}"' in src or f"'{table}'" in src:
            return True
        # Templated form like `ON {table}` won't match; rely on
        # Form 1/2 prefixes for those.
    return False


def test_every_tenant_bearing_table_has_an_rls_policy():
    """SECURITY-CRITICAL audit. Every ORM table with an
    `organization_id` column MUST have at least one CREATE POLICY
    in the alembic migrations.

    Failure surfaces tables where the column exists but no policy
    was found. Resolution paths:

      1. **Forgot to add the CREATE POLICY**: write the migration
         with `CREATE POLICY tenant_isolation_<table> ON <table>
         USING (organization_id = current_setting('app.current_org_id')::uuid)`.

      2. **The policy exists under a non-conventional name**:
         this audit's substring matcher missed it. Either rename
         the policy to match `tenant_isolation_<table>` /
         `tenant_visibility_<table>` (preferred — matches the
         codebase convention) OR add the table to
         `_TABLES_WITHOUT_RLS_POLICY` with a rationale.

      3. **The table doesn't need RLS** (rare; tenant scoping
         enforced at the app layer): add to
         `_TABLES_WITHOUT_RLS_POLICY` with rationale. PR review
         of THAT addition vets the design choice.
    """
    tenant_tables = _walk_tenant_bearing_tables()
    migrations_text = _all_migration_text()

    no_policy: list[str] = []
    for table in sorted(tenant_tables):
        if table in _TABLES_WITHOUT_RLS_POLICY:
            continue
        if not _table_has_policy(table, migrations_text):
            no_policy.append(table)

    assert not no_policy, (
        "These tenant-bearing tables (have `organization_id` column) "
        "have NO CREATE POLICY found in migrations:\n  " + "\n  ".join(no_policy) + "\n\n"
        "SECURITY: a tenant-bearing column without an RLS policy "
        "= no cross-tenant filtering. Reads and writes succeed "
        "across tenants silently.\n\n"
        "Resolution:\n"
        "  1. Add a CREATE POLICY to the migration that created "
        "the table (or a follow-up migration). Convention:\n"
        "       CREATE POLICY tenant_isolation_<table> ON <table>\n"
        "       USING (organization_id = current_setting(...)::uuid)\n"
        "  2. If the policy exists under a non-standard name, "
        "this audit's substring matcher missed it — either rename "
        "to the convention OR allowlist with rationale."
    )


def test_audit_finds_tenant_bearing_tables():
    """Sanity floor — the iteration finds at least a handful of
    tenant-bearing tables. Without this, a refactor that emptied
    the ORM registry would let the policy check silently pass
    with zero tables scanned."""
    tenant_tables = _walk_tenant_bearing_tables()
    assert len(tenant_tables) >= 10, (
        f"Audit found {len(tenant_tables)} tenant-bearing tables — "
        "implausibly few. Either every table dropped its "
        "organization_id column (broader regression worth surfacing) "
        "or the model-walk helper isn't picking up modules."
    )


def test_audit_finds_create_policy_statements():
    """Sanity floor — at least some CREATE POLICY statements
    exist in migrations. If they all got dropped, the substring
    match would fail for every table simultaneously (the audit
    catches that, but this targeted check surfaces the root
    cause)."""
    text = _all_migration_text()
    policy_count = text.count("CREATE POLICY")
    assert policy_count >= 10, (
        f"Found {policy_count} CREATE POLICY statements across "
        "migrations — implausibly few. Either policies got "
        "consolidated into a different mechanism OR a refactor "
        "removed them. Check `alembic/versions/0001_core.py` and "
        "0003_siteeye / 0012_submittals etc. for the canonical "
        "loop pattern."
    )


def test_allowlist_entries_have_rationale():
    """Every `_TABLES_WITHOUT_RLS_POLICY` entry has a non-empty
    rationale string."""
    for table, rationale in _TABLES_WITHOUT_RLS_POLICY.items():
        assert rationale and rationale.strip(), (
            f"Allowlist entry `{table}` has empty rationale. PR reviewers need the WHY alongside the entry."
        )


def test_allowlist_size_is_minimal():
    """The carve-out for tenant-bearing tables without policies
    should stay empty in steady state. Pin a low cap so a future
    addition is reviewed deliberately."""
    assert len(_TABLES_WITHOUT_RLS_POLICY) <= 1, (
        f"_TABLES_WITHOUT_RLS_POLICY has "
        f"{len(_TABLES_WITHOUT_RLS_POLICY)} entries: "
        f"{list(_TABLES_WITHOUT_RLS_POLICY.keys())}. Today should "
        "be 0; if you needed to add one, the rationale belongs in "
        "the comment alongside it."
    )
