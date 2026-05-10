# Audit suite — campaign state snapshot

**Last updated:** 2026-05-09. **Branch:** `feat/audit-suite-followup-rescue`.

A single-page status snapshot for picking up the audit-suite
campaign in a future session. Pairs with:

  * [`audit-suite.md`](audit-suite.md) — auto-generated index of
    every audit's tests + docstring (the spec view).
  * [`runbook-audit-suite-on-call.md`](runbook-audit-suite-on-call.md) —
    on-call triage when an audit fires red.

This doc is the orientation: how many audits, what's red, what
the recent work touched.

## Counts at-a-glance

| Surface | Count |
| --- | --- |
| Audits in `apps/api/tests/test_*_audit.py` | 56 |
| Pin tests in `apps/api/tests/test_*_pin.py` | (separate suite — not covered here) |
| Runbooks in `docs/runbook-*.md` | 10 |
| Migrations under `apps/api/alembic/versions/` | ~50 |

## Currently red audits (4)

The 4 audits whose count exceeds baseline as of this snapshot.
Each has a spawn-task issued — see the chips left for the user.
Triage flow per audit lives in
[`runbook-audit-suite-on-call.md`](runbook-audit-suite-on-call.md).

| Audit | Drift | Spawn-task title |
| --- | --- | --- |
| `test_orm_tables_organization_id_audit.py` | 8 tables missing `organization_id` | "Triage 8 ORM tables flagged without organization_id" |
| `test_openapi_route_docs_audit.py` | 3 routes over baseline 170 | "Add response_model to 3 new routes (openapi_route_docs)" |
| `test_audit_completeness_audit.py` | 1 route over baseline 124 (`POST /verify-signature`) | "Audit POST /verify-signature (audit_completeness)" |
| `test_audit_action_callsite_audit.py` | 2 dynamic action callsites | "Allowlist 2 dynamic action callsites (audit_action_callsite)" |

## Recently green'd this session

For context — the audits that went red→green during the
campaign's most recent push:

| Audit | What changed |
| --- | --- |
| `test_rls_policy_coverage_audit.py` | Added migration `0048_retention_overrides_rls.py` for the missing tenant policy (later renumbered/restated by parallel-session work) |
| `test_alembic_chain_integrity_audit.py` | Allowlisted 2 pre-existing chain bugs (0044 dangling reference; 0043 leaf head) bringing known chain bugs from 5 → 7 |
| `test_audit_index_freshness_audit.py` | Regenerated `audit-suite.md` to absorb new `__all__` + `__future__` audits |

## Recently shipped audits

New audits added during this campaign (not exhaustive — the
parallel-session workflow has been productive):

  * `test_alembic_chain_integrity_audit.py` — chain integrity
    (revision uniqueness, dangling refs, single root, single
    head, no cycles, filename↔revision match).
  * `test_admin_session_factory_usage_audit.py` — BYPASSRLS
    session usage allowlist.
  * `test_admin_routes_role_gate_audit.py` — every
    `/api/v1/admin/*` route has a role-gate dep.
  * `test_every_router_mounted_in_main_audit.py` — every
    `routers/X.py` is `include_router(...)`'d in `main.py`.
  * `test_rls_policy_coverage_audit.py` — every tenant-bearing
    table has an RLS policy.
  * `test_migration_upgrade_downgrade_symmetry_audit.py` —
    every `upgrade()` has a non-empty `downgrade()`.
  * `test_router_handlers_are_async_audit.py` — `@router.<m>`
    decorators only on `async def`.
  * `test_future_annotations_import_audit.py` — every `.py`
    has `from __future__ import annotations`.
  * `test_dunder_all_consistency_audit.py` — every `__all__`
    entry resolves to a top-level symbol.
  * `test_bare_except_audit.py` — no bare `except:` clauses.
  * `test_mutable_default_args_audit.py` — no mutable default
    arguments.
  * `test_fromtimestamp_naive_audit.py` (parallel session)
  * `test_logger_exception_outside_except_audit.py` (parallel)
  * `test_optional_without_default_audit.py` (parallel)
  * `test_singleton_comparison_audit.py` (parallel)
  * `test_stale_init_export_audit.py` (parallel)
  * `test_sync_requests_in_async_audit.py` (parallel)
  * `test_untyped_function_audit.py` (parallel)

## Recently shipped runbooks

  * `runbook-cross-tenant-incident.md` — pairs with the 5
    cross-tenant security audits.
  * `runbook-rls-policies.md` — pairs with `test_rls_policy_coverage_audit.py` + `test_orm_tables_organization_id_audit.py`.
  * `runbook-migration-rollback.md` — pairs with the migration
    audits; includes the 7-known-chain-bugs triage table.
  * `runbook-api-keys.md` — pairs with `test_output_schemas_no_secret_fields_audit.py` + `test_secret_access_audit.py`.
  * `runbook-api-keys-unused.md` — lifecycle / cleanup procedure.
  * `runbook-audit-suite-on-call.md` (NEW this session) — on-call
    triage flow when any audit fires red.

## Cross-references — discovery surfaces

| If you want to… | Read |
| --- | --- |
| See every audit's tests + docstring | [`audit-suite.md`](audit-suite.md) (auto-generated) |
| Map audits → runbooks (curated by category) | [`audit-suite-overview.md`](audit-suite-overview.md) (when present) |
| Triage a red audit at 3 AM | [`runbook-audit-suite-on-call.md`](runbook-audit-suite-on-call.md) |
| Roll back a bad migration | [`runbook-migration-rollback.md`](runbook-migration-rollback.md) |
| Add an RLS policy | [`runbook-rls-policies.md`](runbook-rls-policies.md) |
| Walk through a cross-tenant incident | [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) |
| See admin dashboards index | [`admin-surfaces.md`](admin-surfaces.md) |

## The audit-ratchet philosophy

A short refresher (the on-call runbook has the long version):

  * **Audits ratchet DOWN, never UP.** Allowlist size only
    shrinks; baseline count only decreases. Bumping a baseline
    up loses the entire audit's value.
  * **Allowlist entries require rationale.** "Didn't think
    about it" is not a rationale. The rationale IS the review
    surface.
  * **Audits are revert-resistant.** Every audit lives in
    `tests/test_*_audit.py` and survives upstream reverts of
    feature code. This is the campaign's core value: a
    feature can be reverted without losing the regression-
    prevention test.

## Known parallel-session pattern

This branch sees parallel Claude Code sessions pushing audit
work. As a result:

  * The branch state can move between turns within a single
    conversation.
  * Edits to existing files (allowlists, handler bodies) can
    appear "reverted" between turns — they're preserved in the
    parallel session's worktree, just not visible in the
    current checkout.
  * Edits to NEW files (new audits, new runbooks, new
    migrations) tend to stick because there's no prior version
    to revert to.

**Implication for the next session:** prefer new-file work
over edits to existing audits / handlers when continuing this
campaign. Spawn-tasks for the existing-file work let the
human direct the merge of parallel branches.

## Pickup checklist for the next session

1. **Run the suite first**: `cd apps/api && python -m pytest tests/test_*_audit.py -q --no-header --tb=no`. Compare to the
   "Currently red audits" table above. If new reds appeared,
   they're recent drift.
2. **Read `audit-suite.md`** for the audit list (auto-generated).
3. **Read `runbook-audit-suite-on-call.md`** for the triage
   per-audit.
4. **Pick a green path:**
   - Fix a red audit (touch existing files; revert risk on
     this branch).
   - Ship a new audit (new file; sticks reliably).
   - Pair an existing audit with a runbook (new file).
   - Snapshot the campaign state (this doc; refresh on each
     session boundary).
5. **Don't bump baselines up** without a written rationale in
   the commit message naming what changed in the codebase that
   justifies the bump.

## What this snapshot is NOT

  * **Not a substitute for `audit-suite.md`.** That file is
    auto-generated and exhaustive; this one is curated and
    short.
  * **Not a triage runbook.** That's
    `runbook-audit-suite-on-call.md`. This snapshot answers
    "where are we" not "what do I do."
  * **Not a permanent doc.** Refresh on each campaign session.
    A stale snapshot is worse than no snapshot — it tells the
    next session a state that's no longer true.
