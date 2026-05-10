# Audit suite — runbook map

Single source of truth for "an audit fired red — where do I read
to fix it?". Companion to the auto-generated
[`audit-suite.md`](audit-suite.md) (which lists every audit's
tests verbatim) — this doc is the **curated** view: audits
grouped by category, paired with the runbook that explains the
remediation, and the count of TODO-triage entries currently in
each audit's allowlist.

The relationship between the two docs:

| Doc | Generated? | Purpose |
| --- | --- | --- |
| [`audit-suite.md`](audit-suite.md) | yes (from docstrings) | "What does each audit assert?" — the spec view |
| `audit-suite-overview.md` (this) | hand-curated | "An audit fired — what runbook do I open?" — the on-call view |

If you're adding a new audit, BOTH docs need an entry: the
generator updates `audit-suite.md`; you add the row here by hand.
The contribution checklist at the bottom enumerates the steps.

## The audit-ratchet philosophy

Every audit in this suite follows the same shape:

1. **Walk the codebase**, find every instance of a regression
   shape (an admin route without a role gate, a tenant-bearing
   table without an RLS policy, a `__all__` entry that doesn't
   resolve, etc.).
2. **Compare to a pinned baseline** — usually a frozenset / dict
   allowlist of "known existing offenders, with rationale per
   entry."
3. **Fail if the count grew** (a new offender slipped in) AND
   **fail if the count shrank** (someone fixed an entry but
   forgot to delete the allowlist row, which leaves the audit
   blind to future regressions of that exact name).

The allowlist IS the triage list. An entry has the form:

```python
"routers/sandbox.py": "TODO(SCRAPE-247): unmounted; either mount in main.py or delete the file",
```

The rationale + ticket reference is mandatory. A bare
`"routers/sandbox.py": ""` fails the
`*_audit_allowlist_entries_have_rationale` test that every audit
ships with.

**The ratchet only goes DOWN.** Adding a new entry to an
allowlist requires PR review. Removing an entry (because the
underlying bug got fixed) is encouraged and ships in the same PR
as the fix.

---

## Cross-tenant security perimeter

These audits exist to PREVENT a cross-tenant data exposure
incident. If any of them fires red, the response is "stop the
PR, do not deploy." If a cross-tenant exposure happens despite
green audits, the post-incident review widens this suite (see
[`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md)).

| Audit | Catches | Runbook | Allowlist size |
| --- | --- | --- | --- |
| `tests/test_admin_session_factory_usage_audit.py` | A user-facing handler using `AdminSessionFactory` (BYPASSRLS) instead of `TenantAwareSession` | [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) | 9 routers (curated allowlist) |
| `tests/test_admin_routes_role_gate_audit.py` | New admin endpoint shipped without a `require_role`/`require_min_role` dep in its tree | [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) | 0 (intentionally-public admin routes only) |
| `tests/test_input_schemas_no_organization_id_audit.py` | Client overriding tenant via request body (an input schema accepting `organization_id`) | [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) | tracked allowlist |
| `tests/test_output_schemas_no_secret_fields_audit.py` | Server leaking secret material (API key plaintext, signing secret, password hash) via response | [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) + [`runbook-api-keys.md`](runbook-api-keys.md) | tracked allowlist |
| `tests/test_orm_tables_organization_id_audit.py` | New tenant-bearing table without the `organization_id` column | [`runbook-rls-policies.md`](runbook-rls-policies.md) | non-tenant tables (curated set) |
| `tests/test_rls_policy_coverage_audit.py` | Tenant-bearing table without a `tenant_isolation_<table>` RLS policy | [`runbook-rls-policies.md`](runbook-rls-policies.md) | 0 — currently green |
| `tests/test_tenant_predicate_audit.py` | A query that filters on the wrong column (e.g. `assignee_id = auth.organization_id`) | [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) | tracked allowlist |
| `tests/test_secret_access_audit.py` | Code reading raw secret material outside the canonical service path | [`runbook-api-keys.md`](runbook-api-keys.md) | tracked allowlist |

---

## Migration / schema health

These audits keep the alembic chain coherent and ensure schema
changes ship with the operational hooks ops needs.

| Audit | Catches | Runbook | Allowlist size |
| --- | --- | --- | --- |
| `tests/test_alembic_chain_integrity_audit.py` | Orphan revisions, multi-head chain, filename↔revision mismatches, cycles | [`runbook-migration-rollback.md`](runbook-migration-rollback.md) | **7 known bugs** (`_KNOWN_DANGLING_DOWN_REVISIONS`, `_KNOWN_MULTI_HEAD_REVISIONS`, `_KNOWN_FILENAME_MISMATCHES`) |
| `tests/test_migration_upgrade_downgrade_symmetry_audit.py` | An `upgrade()` with an empty / no-op `downgrade()` | [`runbook-migration-rollback.md`](runbook-migration-rollback.md) | 0 — currently green |
| `tests/test_migration_safety_audit.py` | Destructive DDL (drop column, alter type, NOT NULL without backfill) without explicit opt-in | [`runbook-migration-rollback.md`](runbook-migration-rollback.md) | tracked allowlist |
| `tests/test_fk_index_coverage_audit.py` | Foreign key column without a covering index (slow joins; lock-amplification on cascade) | [`runbook-migration-rollback.md`](runbook-migration-rollback.md) | tracked allowlist |
| `tests/test_fk_ondelete_audit.py` | FK without an explicit `ON DELETE` (`CASCADE` / `SET NULL` / `RESTRICT`) | [`runbook-migration-rollback.md`](runbook-migration-rollback.md) | tracked allowlist |

---

## Router & API surface invariants

These audits keep the FastAPI surface coherent: every router is
mounted, every handler is async, every endpoint has the
machinery (docstring, tag, status code) it needs to render in
the OpenAPI spec.

| Audit | Catches | Runbook | Allowlist size |
| --- | --- | --- | --- |
| `tests/test_every_router_mounted_in_main_audit.py` | A `routers/X.py` file that defines a `router` but isn't `include_router(...)`'d in `main.py` | [`admin-surfaces.md`](admin-surfaces.md) (contribution checklist) | **1 known bug**: `routers/sandbox.py` (unmounted; see `_UNMOUNTED_ROUTERS_ALLOWLIST`) + `codeguard_quota` (legitimate sub-router delegation) |
| `tests/test_router_handlers_are_async_audit.py` | A `@router.get(...)` decorating a sync `def` (silent perf footgun under uvicorn) | [`admin-surfaces.md`](admin-surfaces.md) | 0 — currently green |
| `tests/test_router_commit_audit.py` | A mutating handler that doesn't `db.commit()` before returning | _(no runbook — code-style)_ | tracked allowlist |
| `tests/test_router_docstring_audit.py` | A handler missing a docstring (renders as empty in OpenAPI) | _(no runbook — code-style)_ | tracked allowlist |
| `tests/test_openapi_route_docs_audit.py` | A route missing summary / description / response model | _(no runbook — code-style)_ | tracked allowlist |
| `tests/test_openapi_tags_audit.py` | A router without a tag (groups orphan endpoints in OpenAPI) | _(no runbook — code-style)_ | tracked allowlist |
| `tests/test_http_status_constants_audit.py` | Hardcoded numeric status (`status_code=404`) instead of `status.HTTP_404_NOT_FOUND` | _(no runbook — code-style)_ | tracked allowlist |

---

## Operational integrations

These audits guard the wires between the API and external
systems (Slack, webhooks, cron, audit log) — the surfaces ops
actively triage.

| Audit | Catches | Runbook | Allowlist size |
| --- | --- | --- | --- |
| `tests/test_audit_action_callsite_audit.py` | A `record(action="...")` callsite using a string not in the `AuditAction` Literal | _(no runbook — invariant pin)_ | tracked allowlist |
| `tests/test_audit_completeness_audit.py` | A mutating endpoint with no `record(...)` call in its body | _(no runbook — invariant pin)_ | tracked allowlist |
| `tests/test_cron_mutex_audit.py` | A cron handler without `@with_cron_mutex` | [`runbook-cron-admin.md`](runbook-cron-admin.md) + [`runbook-cron-watchdog.md`](runbook-cron-watchdog.md) | tracked allowlist |
| `tests/test_worker_retry_policy_audit.py` | A worker task without an explicit retry budget | _(no runbook yet)_ | tracked allowlist |
| `tests/test_rate_limit_audit.py` | A user-facing endpoint without a rate-limit declaration | _(no runbook yet)_ | tracked allowlist |
| `tests/test_idempotency_contract_audit.py` | A POST/PUT mutator without idempotency-key handling | _(no runbook yet)_ | tracked allowlist |

---

## Code-style & hygiene

The "low-stakes individually, but they accumulate" tier. None of
these is a deploy-blocker on its own; collectively they keep the
codebase from drifting into the "every file follows its own
rules" antipattern.

| Audit | Catches | Allowlist size |
| --- | --- | --- |
| `tests/test_future_annotations_import_audit.py` | A `.py` file under `apps/api/` missing `from __future__ import annotations` | 0 — currently green |
| `tests/test_dunder_all_consistency_audit.py` | An entry in a module's `__all__` that doesn't match a top-level symbol; a leading-underscore name in `__all__` | 0 — currently green |
| `tests/test_assert_in_production_audit.py` | A bare `assert` in non-test code (gets stripped under `python -O`) | tracked allowlist |
| `tests/test_print_in_production_audit.py` | A `print(...)` in non-test code (use the structured logger) | tracked allowlist |
| `tests/test_naive_datetime_audit.py` | A `datetime.now()` / `datetime.utcnow()` call (use `datetime.now(timezone.utc)`) | tracked allowlist |
| `tests/test_noqa_specificity_audit.py` | A bare `# noqa` without a rule code (silences ALL ruff rules at that line) | tracked allowlist |
| `tests/test_type_ignore_specificity_audit.py` | A bare `# type: ignore` without an error-code suffix (silences ALL mypy errors at that line) | tracked allowlist |
| `tests/test_pydantic_strictness_audit.py` | A Pydantic model without `ConfigDict(extra="forbid")` (silently accepts unknown fields) | tracked allowlist |
| `tests/test_pydantic_field_constraint_audit.py` | A field without an explicit min/max constraint where one is appropriate (e.g. unbounded `str` for IDs) | tracked allowlist |
| `tests/test_logging_structure_audit.py` | An `f"..."`-formatted log line (loses structured-field extraction) | tracked allowlist |
| `tests/test_complexity_budget_audit.py` | A function above the cyclomatic-complexity budget | tracked allowlist |
| `tests/test_dependency_direction_audit.py` | A layer-violation import (e.g. `routers/` → `services/` is fine; `services/` → `routers/` is not) | tracked allowlist |
| `tests/test_n_plus_one_audit.py` | A loop body containing a DB query (classic N+1 shape) | tracked allowlist |
| `tests/test_concurrency_safety_audit.py` | A shared mutable global without a lock | tracked allowlist |
| `tests/test_sync_open_in_async_audit.py` | A blocking `open(...)` / `requests.get(...)` inside an `async def` body | tracked allowlist |
| `tests/test_shell_injection_audit.py` | An `os.system` / `subprocess.run(..., shell=True)` with interpolated args | tracked allowlist |
| `tests/test_todo_aging_audit.py` | A `# TODO` older than the aging threshold without a ticket reference | tracked allowlist |
| `tests/test_fixture_duplication_audit.py` | The same fixture defined in N test files instead of in `conftest.py` | tracked allowlist |
| `tests/test_dep_parity_audit.py` | A package in `requirements.txt` not in `requirements-dev.txt` (or vice-versa) where it should be | tracked allowlist |
| `tests/test_ci_precommit_drift_audit.py` | A pre-commit hook present in `.pre-commit-config.yaml` but not in CI (or vice-versa) | tracked allowlist |
| `tests/test_audit_index_freshness_audit.py` | The auto-generated `audit-suite.md` is stale relative to the source tests | _(self-pinning)_ |
| `tests/test_frontend_bundle_composition_audit.py` | An unexpected dependency leaking into the frontend bundle | tracked allowlist |

---

## Runbook index

Every runbook below either pairs with one or more audits OR
covers an incident shape that audits help PREVENT.

| Runbook | Pairs with |
| --- | --- |
| [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) | The 5 cross-tenant security audits (admin-session-factory, admin-routes-role-gate, input-schemas, output-schemas, orm-tables, rls-policy-coverage, tenant-predicate, secret-access) |
| [`runbook-rls-policies.md`](runbook-rls-policies.md) | `test_rls_policy_coverage_audit.py` + `test_orm_tables_organization_id_audit.py` |
| [`runbook-migration-rollback.md`](runbook-migration-rollback.md) | `test_alembic_chain_integrity_audit.py` + `test_migration_upgrade_downgrade_symmetry_audit.py` + `test_migration_safety_audit.py` |
| [`runbook-cron-admin.md`](runbook-cron-admin.md) | `test_cron_mutex_audit.py` |
| [`runbook-cron-watchdog.md`](runbook-cron-watchdog.md) | `test_cron_mutex_audit.py` (operational view) |
| [`runbook-webhook-deliveries.md`](runbook-webhook-deliveries.md) | `test_audit_action_callsite_audit.py` (webhook actions) |
| [`runbook-slack-deliveries.md`](runbook-slack-deliveries.md) | (no direct audit pair; pin tests cover it) |
| [`runbook-api-keys.md`](runbook-api-keys.md) | `test_output_schemas_no_secret_fields_audit.py` + `test_secret_access_audit.py` |
| [`runbook-api-keys-unused.md`](runbook-api-keys-unused.md) | (no direct audit pair; lifecycle / cleanup procedure) |

---

## Contribution checklist for new audits

When adding a new `tests/test_X_audit.py`:

1. **Audit file** — under `apps/api/tests/test_X_audit.py`. The
   docstring is the source of truth for `audit-suite.md`'s
   description; write it as if a future on-call engineer is
   reading it 6 months from now.

2. **Allowlist with rationale** — every existing offender gets
   an entry like
   `"<path>": "TODO(<ticket>): <one-line plan>"`. The audit
   ships GREEN with the allowlist absorbing every existing
   instance; the audit catches future REGRESSIONS, not the
   present state.

3. **Three companion tests** in the same file:
   - `test_<bug-shape>_does_not_grow_silently` — the main
     ratchet.
   - `test_audit_finds_at_least_one_<thing>` — sanity floor; if
     the codebase shrinks past the floor, the audit's iteration
     probably broke.
   - `test_<allowlist>_entries_have_rationale` — every allowlist
     value is non-empty and references a ticket / explanation.

4. **Regenerate `audit-suite.md`** — run
   `python -m scripts.generate_audit_index` from `apps/api/`.
   The `test_audit_index_freshness_audit.py` audit fails
   pre-merge if you skip this step.

5. **Add a row to THIS doc** — pick the right category, fill in
   what the audit catches, link the runbook (or note "no runbook
   — code-style"), state the current allowlist size.

6. **Pair with a runbook** if the audit guards an
   ops-relevant invariant. The default is "code-style audits
   don't need a runbook; security / migration / operational
   audits do." When in doubt, a one-paragraph runbook stub is
   better than nothing — it gives ops a place to add procedure
   the first time the audit fires red.

7. **Add to `make audit`** — the make target should pick up
   `tests/test_*_audit.py` automatically. If the new file
   doesn't run, check the glob.

---

## Why this doc exists

The auto-generated [`audit-suite.md`](audit-suite.md) is
exhaustive but flat — every audit at the same level, no
grouping, no runbook context. That's the right shape for "show
me everything pinned" but the wrong shape for "an audit fired in
CI at 3 AM, what do I read."

This doc is the on-call entry point. The categorisation and the
runbook column are deliberate: an on-call engineer with a red
audit name should be able to find the right procedure in under
30 seconds.

If you find yourself reaching for `grep` against
`tests/test_*_audit.py` to figure out what an audit catches,
that's a bug in this doc — please add the missing context.
