# Runbook: worker tasks (arq queue)

The on-call procedure when a worker task is failing, stuck, or
running away. Pairs with:

  * `tests/test_worker_retry_policy_audit.py` — every worker
    task declares an explicit retry budget.
  * `apps/api/workers/queue.py::WorkerSettings` — the arq
    queue config + cron schedule.
  * `runbook-cron-admin.md` and `runbook-cron-watchdog.md` —
    the cron-specific operational surfaces.

## What runs in workers

Three flavours of workload share the worker pool:

1. **Cron-scheduled tasks** — daily reports, retention
   sweeps, scraper runs. Defined in
   `WorkerSettings.cron_jobs`.

2. **Enqueued tasks** — webhook deliveries, async exports,
   anything spun off from a route handler. Enqueued via
   `pool.enqueue_job(...)`.

3. **Re-enqueued retries** — tasks the worker retries on
   transient failure (configurable per-task retry budget).

The worker is `arq`-based. Concurrency, retry policy, and
telemetry hooks all live in `WorkerSettings`.

## When a task is failing

### 1. Find the failing job

The arq queue keeps results for finished jobs. Inspect:

```bash
# In the worker pool's Redis (typically separate from the API's
# rate-limit Redis):
redis-cli --tls -h <host> -p <port> -a <pw>
> KEYS arq:result:*
> GET arq:result:<job_id>
```

The result blob contains `success`, `result_or_error`, the args
the job ran with, and timing.

For cron jobs specifically, every invocation also writes a
`cron_runs` row — check `/admin/crons/[name]` for the timeline
view.

### 2. Decide: code bug vs operational issue

Code bug — exception traceback in the result. Look at the
traceback; fix the bug; deploy. The job will retry on the next
arq cycle (if retry budget remains) or wait for the next cron
tick.

Operational issue — typical shapes:

  * **Downstream HTTP returned 5xx for the job's window.**
    Webhook deliveries are the most common. Look at whether
    the customer's receiver was up; cross-reference with the
    `webhook_deliveries` table.
  * **DB connection exhaustion.** The worker pool's DB
    connections are separate from the API's. If the API is
    busy, the worker may be queued waiting for a connection.
  * **Redis flake.** Idempotency / activity-stream Redis. The
    arq worker itself uses a different Redis; arq still
    schedules but the task body may fail.

### 3. If retry budget exhausted

The audit `test_worker_retry_policy_audit.py` enforces every
task declare an explicit retry budget. Default is 5 retries
with exponential backoff. After exhaustion:

  * **Webhook delivery** — the delivery row is marked
    `failed`; partner is responsible for re-fetching the event.
    See `runbook-webhook-deliveries.md`.
  * **Cron job** — the next cron tick re-enqueues; the
    operator can also manually re-enqueue from
    `/admin/crons/[name]` (button).
  * **Generic enqueued job** — the row in arq's result store
    has `success=false`. Manual re-enqueue is required.

## When a task is stuck (running too long)

Arq tasks have a configurable timeout. Default is 5 minutes;
specific tasks can override (long-running export jobs may
have 1h).

If a task exceeds its timeout, arq cancels it. The job's result
records the timeout error. Diagnosis:

  * **Long-running by design** — bump the per-task timeout.
    Document why; don't bump globally.
  * **Stuck on a network call** — the call has no inner
    timeout. Add one (5s for HTTP, 30s for DB queries).
  * **Stuck on a lock** — see "Cron mutex" below.

## When the worker pool is overloaded

Symptoms:

  * Queue depth growing (arq exposes a queue-length metric).
  * Cron tick lag (a cron scheduled at :00 doesn't fire until
    :02).

Causes:

  * **Genuine spike** — partner just imported 10k items;
    every import row enqueued a side-effect job. The pool
    backlog clears when the spike ends.
  * **Slow individual tasks** — one task type is taking 30s
    each, blocking the pool. Identify via job-result timing
    histogram; tune that task.
  * **Pool too small** — the worker count is configured per
    deploy. If genuine sustained load > pool capacity, scale
    up.

The `runbook-cron-watchdog.md` covers the alert when cron tick
lag exceeds the threshold.

## When two cron runs collide (mutex)

Some crons MUST NOT run concurrently — if a daily-report cron
fires twice (because the pool restarted mid-run and the job
didn't finish), the customer gets two reports.

The `@with_cron_mutex` decorator (see `services.cron_mutex`)
takes a Redis lock on the cron's name; only one holder runs
the body. The `test_cron_mutex_audit.py` audit pins which
crons require the mutex.

If a cron is silently skipping (the lock is held but the prior
holder died without releasing):

  ```bash
  # Find the lock key and its TTL
  redis-cli KEYS "cron_mutex:*"
  redis-cli TTL "cron_mutex:<cron_name>"
  ```

  * `TTL > 0`: lock will expire on its own; wait or
    `redis-cli DEL <key>` to release immediately.
  * `TTL = -1` (no expiration): bug in the mutex acquisition;
    DELETE the key and file a follow-up.

## When a cron is firing late or not at all

`/admin/crons/[name]` shows the per-cron run history. If runs
are sparse / missing:

  1. **Check the cron's schedule** — defined in
     `WorkerSettings.cron_jobs`. A misconfigured schedule
     (too-strict cron expression) may match no times.
  2. **Check the worker's clock** — drift between the
     scheduler and Redis can produce missed ticks. Less common
     in containerised deploys (NTP is usually reliable).
  3. **Check the watchdog runbook** —
     `runbook-cron-watchdog.md` covers the alert + the
     deeper triage.

## When the retry-policy audit fires red

`test_worker_retry_policy_audit.py` catches a worker task
without an explicit retry budget. Triage:

1. **Identify the task.** Failure message names the file.
2. **Add the retry config.** Convention:
   ```python
   @arq_task(max_tries=5, keep_result=86400)
   async def my_task(ctx, ...):
       ...
   ```
   The exact decorator name + kwargs depend on the codebase's
   convention; look at any sister task for the shape.
3. **If the task is genuinely fire-and-forget** (no retry
   needed; e.g. metric emission) → `max_tries=1` IS the
   explicit budget. Keep it explicit.

## When a task writes to the audit log

Worker tasks that mutate state should still write to
`audit_events` — the actor is `actor_kind = 'system'` or
`'cron'`. The `test_audit_completeness_audit.py` audit covers
HTTP routes; worker tasks aren't enforced by it but are still
expected to audit per-convention.

See [`runbook-audit-trail.md`](runbook-audit-trail.md) for
the writer's signature + convention.

## Common mistakes

### Catching exceptions and swallowing them

A worker task that does `try: ... except Exception: pass`
breaks the retry budget — arq sees the task succeeded and
doesn't retry. The job appears "done" but the side-effect
failed.

The `test_bare_except_audit.py` and the broader exception-
handling audits catch the bare-except case; the broader-
Exception case is harder to detect. Convention: let
exceptions propagate to arq; arq decides whether to retry.

### Spawning subprocesses without timeouts

`subprocess.run(..., timeout=None)` inside a worker task can
hang the entire worker. Always set an explicit timeout.

### Enqueuing from inside a transaction

`pool.enqueue_job(...)` inside an open DB transaction means
the job CAN START before the transaction commits — the worker
reads stale data. Move the `enqueue_job` AFTER `db.commit()`.

### Re-enqueuing manually after a transient failure

The arq retry budget covers transient failures. Manual
re-enqueue should ONLY happen after the budget is exhausted.
Re-enqueuing during the retry window means the job runs N+1
times.

## Related code + audits + runbooks

| Surface | Lives in |
| --- | --- |
| Worker pool config | `apps/api/workers/queue.py::WorkerSettings` |
| Cron mutex | `apps/api/services/cron_mutex.py` |
| Retry-policy audit | `tests/test_worker_retry_policy_audit.py` |
| Cron-mutex audit | `tests/test_cron_mutex_audit.py` |
| Cron admin surface | [`runbook-cron-admin.md`](runbook-cron-admin.md) |
| Cron watchdog | [`runbook-cron-watchdog.md`](runbook-cron-watchdog.md) |
| Webhook delivery worker | [`runbook-webhook-deliveries.md`](runbook-webhook-deliveries.md) |

## What this runbook is NOT for

  * **A web-handler latency issue.** Different surface; the
    worker is async-from-HTTP.
  * **A scheduled task that should be a route.** Some "tasks"
    are logically synchronous and shouldn't be enqueued at
    all. That's a design call; not on-call's plate.
  * **Adding a new task.** The retry-policy audit fires in CI
    if the new task lacks budget. This runbook is for in-prod
    incidents.
