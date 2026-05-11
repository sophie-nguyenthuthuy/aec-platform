# Runbook: audit suite on-call triage

The on-call procedure when one or more `tests/test_*_audit.py`
files fire red in CI. Pairs with `audit-suite.md` (the
auto-generated index — every audit + its tests) and the per-
audit allowlist comments inside each test file.

The premise: every audit that fires red is doing its job. The
work is triage, not "fix the audit." If the audit's intent has
genuinely drifted (the bug shape it catches is no longer
relevant), the fix is to delete the audit, not to silence it.

## Triage philosophy

```
audit fires red
       │
       ▼
┌──────────────────────────────────┐
│ Read the failure message.        │
│ Every audit's failure prints:    │
│   1. What it caught.             │
│   2. Where (file:line).          │
│   3. The 2-3 resolution paths.   │
└────────────┬─────────────────────┘
             ▼
   ┌─────────┴──────────┐
   │  Resolution path?  │
   └──┬──────┬──────────┘
      │      │
   "fix"   "allowlist"
      │      │
      ▼      ▼
  edit code  add entry to the audit's
  to make    allowlist (FROZENSET / DICT)
  the count  with a one-line rationale.
  drop.      The rationale IS the
             review surface — "didn't
             think about it" is not a
             rationale.
```

Every audit ships with the same shape:

  * A **counter** (line / file / route / table count) compared
    against a **pinned baseline**.
  * An **allowlist** of known-existing offenders with rationale
    per entry.
  * A **sanity floor** — the iteration must find ≥ N files /
    tables / routes; without this, a refactor that wiped the
    target directory would silently make the audit pass.

## When an audit's count grows over baseline

The most common red. A new bug shape slipped in. Steps:

1. **Read the failure message.** It names the new file:line(s).
2. **Decide: fix, narrow, or allowlist.**
   - If the new instance is a bug → fix it.
   - If it's a false positive (the audit's check is broader
     than the bug shape it cares about) → allowlist the
     specific entry with a rationale.
   - If it's a third option (refactor the call site so the
     pattern doesn't apply) → take it.
3. **Don't bump the baseline up.** The baseline is monotonic-
   down. Bumping up loses the entire audit's value: future
   regressions of the same shape get absorbed silently.
4. **Verify the fix locally.**
   ```bash
   pnpm --filter @aec/api exec pytest \
     apps/api/tests/test_<audit_name>.py -v
   ```

## When an audit's count drops below baseline

A 🎉 path — someone fixed N entries. The audit fails to FORCE
the baseline update in the same PR as the fix.

1. The failure message names the new (smaller) count.
2. Update `BASELINE_<NAME>` in the audit file to the new
   count.
3. Commit alongside the fix.

If the new count is 0, the next step is to **flip the
assertion** from `<= BASELINE` to `== 0` and remove the
baseline constant entirely. The audit becomes a strict-zero
ratchet from that point.

## Per-audit triage cards

The currently-red audits + their triage flow.

### `test_orm_tables_organization_id_audit.py`

**What red means:** an ORM table without `organization_id` is
flagged. SECURITY: a tenant-bearing table without that column
can't have RLS policies that filter by tenant; reads + writes
succeed cross-tenant by default.

**Triage flow:**

1. **Decide if the table is tenant-bearing or global.**
   - Tenant-bearing → add `organization_id: Mapped[UUID]` to
     the model + a follow-up alembic migration that adds the
     column with a default backfill.
   - Global (public reference data, ops telemetry, etc.) →
     add to `_GLOBAL_TABLES` with a rationale.
   - Tenant-via-parent (FK CASCADE to a table that DOES have
     `organization_id`) → also goes in `_GLOBAL_TABLES` with
     rationale naming the parent. Verify EVERY handler that
     reads the child joins through the parent — RLS is per-
     table, not transitive.

2. **Pair with the RLS policy.** Adding `organization_id` is
   step 1; the migration must ALSO run `CREATE POLICY
   tenant_isolation_<table>` per `docs/runbook-rls-policies.md`.

3. **Verify with the smoke test.** Set
   `app.current_org_id` to one tenant in psql; SELECT against
   the table; confirm only that tenant's rows return.

### `test_tenant_predicate_audit.py`

**What red means:** a raw SQL query in a router file lacks
`organization_id = :org_id` in its predicate. Same family as
the ORM-tables audit; this one watches the raw-SQL plane.

**Triage flow:**

1. **Read the failure list.** It names file:line and the
   first 80 chars of the offending SQL.
2. **For each new entry, decide:**
   - Does the query actually need tenant-scoping? Most do —
     add the predicate.
   - Is it scoped via a different mechanism (RLS through the
     joined parent)? Add to the audit's per-file allowlist
     with a rationale naming the mechanism.
3. **Don't trust "RLS will catch it."** If the handler uses
   `AdminSessionFactory` (BYPASSRLS), RLS isn't filtering.
   The audit assumes the worst case — handler-level scoping
   AND RLS as defense-in-depth.

### `test_audit_completeness_audit.py`

**What red means:** a state-changing route doesn't call
`services.audit.record(...)` in its body.

**Triage flow:**

1. **Identify the new route(s).** Recent commit history is
   the easiest source: `git log -p --since="2 weeks ago" --
   apps/api/routers/` and grep for `@router.(post|put|patch|
   delete)`.
2. **For each, decide:**
   - **Mutating action with an actor** → add a `record(...)`
     call to the handler body before the response.
   - **Stateless / public / read-shaped POST** (HMAC verify,
     health check, signed-URL diagnostics) → add the
     contract-recognised marker comment in the handler body:
     ```python
     # audit-trail: <one-line rationale>
     ```
     The audit's regex matches the comment text and treats
     the handler as audited.
   - **Streaming / SSE** → the underlying mutation auditing
     covers it; add to the audit's `ALLOWLIST` dict keyed on
     `(path_substring, method)` with a rationale.

### `test_audit_action_callsite_audit.py`

**What red means:** a `record(action=...)` call uses a
non-literal expression (variable, ternary, dict-lookup). The
audit can't statically verify the action string is in the
`AuditAction` Literal.

**Triage flow:**

1. **Read the file:line.** Look at the surrounding code.
2. **For each, decide:**
   - **Refactor to literal strings** (preferred) — split the
     conditional into two `record(...)` calls, each with a
     literal `action=`. The static check covers both branches.
   - **Allowlist the call site** — add the `<file>:<line>`
     entry to `_DYNAMIC_ACTION_CALL_SITES` with a rationale
     naming the constraint (e.g. "ternary; both branches are
     AuditAction members" / "dict-lookup keyed by Pydantic
     Enum constrained to N members").

### `test_openapi_route_docs_audit.py`

**What red means:** a route is missing `response_model=Foo` in
its decorator (or a `-> Foo` return-type annotation). The
OpenAPI spec renders the route with no response shape.

**Triage flow:**

1. **Identify the new routes.** Same `git log` approach as
   `test_audit_completeness_audit.py`.
2. **For each, decide:**
   - **Add `response_model=Foo`** — the canonical fix.
     Pydantic schema lives in `apps/api/schemas/<topic>.py`;
     declare a `Foo` model and use it in the decorator.
   - **Streaming / NDJSON / file-download endpoint** → the
     response body isn't a JSON model. Add to the audit's
     `RESPONSE_MODEL_ALLOWLIST` with a one-line reason.

### `test_alembic_chain_integrity_audit.py`

**What red means:** the migration chain has dangling
references, multi-head branches, filename↔revision mismatches,
or cycles. See `docs/runbook-migration-rollback.md` for the
detailed triage of each known chain bug.

### `test_migration_upgrade_downgrade_symmetry_audit.py`

**What red means:** an `upgrade()` has a non-empty body but
`downgrade()` is empty / no-op. Rollbacks would silently fail.

**Triage flow:**

1. **Read the migration's `upgrade()`.** Note every
   `op.create_table` / `op.add_column` / `op.execute(...)`.
2. **Write the inverse in `downgrade()`.** `drop_table`
   undoes `create_table`; `drop_column` undoes `add_column`;
   for `op.execute("CREATE POLICY ...")`, the inverse is
   `op.execute("DROP POLICY IF EXISTS ...")`.
3. **Test it:** apply the migration, then `alembic
   downgrade -1`, then `alembic upgrade head` again. The
   schema should be byte-identical at the end.

## When the audit's intent has genuinely drifted

Rare but not zero. The audit was written when bug shape X
mattered; the codebase has shifted enough that X is no longer
the right ratchet. Symptoms:

  * The allowlist grew over many PRs, each entry with a
    different rationale that doesn't share a theme.
  * The audit's per-failure resolution path keeps being
    "allowlist with rationale" rather than a real fix.

Resolution: write a postmortem-style PR that **deletes the
audit**, with the PR description naming why the bug shape no
longer applies. Don't keep the audit running just to absorb
allowlist entries — that's the worst outcome (the audit looks
green but covers nothing).

## When you're not sure if a red is real

The audit's docstring is the canonical answer to "what is this
audit FOR?". Read it before deciding. Failure messages are
intentionally short; the docstring carries the rationale and
the bug shape.

If the docstring doesn't make the case, that's a docs bug —
file a follow-up to clarify it. The audit is a contract; an
under-documented audit is a weak contract.

## Related runbooks + audits

| Surface | Lives in |
| --- | --- |
| Audit suite spec view | [`audit-suite.md`](audit-suite.md) (auto-generated) |
| Cross-tenant exposure incident | [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) |
| RLS policy convention | [`runbook-rls-policies.md`](runbook-rls-policies.md) |
| Migration rollback | [`runbook-migration-rollback.md`](runbook-migration-rollback.md) |
| API key surface | [`runbook-api-keys.md`](runbook-api-keys.md) |

## What this runbook is NOT for

- **An audit fired green.** That's the audit doing its job
  silently. No action.
- **A test that's not an audit.** This runbook covers
  `tests/test_*_audit.py` only. Pin tests
  (`tests/test_*_pin.py`) have a different triage flow —
  usually a single contract changed.
- **A flaky audit.** If the same audit fires red AND green
  on the same code, file an issue against the audit. Audits
  must be deterministic; flakiness undermines the entire
  ratchet pattern.
