# Runbook: database (Postgres) incident

The on-call procedure when Postgres is degraded — slow queries,
connection exhaustion, replication lag, out-of-disk, or a query
that's taking down the box. Pairs with:

  * [`runbook-migration-rollback.md`](runbook-migration-rollback.md) —
    rolling back a bad alembic migration (different incident
    shape; this runbook is for runtime issues, not schema
    changes).
  * [`runbook-rls-policies.md`](runbook-rls-policies.md) —
    when RLS itself is the problem (rare; this runbook covers
    the broader cases).
  * [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) —
    cross-tenant exposure is its own runbook; if a DB issue
    caused exposure, escalate there first.

## What "DB incident" looks like

| Symptom | Likely cause |
| --- | --- |
| Every API request times out | Connection pool exhausted, OR primary unreachable |
| Most requests slow but some fast | One slow query is hogging connections / locks |
| Specific tenant slow, others fine | Tenant-bearing query missing an index, OR RLS evaluation slow |
| Replicas stale | Replication lag spike (long-running write transaction) |
| `OUT OF DISK` errors | WAL / temp / archive disk full |
| `too many connections` errors | Pool tuning vs Postgres `max_connections` mismatch |

## First 5 minutes — connection vs query

The two highest-leverage diagnoses upfront.

### 1. Is it the connection pool?

```sql
-- How many connections does Postgres see?
SELECT count(*), state, wait_event_type, wait_event
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY state, wait_event_type, wait_event
ORDER BY count(*) DESC;
```

Read the rows:

  * `state = 'active'` rows are running queries. If the count is
    near `max_connections`, the pool is at capacity AND queries
    are slow → cascading congestion.
  * `state = 'idle in transaction'` rows are connections holding
    transactions open WITHOUT actively running. These are usually
    a bug — a handler started a transaction, then went off to do
    something slow (S3 call, external HTTP) without committing.
  * `wait_event_type = 'Lock'` → row-level or relation-level lock
    contention. See "Lock contention" below.

### 2. Is it a single bad query?

```sql
-- Top 10 longest-running queries right now.
SELECT pid, age(clock_timestamp(), query_start) AS duration,
       state, wait_event, query
FROM pg_stat_activity
WHERE datname = current_database()
  AND state != 'idle'
ORDER BY query_start ASC
LIMIT 10;
```

If one query is hours-long, it's blocking. Decide:

  * **Cancel it**: `SELECT pg_cancel_backend(<pid>)` — graceful;
    the query receives a signal and unwinds.
  * **Terminate it**: `SELECT pg_terminate_backend(<pid>)` —
    forceful; closes the connection. Use if cancel doesn't take.

After cancel/terminate, investigate WHY the query was slow. The
query text from `pg_stat_activity` plus `EXPLAIN ANALYZE` (with
representative parameters) usually reveals it.

## Connection pool exhaustion

Symptom: every API request returns 503 / connection-timeout.
`pg_stat_activity` shows `count(*)` close to `max_connections`.

### Diagnosis (pool exhaustion)

```sql
-- Who's holding connections, and what state are they in?
SELECT application_name, state, count(*)
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY application_name, state
ORDER BY count(*) DESC;
```

Common shapes:

  * **Workers + API both at capacity** — the pool tunings are
    fighting. Each layer should have its own pool with bounded
    size; total across all layers must fit
    `max_connections - reserved_connections`.
  * **One `application_name` dominating** — that pool is leaking
    or has stuck connections. Restart the affected service if
    the leak is in flight.
  * **`idle in transaction` is high** — a handler isn't
    committing/rolling back. Look at the `query` column for the
    last statement they ran.

### Recovery (pool exhaustion)

  1. Cancel idle-in-transaction connections older than 30s:
     ```sql
     SELECT pg_cancel_backend(pid)
     FROM pg_stat_activity
     WHERE state = 'idle in transaction'
       AND age(clock_timestamp(), state_change) > interval '30 seconds';
     ```
  2. If the leak is from a specific service, restart it.
  3. Document the leak shape; file a follow-up to fix the
     handler that doesn't commit.

### Prevention

  * `idle_in_transaction_session_timeout` set on the role —
    Postgres force-closes after the timeout. Default in this
    codebase: see `core/config.py` for the value.
  * Pool tunings: `aec_app` (NOBYPASSRLS) gets the biggest pool;
    `aec` (BYPASSRLS) is admin-tooling only and should have a
    small pool.

## Lock contention

Symptom: queries slow, `wait_event_type = 'Lock'` on multiple
rows in `pg_stat_activity`.

### Diagnosis (lock contention)

```sql
-- Who's holding the locks the waiters want?
SELECT
  blocked_locks.pid AS blocked_pid,
  blocked_activity.usename AS blocked_user,
  blocking_locks.pid AS blocking_pid,
  blocking_activity.usename AS blocking_user,
  blocked_activity.query AS blocked_statement,
  blocking_activity.query AS current_statement_in_blocking_process
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity
  ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks
  ON blocking_locks.locktype = blocked_locks.locktype
  AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
  AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
  AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
  AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
  AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
  AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
  AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
  AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
  AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
  AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity
  ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

The `blocking_pid` is what to investigate. The
`current_statement_in_blocking_process` shows what it's doing.

Common cases:

  * **Long-running migration with `ACCESS EXCLUSIVE` lock**.
    The fix: schedule schema-changing migrations during low-
    traffic windows; use `lock_timeout` on the session.
  * **Bulk update with no batching**.
    `UPDATE ... WHERE org_id = X` on a 10M-row table holds row
    locks for the duration. Refactor to batched updates.
  * **`SELECT FOR UPDATE` from a hung handler**.
    Same root cause as idle-in-transaction; a handler took a
    row lock then went off to do something slow.

### Recovery (lock contention)

Same as connection pool: cancel/terminate the blocking PID;
investigate WHY it was slow.

## Replication lag

Symptom: read-replica returns stale data; lag metric spikes.

### Diagnosis (replication lag)

```sql
-- On the primary:
SELECT client_addr, application_name, state,
       pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS sent_lag,
       pg_wal_lsn_diff(pg_current_wal_lsn(), write_lsn) AS write_lag,
       pg_wal_lsn_diff(pg_current_wal_lsn(), flush_lsn) AS flush_lag,
       pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag
FROM pg_stat_replication;
```

Lag values are bytes of WAL behind. If `replay_lag` is large +
growing, the replica can't keep up.

Causes:

  * **Long-running transaction on the primary** — replicas can't
    apply WAL past it without breaking serialisability.
  * **Replica is CPU-bound** — usually because of read traffic;
    move some reads back to primary or scale up.
  * **Replica is disk-bound** — the storage couldn't apply WAL
    fast enough.

### Recovery (replication lag)

  * Cancel / terminate the long-running primary transaction.
  * If application is replica-aware (some reads go to replica),
    consider routing those reads back to primary while lag
    recovers — accept the primary load increase as a tradeoff.

## Out of disk

Symptom: `ERROR: could not extend file ...: No space left on
device`. Writes start failing; reads may still work.

### Causes

  * **WAL backed up** — `pg_wal/` filling because replication is
    broken or the WAL retention setting is too aggressive.
    Diagnose: `du -sh /var/lib/postgresql/.../pg_wal/` (or where
    the WAL lives in your deploy).
  * **Temp files** — a query is spilling to disk because of
    insufficient `work_mem`. `du -sh /tmp/`.
  * **Logs filling** — `log_destination = 'csvlog'` plus a busy
    box plus no log rotation = disk full from logs.
  * **Genuine data growth** — unusual; the storage layer
    should be alerting on capacity well before this.

### Recovery (disk full)

In order of preference:

  1. **Fix the root cause** (broken replication, oversized
     query, log rotation) — frees space cleanly.
  2. **Truncate logs** — `truncate -s 0
     /var/lib/postgresql/.../log/*.csv` — fast, safe.
  3. **Drop a non-critical index** to free space (only as a
     last resort; the index needs rebuilding when space
     returns).
  4. **Add storage** — slowest path; takes minutes to hours
     depending on the deploy.

NEVER `rm -rf /var/lib/postgresql/.../pg_wal/` to free space.
That destroys the database's recovery point.

## Slow query — diagnose-and-fix

A handler is slow but DB is otherwise healthy. Step-by-step:

  1. Find the slow query. Logs (`SLOW_QUERY_MS` env var triggers
     a structured log entry — see `core/observability.py`).
     Or look at the API's request-id in `pg_stat_activity` if
     the request is still mid-flight.

  2. Run `EXPLAIN (ANALYZE, BUFFERS)` against the query with
     representative parameters. The plan tells you what's
     happening:
     - **Sequential scan on a large table** — missing index on
       the WHERE column.
     - **Slow index scan** — the index is bloated; `REINDEX
       CONCURRENTLY` may help.
     - **`Filter: (... )` with high "Rows Removed by Filter"** —
       the query is reading rows it doesn't need; a more-
       specific index would help.
     - **Nested loop with high cost** — bad join order; check
       statistics with `ANALYZE`.

  3. Add the missing index in a follow-up alembic migration.
     Use `op.create_index(... postgresql_concurrently=True)` so
     the migration doesn't lock the table — see
     `runbook-rls-policies.md`'s migration patterns for the shape.

  4. The `test_fk_index_coverage_audit.py` audit catches FK
     columns without indexes; if a query was slow due to a
     missing FK index AND the audit was passing, the audit's
     scope may need to widen.

## Common mistakes

### Treating "slow query" as "DB is broken"

Postgres is rarely "broken." A slow query is almost always a
missing index, a query plan that needs `ANALYZE`, or genuine
data growth that needs schema-level work (partitioning,
archiving). Don't restart the DB; profile the query.

### Restarting Postgres to "free connections"

The connection leak isn't IN Postgres; it's in the application
holding connections. Restarting Postgres resets every
connection but the leak resumes the second the application
reconnects. Fix the leak in the app layer.

### Cancelling autovacuum during an incident

Autovacuum runs in the background to keep tables / indexes
healthy. Killing it during an incident postpones bloat issues
to the next incident. Let it run.

### Reading from the primary "to be safe"

A replica-routing scheme that falls back to primary when
replicas are slow is a foot-gun: a replica problem becomes a
primary-overload problem. Build the scheme so replicas are
explicitly required for read paths; failures surface as 503,
not as silent primary load.

### Using `pg_terminate_backend` on a writer

If the terminated PID was mid-transaction, the rollback is
clean — Postgres handles it. But if it was holding row locks
against a hot table, EVERY waiter will retry, and the
contention storm shifts to the new connections. Cancel
gracefully first.

## When to wake the team

  * Connection pool > 80% utilised for >5 min → wake on-call
    DBA or senior engineer.
  * Replication lag > 30s sustained → wake on-call DBA.
  * Disk > 90% full → page infra immediately.
  * Any cross-tenant exposure suspected →
    [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md)
    and wake security lead.

## Related code + audits + runbooks

| Surface | Lives in |
| --- | --- |
| DB factories | `apps/api/db/session.py` |
| Pool tuning | `apps/api/core/config.py` (look for `DB_POOL_SIZE`) |
| Slow-query log | `core/observability.py` (env: `SLOW_QUERY_MS`) |
| Migration health | [`runbook-migration-rollback.md`](runbook-migration-rollback.md) |
| RLS layer | [`runbook-rls-policies.md`](runbook-rls-policies.md) |
| Cross-tenant exposure | [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) |
| FK index coverage audit | `tests/test_fk_index_coverage_audit.py` |
| Migration safety audit | `tests/test_migration_safety_audit.py` |

## What this runbook is NOT for

  * **A bad alembic migration.** That's
    [`runbook-migration-rollback.md`](runbook-migration-rollback.md).
    This runbook is for runtime DB issues unrelated to the
    schema-change history.
  * **A Redis incident.** That's
    [`runbook-redis-incident.md`](runbook-redis-incident.md).
  * **Adding a new index because a query is slow.** That's a
    follow-up PR, not an incident. Use this runbook to triage
    THE INCIDENT; ship the index fix in normal flow.
  * **Deploying a new Postgres major version.** Major-version
    upgrades have their own playbook; ask infra.
