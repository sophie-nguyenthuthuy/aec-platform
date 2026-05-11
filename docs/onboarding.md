# Engineer onboarding

You're new to the codebase. This is the orientation surface —
what to read, in what order, to come up to speed without
boiling the ocean.

The codebase has lots of docs. Most don't matter for the first
week; this guide tells you which ones do.

## Day 1 — orient

Read these, in this order. ~90 min total.

1. **[`README.md`](README.md)** (5 min) — the platform's
   entry point. Cross-module conventions you'll see referenced
   everywhere.

2. **[`architecture.md`](architecture.md)** (30 min) — the
   shape: which apps live where, the DB factories, the
   request lifecycle, the worker model. Keep this open on a
   second monitor for your first week.

3. **[`testing.md`](testing.md)** (15 min) — how the test
   suite is organised. The audit suite vs pin tests vs
   integration tests distinction matters; you'll touch all
   three.

4. **[`admin-surfaces.md`](admin-surfaces.md)** (15 min) —
   index of `/admin` dashboards. You won't BUILD one on day 1
   but knowing they exist + the contribution checklist saves
   "where do I put this" questions later.

5. **[`on-call-runbooks-index.md`](on-call-runbooks-index.md)**
   (15 min) — operational runbooks indexed by symptom. Read
   the symptom table; you don't need to read the runbooks
   themselves until the symptom fires.

## Day 2 — the audit suite

The codebase uses a "ratchet audit" pattern extensively (~50+
audits in `apps/api/tests/test_*_audit.py`). Understanding the
pattern matters because:

- Most PRs trigger one or more audits.
- A failing audit is the platform's primary regression-
  prevention surface.
- The allowlist-with-rationale convention is everywhere.

Read these, in this order. ~30 min.

1. **[`audit-suite.md`](audit-suite.md)** — auto-generated
   index of every audit. Spec view: every audit's docstring
   + tests. Skim, don't memorise; come back when you write
   your first audit.

2. **[`audit-suite-overview.md`](audit-suite-overview.md)** (if
   present) — curated audit-to-runbook map.

3. **[`runbook-audit-suite-on-call.md`](runbook-audit-suite-on-call.md)**
   — what to do when an audit fires red in CI. Triage flow
   per audit; the philosophy section on "ratchet only goes
   DOWN" is core.

4. **A representative audit's source** — pick any
   `tests/test_*_audit.py` and read it. Recommend
   `tests/test_admin_routes_role_gate_audit.py` for the
   FastAPI-introspection pattern OR
   `tests/test_alembic_chain_integrity_audit.py` for the
   AST-walk pattern. Audits are well-commented; learning the
   shape from one example transfers.

## Day 3 — the runbook landscape

The platform has 15+ runbooks for operational scenarios. You
won't read them all; you read the ones for surfaces you're
about to touch.

Use the **symptom table** in
[`on-call-runbooks-index.md`](on-call-runbooks-index.md) as
the entry point. When a customer report or alert names a
symptom, the table maps it to the runbook.

The high-stakes runbooks every engineer should at least skim
(15 min total):

- [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md)
  — the worst incident type. The audits exist to prevent it;
  this runbook covers the response.
- [`runbook-rls-policies.md`](runbook-rls-policies.md) — the
  RLS layer is the platform's defense-in-depth against
  cross-tenant leaks. Convention here matters when you add a
  new tenant-bearing table.
- [`runbook-migration-rollback.md`](runbook-migration-rollback.md)
  — how to roll back a bad migration. Includes the table of
  known chain bugs (a few legacy migrations have unfixed
  issues; the runbook tells you not to roll back through
  them).

## Week 1 — the modules you'll touch

The platform has multiple verticals, each with its own deep-
dive doc. Read the one(s) for the module you're about to
work in:

| Vertical | Doc |
| --- | --- |
| Codeguard (compliance assistant) | [`codeguard.md`](codeguard.md) + [`codeguard-quotas.md`](codeguard-quotas.md) + [`codeguard-telemetry.md`](codeguard-telemetry.md) |
| CostPulse (BOQ I/O) | [`costpulse-boq-io.md`](costpulse-boq-io.md) |
| Public RFQ portal | [`public-rfq-portal.md`](public-rfq-portal.md) |
| Scraper drift | [`scraper-drift-monitoring.md`](scraper-drift-monitoring.md) |
| ML coverage | [`ml-coverage-audit.md`](ml-coverage-audit.md) |

Each is ~15-30 min. They assume you've read `architecture.md`
already.

## When you write your first PR

A few conventions that aren't enforced anywhere but make the
review faster:

### Touch one surface at a time

A PR that adds a route AND changes the DB schema AND tweaks
the frontend AND adds a runbook is hard to review. Split it.
Each surface has its own audits + pin tests + reviewers.

### Read the failure message before "fixing" the test

The audits print 2-3 resolution paths in their failure
messages. Reading them saves time vs guessing. The audit's
docstring carries the WHY.

### Add to the allowlist with rationale, not a bare entry

The audit allowlists are dicts of `key → rationale`. Adding
a key with `""` as the value silences the gate without a
review surface. PR review will (and should) reject this.

### Test the rollback before merging

Migrations: `alembic upgrade head; alembic downgrade -1;
alembic upgrade head` — the schema should be byte-identical
at the end. The
`test_migration_upgrade_downgrade_symmetry_audit.py` audit
catches some of this in CI but isn't a substitute for the
roundtrip test.

## When something goes wrong

The triage tree:

```
Something broke
       │
       ▼
   ┌───┴───────────────┐
   │ Customer-facing?  │
   └───┬─────────┬─────┘
       │         │
      yes        no (CI / build / pre-merge)
       │         │
       ▼         ▼
on-call-runbooks-index.md      runbook-audit-suite-on-call.md
       │         │
       └────┬────┘
            ▼
   Match the symptom →
   read that runbook's
   first 15 min section.
```

If the symptom doesn't match any runbook entry, **that's a
docs gap to file as a follow-up.** The runbook landscape is
the on-call surface; an unindexed symptom undermines the
whole discovery loop.

## Don't read

These docs exist for a reason but you don't need them on
day 1 / week 1:

- **[`audit-suite-state.md`](audit-suite-state.md)** — campaign
  state snapshot. Useful for the engineer continuing the
  audit-suite work, not for general onboarding.
- **[`ci-dry-run-findings.md`](ci-dry-run-findings.md)** —
  historical artefact; reference only when investigating
  specific past CI runs.
- **The full runbook set** — symptom-driven; read on demand.
- **The audit source files** — read one example to understand
  the shape, then come back when you write your own.

## Glossary — terms you'll see

| Term | Meaning |
| --- | --- |
| **Ratchet audit** | A test that walks the codebase, counts a bug-shape, and asserts the count hasn't grown beyond a pinned baseline. The campaign produced ~50+ of these. |
| **Allowlist** | A dict of `(file:line / table_name / route_path) → rationale` listing known-existing offenders an audit tolerates. New entries require PR review of the rationale. |
| **Pin test** | A test that asserts a specific surface's contract (route shape, schema fields, function signature) hasn't drifted. Different from an audit; covers one surface vs walking the codebase. |
| **BYPASSRLS / RLS-scoped** | Database-role distinction. `aec_app` (NOBYPASSRLS) is the default request-handler role; `aec` (BYPASSRLS) is admin-tooling only. Mixing them up is a cross-tenant exposure footgun. |
| **`audit_events`** | The append-only governance log. NOT the audit-suite (CI ratchet tests); they're different concepts that share a name unfortunately. See [`runbook-audit-trail.md`](runbook-audit-trail.md). |
| **`organization_id`** | The canonical tenant column. Every tenant-bearing table has this column + an RLS policy filtering on it. |
| **`/admin/*`** | Admin-role-gated routes. The role gate is enforced by `require_role("admin")` deps; the audit `test_admin_routes_role_gate_audit.py` enforces every admin route has the gate. |

## Want to contribute to the docs themselves?

The docs are the platform's institutional memory. If something
was unclear on your first read, it'll be unclear for the next
new engineer too. Three contribution paths:

1. **Fix the doc inline** — typo, broken link, stale section.
   Direct edit + PR.
2. **Add a missing doc** — see the contribution checklist in
   [`on-call-runbooks-index.md`](on-call-runbooks-index.md)
   for runbooks, in [`admin-surfaces.md`](admin-surfaces.md)
   for admin-dashboard docs.
3. **Add to this onboarding doc** — if you found yourself
   wishing the on-the-job orientation was clearer, that's
   information for the next new engineer.

## What this onboarding is NOT for

  * **A "tutorial".** It's a reading order, not a walkthrough.
  * **A platform user-facing manual.** That's the `/docs/api`
    + `/docs/webhooks` + similar customer-facing surfaces.
  * **A deployment runbook.** That's the operations team's
    domain; ask in the engineering channel for access.
