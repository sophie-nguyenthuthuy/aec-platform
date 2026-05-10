# On-call runbooks — index

Single source of truth for "I'm on-call and something's red —
what do I read?". Companion to:

  * [`admin-surfaces.md`](admin-surfaces.md) — index of admin
    dashboards (the `/admin` UI surface).
  * [`audit-suite.md`](audit-suite.md) — auto-generated index
    of every CI audit (the spec view).
  * [`audit-suite-state.md`](audit-suite-state.md) — campaign
    state snapshot for the audit suite.

If a runbook is missing from this index, either:
  * It's been added without updating this doc — please update.
  * It's been retired — please remove the entry.

---

## Triage by symptom

The fastest path: match the page-out symptom to a runbook,
read the "first 15 minutes" section, escalate from there.

| Symptom | Runbook |
| --- | --- |
| Customer reports seeing another tenant's data | [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) |
| Migration deploy broke prod, rollback needed | [`runbook-migration-rollback.md`](runbook-migration-rollback.md) |
| Customer reports duplicate side-effects from one (retried) request | [`runbook-idempotency.md`](runbook-idempotency.md) |
| Customer reports `429`s they think are wrong | [`runbook-rate-limits.md`](runbook-rate-limits.md) |
| API key compromised / leaked / "I think mine got pwned" | [`runbook-api-keys.md`](runbook-api-keys.md) |
| Webhook deliveries failing / partner reports missing events | [`runbook-webhook-deliveries.md`](runbook-webhook-deliveries.md) |
| Slack delivery failure / ops alerts missing | [`runbook-slack-deliveries.md`](runbook-slack-deliveries.md) |
| Cron not firing / firing late | [`runbook-cron-admin.md`](runbook-cron-admin.md) + [`runbook-cron-watchdog.md`](runbook-cron-watchdog.md) |
| Worker task stuck / failing / running away | [`runbook-worker-tasks.md`](runbook-worker-tasks.md) |
| RLS policy isn't filtering / smoke test fails | [`runbook-rls-policies.md`](runbook-rls-policies.md) |
| "Why is this audit row missing?" / audit-log investigation | [`runbook-audit-trail.md`](runbook-audit-trail.md) |
| One of the `tests/test_*_audit.py` tests fired red in CI | [`runbook-audit-suite-on-call.md`](runbook-audit-suite-on-call.md) |
| Old API keys never used → cleanup | [`runbook-api-keys-unused.md`](runbook-api-keys-unused.md) |
| API returns 503 / DB connection pool exhausted / queries timing out | [`runbook-database-incident.md`](runbook-database-incident.md) |
| Postgres replication lag spike / replicas serving stale data | [`runbook-database-incident.md`](runbook-database-incident.md) |
| Redis is up but slow / latency degraded across multiple subsystems | [`runbook-redis-incident.md`](runbook-redis-incident.md) |
| Worker queue depth climbing / cron tick lag | [`runbook-worker-tasks.md`](runbook-worker-tasks.md) + [`runbook-cron-watchdog.md`](runbook-cron-watchdog.md) |
| Service degraded but you don't know which subsystem | Start with [`runbook-database-incident.md`](runbook-database-incident.md) (most cascading-degradations are DB), then [`runbook-redis-incident.md`](runbook-redis-incident.md) |

---

## Triage by surface

The same runbooks, grouped by what they're about — useful
when you don't know the symptom but you know the surface.

### Cross-tenant security

The single highest-stakes incident type. Every minute matters.

| Runbook | Pairs with audit |
| --- | --- |
| [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) | The 5 cross-tenant security audits |
| [`runbook-rls-policies.md`](runbook-rls-policies.md) | `test_rls_policy_coverage_audit.py` + `test_orm_tables_organization_id_audit.py` |
| [`runbook-api-keys.md`](runbook-api-keys.md) | `test_secret_access_audit.py` + `test_output_schemas_no_secret_fields_audit.py` |

### Schema / migration health

| Runbook | Pairs with audit |
| --- | --- |
| [`runbook-migration-rollback.md`](runbook-migration-rollback.md) | `test_alembic_chain_integrity_audit.py` + `test_migration_upgrade_downgrade_symmetry_audit.py` + `test_migration_safety_audit.py` |
| [`runbook-rls-policies.md`](runbook-rls-policies.md) | (covers RLS in migrations) |

### API surface (HTTP)

| Runbook | Pairs with audit |
| --- | --- |
| [`runbook-rate-limits.md`](runbook-rate-limits.md) | `test_rate_limit_audit.py` |
| [`runbook-idempotency.md`](runbook-idempotency.md) | `test_idempotency_contract_audit.py` |
| [`runbook-api-keys.md`](runbook-api-keys.md) | (auth surface) |

### Async / worker surface

| Runbook | Pairs with audit |
| --- | --- |
| [`runbook-worker-tasks.md`](runbook-worker-tasks.md) | `test_worker_retry_policy_audit.py` |
| [`runbook-cron-admin.md`](runbook-cron-admin.md) | `test_cron_mutex_audit.py` (operational view) |
| [`runbook-cron-watchdog.md`](runbook-cron-watchdog.md) | (alert-driven view) |

### Outbound integrations

| Runbook | Surface |
| --- | --- |
| [`runbook-webhook-deliveries.md`](runbook-webhook-deliveries.md) | Outbound HTTP deliveries to partner receivers |
| [`runbook-slack-deliveries.md`](runbook-slack-deliveries.md) | Platform Slack alerts (ops, not per-tenant) |

### Observability / forensics

| Runbook | Surface |
| --- | --- |
| [`runbook-audit-trail.md`](runbook-audit-trail.md) | Querying `audit_events` during an investigation |
| [`runbook-audit-suite-on-call.md`](runbook-audit-suite-on-call.md) | Triage when CI audits fire red |

### Lifecycle / cleanup

| Runbook | Surface |
| --- | --- |
| [`runbook-api-keys-unused.md`](runbook-api-keys-unused.md) | Deprecating old keys; reducing exposure surface |

---

## The two index docs

| Doc | Purpose |
| --- | --- |
| [`admin-surfaces.md`](admin-surfaces.md) | Index of `/admin` dashboards — what surfaces exist + their pin tests |
| [`audit-suite.md`](audit-suite.md) | Auto-generated index of every CI audit — spec view |
| [`audit-suite-overview.md`](audit-suite-overview.md) | Curated audit-to-runbook map (when present) |
| `on-call-runbooks-index.md` (this) | Index of operational runbooks — symptom-driven |

The four together cover the discovery surfaces an on-call
engineer needs: what dashboards exist, what audits exist, what
runbooks exist, and how they map to each other.

---

## Contribution checklist for new runbooks

When adding a `docs/runbook-<topic>.md`:

1. **Match the existing shape.** Header section explaining
   what the runbook is for; "First 15 minutes" or
   "Triage flow" section; per-case sub-sections with concrete
   steps; "Common mistakes" section; "Related code + audits"
   table; "What this runbook is NOT for" closer.

2. **Pair with an audit if applicable.** Most runbooks pair
   with one or more `tests/test_*_audit.py` files. Naming the
   pairing in the runbook's intro AND in this index makes the
   discovery loop tight.

3. **Add a row to BOTH triage tables above.** The "by symptom"
   table is the on-call entry point; the "by surface" table
   is the orientation view.

4. **Cross-link in related runbooks.** If your new runbook
   touches subjects the existing runbooks already cover, add a
   "Related code + audits + runbooks" row to those existing
   runbooks pointing back to yours.

5. **No "TBD" sections.** A runbook with `TODO: fill in` is
   worse than no runbook — on-call reads it, finds the gap
   mid-incident, can't act. Either ship complete or don't ship.

---

## What this index is NOT for

  * **A general docs index.** That's [`README.md`](README.md).
    This file is operational only.
  * **Architecture / module deep-dives.** Those live as
    standalone files in `docs/` — see [`README.md`](README.md)
    for the per-module index.
  * **An on-call rotation schedule.** Out of scope. Schedules
    live in PagerDuty / OpsGenie.
