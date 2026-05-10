# Runbook: RLS policies — convention + how to add one

Reference for the RLS (Row-Level Security) policies that protect
against cross-tenant data leaks at the database layer. Pairs
with the audits:

- `tests/test_orm_tables_organization_id_audit.py` — every
  tenant-bearing table has the `organization_id` column.
- `tests/test_rls_policy_coverage_audit.py` — every tenant-
  bearing table has at least one `CREATE POLICY` in migrations.

## Why RLS

The platform runs every customer-facing request through a
`TenantAwareSession` that binds to the NOBYPASSRLS database role
(`aec_app`). RLS policies on each tenant-bearing table filter
queries on `organization_id`. The session sets a Postgres GUC
(`app.current_org_id`) at the start of each transaction; the
policy reads that GUC and filters accordingly.

The result: even a buggy handler that forgets to filter by
`auth.organization_id` in its WHERE clause STILL gets the right
rows back, because the database is filtering. RLS is the
defense-in-depth layer beneath every handler's explicit scoping.

The two layers must both be in place:

| Layer | Defended by |
| --- | --- |
| Handler-level WHERE clause | Code review + per-router pin tests |
| RLS policy at the table | Database CREATE POLICY + this runbook's audit |

Either alone is incomplete. RLS is the safety net; the audits
catch the cases where the safety net has a hole.

## The canonical policy

Every tenant-bearing table has a policy of this exact shape:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_<table> ON <table>
USING (
    organization_id = current_setting('app.current_org_id', true)::uuid
);
```

Field-by-field:

- **`tenant_isolation_<table>`** — the policy name. The audit's
  substring matcher recognises this prefix, so following the
  convention means the audit "just works." Custom names
  (`<table>_rls`, `org_filter_<table>`, etc.) require adding the
  table to the audit's allowlist with a rationale.

- **`USING (...)`** — applies to SELECT, UPDATE, DELETE. A row
  is visible iff its `organization_id` matches the GUC.

- **`current_setting('app.current_org_id', true)`** — reads the
  per-transaction GUC the `TenantAwareSession` sets. The `true`
  argument means "return NULL if unset" rather than raising —
  important because admin-session paths legitimately don't set
  the GUC.

- **`::uuid`** — the GUC is a string; cast back to UUID for the
  comparison. Postgres optimises this away for an indexed lookup.

## When you also need WITH CHECK

The above policy filters reads + mutations, but lets a tenant
INSERT a row with ANY `organization_id` (it doesn't constrain
inserts). For tables where the API never overrides org-id (most
of them), this is fine — the handler builds the row with
`organization_id=auth.organization_id` and the column-level
constraint is enforced.

For tables where the API DOES accept org-id from clients (very
rare; the input-schemas audit pins this), add a `WITH CHECK`
clause:

```sql
CREATE POLICY tenant_isolation_<table> ON <table>
USING (
    organization_id = current_setting('app.current_org_id', true)::uuid
)
WITH CHECK (
    organization_id = current_setting('app.current_org_id', true)::uuid
);
```

The `WITH CHECK` clause runs on INSERT/UPDATE: it rejects rows
where the new `organization_id` doesn't match the GUC. Belt-and-
suspenders against a buggy handler that managed to receive a
cross-tenant org id from the client.

## Writing a new RLS policy in a migration

When you add a tenant-bearing table, the same migration that
runs `op.create_table(...)` MUST also run the RLS setup. Pattern:

```python
def upgrade() -> None:
    op.create_table(
        "my_new_table",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        # ... other columns ...
    )

    # RLS — the audits will fail without this block.
    op.execute("ALTER TABLE my_new_table ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_my_new_table ON my_new_table "
        "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
    )


def downgrade() -> None:
    # The migration symmetry audit requires a non-empty downgrade.
    # Drop the policy AND the table so re-running upgrade works.
    op.execute("DROP POLICY IF EXISTS tenant_isolation_my_new_table ON my_new_table")
    op.execute("ALTER TABLE my_new_table DISABLE ROW LEVEL SECURITY")
    op.drop_table("my_new_table")
```

For a batch of tables (the convention in `0001_core.py`,
`0003_siteeye.py`, etc.), use a Python loop to keep the
boilerplate proportional:

```python
TENANT_TABLES = (
    "my_new_table_a",
    "my_new_table_b",
    "my_new_table_c",
)


def upgrade() -> None:
    op.create_table("my_new_table_a", ...)
    op.create_table("my_new_table_b", ...)
    op.create_table("my_new_table_c", ...)

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("my_new_table_c")
    op.drop_table("my_new_table_b")
    op.drop_table("my_new_table_a")
```

The audit's substring matcher recognises the templated form
because the literal table name appears in the tuple AND the file
contains `CREATE POLICY`.

## Verifying RLS is actually active

The migration applied; the policy was created. Is RLS actually
filtering? Three checks ops can run by hand:

### 1. Confirm RLS is enabled on the table

```sql
SELECT relname, relrowsecurity, relforcerowsecurity
FROM pg_class
WHERE relname = '<table>';
```

`relrowsecurity = t` means RLS is on. `relforcerowsecurity = t`
means RLS applies even to the table owner — usually not needed
because we run as `aec_app` (NOBYPASSRLS) anyway.

### 2. List policies on the table

```sql
SELECT polname, polcmd, pg_get_expr(polqual, polrelid) AS using_expr
FROM pg_policy
WHERE polrelid = '<table>'::regclass;
```

You should see one row per policy. `polcmd = '*'` means the
policy applies to all commands (SELECT/UPDATE/DELETE/INSERT).
The `using_expr` shows the actual filter — verify it references
`current_setting('app.current_org_id', true)::uuid`.

### 3. Smoke-test as the runtime role

```sql
-- Set the GUC to one tenant.
SET app.current_org_id = '<tenant-A-uuid>';

-- This SELECT should only see tenant-A rows.
SELECT id, organization_id FROM <table> LIMIT 10;

-- Try to read a known tenant-B row.
SELECT * FROM <table> WHERE id = '<known-tenant-B-id>';
-- Returns 0 rows.

-- Reset.
RESET app.current_org_id;
```

If the cross-tenant SELECT returns rows when the GUC is set, the
policy is broken. Cases:
- The policy uses the wrong column (e.g. `org_id` vs
  `organization_id`).
- The table has `relforcerowsecurity = f` AND you're connected
  as the table owner (the `aec` superuser, BYPASSRLS).
- The GUC is being set on the wrong session.

### 4. Verify a handler's session DOES set the GUC

The `TenantAwareSession` wrapper is what sets
`app.current_org_id` at the start of each transaction. If a
handler is using `AdminSessionFactory` instead (which is
BYPASSRLS by design), RLS is bypassed regardless of policy.

The `test_admin_session_factory_usage_audit.py` audit pins which
routers may legitimately use `AdminSessionFactory`. Anything
not in that allowlist using the admin session is a bug.

## Common mistakes

### Forgot `ENABLE ROW LEVEL SECURITY`

`CREATE POLICY` alone doesn't activate RLS. The
`ALTER TABLE ... ENABLE ROW LEVEL SECURITY` statement is what
turns it on. A migration that creates the policy but skips the
ALTER leaves RLS disabled.

The RLS coverage audit doesn't catch this (it only checks for
`CREATE POLICY`), but the smoke test above (#1) does.

### Used `BYPASSRLS` role for normal traffic

`AdminSessionFactory` binds to the `aec` superuser which has
BYPASSRLS — every query bypasses every policy. If a user-facing
handler uses this factory, RLS is silently disabled regardless
of policy.

The `test_admin_session_factory_usage_audit.py` audit pins this.

### Custom policy name without allowlist

If you write a policy named `<table>_org_filter` instead of
`tenant_isolation_<table>`, the RLS coverage audit's substring
matcher won't recognise it. Either:
- Rename the policy to the convention (preferred), OR
- Add the table to `_TABLES_WITHOUT_RLS_POLICY` in the audit
  with a rationale comment naming the alternative policy name.

### Wrong column in the policy

`organization_id` is the canonical column name (pinned by the
ORM-tables audit). A policy that filters on `org_id`,
`tenant_id`, or `customer_id` either:
- 42703-errors at policy-create time (column doesn't exist), OR
- Filters on a different (probably-NULL) column, letting every
  row pass.

Always verify the smoke test (#3) shows the policy actually
filters.

## Related code + tests

| Component | Lives in |
| --- | --- |
| Tenant-aware session wrapper | `db/session.py::TenantAwareSession` |
| Admin session factory (BYPASSRLS) | `db/session.py::AdminSessionFactory` |
| RLS migration loop convention | `alembic/versions/0001_core.py` |
| Substring-based audit | `tests/test_rls_policy_coverage_audit.py` |
| Org-id column audit | `tests/test_orm_tables_organization_id_audit.py` |
| Admin-session allowlist | `tests/test_admin_session_factory_usage_audit.py` |
| DB factories pin | `tests/test_db_session_factories_pin.py` |

## When ops should NOT touch RLS in production

- **Mid-incident** — disabling RLS to "see what's going on" is
  a path to cross-tenant data exposure. Use the smoke test
  patterns above, which set the GUC explicitly within a
  transaction, instead.

- **Without a follow-up migration** — running `ALTER TABLE
  DISABLE ROW LEVEL SECURITY` on a live table reverts the table
  to no protection until the next deploy re-enables it. Always
  pair with an alembic migration so the change is durable +
  reviewed.

- **As a "performance fix"** — RLS overhead in this codebase is
  microsecond-scale (the policy is an indexed equality check on
  `organization_id`). If a query is slow, the issue is almost
  certainly elsewhere.
