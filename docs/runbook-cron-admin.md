# Runbook: `/admin/crons` dashboard

## What this is

Every background job (drift scrapes, weekly reports, webhook drain,
RFQ slot expiry, retention prune) is registered as an arq cron in
`apps/api/workers/queue.py::WorkerSettings.cron_jobs`. The cron
schedules live in code, but ops needs a way to verify what's actually
registered on a deployed worker — "did my new cron entry ship?",
"why hasn't the weekly report fired in three weeks?", "what's about
to fire next?".

The `/admin/crons` page reads `WorkerSettings.cron_jobs` in-process
on the API container and renders one row per registered cron with
schedule + next-due timestamp + first-line docstring.

## How to read the dashboard

| Column        | What it tells you                                               |
| ------------- | --------------------------------------------------------------- |
| `function`    | The coroutine's `__name__` — search this in worker logs        |
| `module`      | Where the cron lives (e.g. `workers.queue`)                    |
| `schedule`    | Human-readable form ("Mondays at 06:00 UTC", "Every minute")    |
| `next run`    | Computed via arq's `calculate_next` — when this cron next fires |
| `description` | First line of the cron function's docstring (160-char cap)      |

The list is sorted by **next run ASC NULLS LAST** so the cron about
to fire is at the top. A cron with `next_run = "—"` means arq's
`calculate_next` raised — typically a malformed schedule spec.

## What this dashboard *isn't* useful for (v1 caveat)

- **Last-run history.** arq stores `JobResult` records in Redis with
  a 1-hour TTL by default; a persistent `cron_runs` table would let
  the page answer "did the cron actually run on time?" but is
  follow-up work. **Today, "the cron is registered" ≠ "the cron is
  firing."**
- **Health rollup.** Without last-run telemetry, "healthy" can't be
  derived; the page is the registry, not a status board.
- **Manual fire button.** Triggering a cron from the UI would need
  a cross-tenant queue-enqueue path with audit logging; out of v1
  scope. Manual fires today happen via the worker shell:
  ```bash
  pnpm --filter @aec/api exec python -c "import asyncio; from workers.queue import weekly_report_cron; asyncio.run(weekly_report_cron({}))"
  ```

## When the dashboard shows something unexpected

### A cron you expected to see is missing

1. **Confirm it's deployed.** `git log apps/api/workers/queue.py` —
   was the entry merged + deployed? The page reads in-process, so
   a fresh deploy is required for new entries to appear.

2. **Check `register_all()` in `models/__init__.py`.** Some crons
   import models that aren't registered yet; if SQLAlchemy can't
   resolve a FK at module load, the worker crashes BEFORE
   registering its crons. Look for `NoReferencedTableError` in
   worker logs.

3. **Check the worker booted at all.** `kubectl logs -l app=worker`
   (or whatever the deploy target is). A boot failure stops cron
   registration entirely — the page would be EMPTY rather than
   missing one entry.

### Next-run shows "—" for a cron

`_next_run_iso` returns None when arq's `calculate_next` raises.
Causes:
- Schedule spec uses an unsupported pattern (e.g. unpredictable
  combinations of `weekday=`, `day=`, `month=`).
- `WorkerSettings.cron_jobs` was constructed with stale arq
  internals between version bumps.

The page renders "—" rather than 500ing because one bad entry
shouldn't take down the whole list (defended in the pin file
`tests/test_cron_admin_surface_pin.py`).

To investigate: look at the cron's source declaration and try
calling `calculate_next(datetime.now(UTC))` in a Python shell. The
exception is what's getting swallowed.

### Next-run is in the past

A cron whose next_run is older than now means:
- The worker is dead / hasn't picked up the schedule. Check
  worker liveness.
- arq's internal queue is stuck. Check Redis for stale entries
  in the arq job-queue keys.

This is the most common "the dashboard says X is registered but
nothing happens" symptom. Wake on-call.

### "Every minute" cron isn't firing

The webhook-drain cron fires every minute (`minute={0..59}` in arq
parlance). If the dashboard shows it registered but the
`webhook_deliveries` backlog is growing, the dispatcher is dead —
see [`runbook-webhook-deliveries.md`](runbook-webhook-deliveries.md)
for the drain-stuck triage path.

## Common crons + what their failure looks like

| Cron                      | Schedule        | Failure mode                                     |
| ------------------------- | --------------- | ------------------------------------------------ |
| `weekly_report_cron`      | Mondays 06:00   | Customer asks "where's my Monday report?"       |
| `webhook_drain_cron`      | Every minute    | `webhook_deliveries` pending count grows         |
| `evaluate_price_alerts`   | Daily 22:00     | Customers don't get next-day price-shift alerts  |
| `expire_rfq_slots`        | Hourly          | Stale RFQ rows persist past their deadline       |
| `retention_prune_cron`    | Weekly          | Tables grow; no automated cleanup               |
| `scrape_and_score_*`      | Daily / weekly  | Bidradar opportunity feed goes stale           |

When a customer reports a missing notification, this table is the
fastest mental map from "what they didn't get" to "which cron"
to investigate.

## Escalation

- **Cron silently registered but not firing**: page on-call. Worker
  process is dead or arq's loop is stuck.
- **Cron was supposed to deploy but isn't on the page**: check the
  CI deploy log; the new entry may not have shipped.
- **`calculate_next` raises for a known cron**: not urgent, but
  fix the schedule spec; the cron is effectively unscheduled.

## Related code

| Component                      | Lives in                                                |
| ------------------------------ | ------------------------------------------------------- |
| Cron registry                  | `apps/api/workers/queue.py::WorkerSettings.cron_jobs`   |
| Admin router                   | `apps/api/routers/cron_admin.py`                        |
| Frontend page                  | `apps/web/app/(dashboard)/admin/crons/page.tsx`         |
| Frontend hook                  | `apps/web/hooks/admin/useCrons.ts`                      |

## Pin tests (tripwires)

These tests guard the dashboard's contract from silent regressions:

- `apps/api/tests/test_cron_admin_surface_pin.py` — module presence,
  endpoint path, role gate, row shape, schedule formatter (weekday +
  every-minute patterns), description truncation, defensive
  next-run-on-raise, sort order, main.py wiring
- `apps/api/tests/test_arq_cron_schedules.py` — pins each cron's
  documented schedule (catches accidental tweaks to the
  `WorkerSettings.cron_jobs` literals)
- `apps/web/hooks/admin/__tests__/useCrons.test.tsx` — URL,
  envelope unwrap, 60-second refetch interval, cache-key stability
- `apps/web/app/(dashboard)/admin/__tests__/page.test.tsx` —
  landing-page tile for `/admin/crons` is present

If any of these go red on CI, the dashboard's contract has drifted —
investigate before merging the PR that broke them.
