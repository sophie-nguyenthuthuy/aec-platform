# Runbook: cron-watchdog Slack alerts

This runbook covers the on-call response to the two alert types
the cron watchdog sends to ops Slack:

- 🚨 `cron failed: <name> — <error>`
- ⏳ `cron stuck: <name> running Xs (~Y× p95)`

Both come from `services.cron_alerts`, registered as
`cron_failure_watchdog_cron` in `workers/queue.py` (every 5 min).

---

## 🚨 `cron failed` — fresh failure alert

### What just happened

The watchdog scanned `cron_runs` for rows that wrote `status='failed'`
in the last 5 minutes and sent **one Slack message per failing cron**
(deduplicated via `DISTINCT ON (cron_name)`, so a cron failing 5
minutes in a row produces 1 alert, not 5).

The alert text format:

```
🚨 cron failed: `<cron_name>` (Xms) — <truncated error>
```

`<cron_name>` is the arq-style `cron:<func>`. Click into
`/admin/crons/<cron_name>` (URL-encoded) for the full row + recent
history.

### Triage tree

1. **Open `/admin/crons`** and find the affected cron's row. The
   "Last run" cell will show the failed run with its truncated
   error message.

2. **Click into the drilldown** at `/admin/crons/<cron_name>` to
   see up to 20 recent runs. If the previous run also failed,
   you have a chronic failure (not a one-off blip) — wake on-call
   if it's a critical cron.

3. **Read the worker logs** — `kubectl logs -l app=worker | grep
   <cron_name>`. The `error_message` in `cron_runs` is truncated to
   2000 chars; the full traceback is in stdout.

4. **Decide**:
   - **One-off blip on a non-critical cron** — let the next run
     recover. Will close the loop with a "succeeded" row in the
     drilldown.
   - **Chronic failure on a critical cron** (auth, payments,
     drift detection) — page on-call.

### Critical-cron decoder

Map cron names to their criticality + the customer-facing impact:

| Cron                            | Criticality    | What customers notice if this fails repeatedly                                            |
| ------------------------------- | -------------- | ----------------------------------------------------------------------------------------- |
| `weekly_report_cron`            | Medium         | "Where's my Monday report?" tickets after 1-2 missed Mondays                              |
| `webhook_drain_cron`            | **Critical**   | Customer webhooks stop firing. Backlog grows in `webhook_deliveries`. Page IMMEDIATELY.  |
| `price_alerts_evaluate_job`     | Medium         | CostPulse subscribers don't get next-day price-shift alerts                              |
| `daily_activity_digest_cron`    | Low            | Watchers don't get their morning digest. Triage during business hours.                   |
| `rfq_deadlines_cron`            | Medium         | Stale RFQ slots persist past their deadline                                               |
| `retention_prune_cron`          | Low            | Tables grow; storage cost climbs. Triage during business hours.                          |
| `cron_failure_watchdog_cron`    | **Critical**   | The alerter itself failed → you wouldn't be reading this. If you ARE seeing this alert in Slack, the watchdog is working — its OWN row will appear in `/admin/crons` with the failure. |

### Common error patterns

| Error fragment                              | What it usually means                                              | Action                                                                |
| ------------------------------------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------- |
| `OperationalError`                          | DB blip — connection pool exhausted, replica lag, etc.            | Wait for next run. If 3+ consecutive fail, page DB on-call.          |
| `TimeoutError` / `httpx.TimeoutException`   | Outbound HTTP call timed out (Slack, mailer, scraper target)      | Usually transient. If a specific external service is sustained-down, that's the upstream incident, not ours. |
| `KeyError` / `AttributeError` / `TypeError` | Logic bug in the cron coroutine                                   | Roll back the most recent deploy that touched the cron's source.     |
| `IntegrityError`                            | Constraint violation — usually a UNIQUE conflict on a fan-out     | Either the cron lost idempotency or there's stale data. Read the SQL in the cron carefully. |

---

## ⏳ `cron stuck` — running too long alert

### What just happened (stuck variant)

The watchdog found a row in `cron_runs` with `status='running'`
AND `finished_at IS NULL` whose elapsed time has exceeded 3× the
cron's 7-day rolling p95 (calibrated boundary — see
`services.cron_alerts._STUCK_MULTIPLIER`).

The alert text format:

```
⏳ cron stuck: `<cron_name>` running Xs (~Y.Y× p95). Worker may
have crashed mid-run; check `/admin/crons/<cron_name>` for the
row id.
```

### Why this matters

Stuck crons are usually a worker crash (the wrapper INSERTed a
`running` row at start, then the worker died before the
finish-time UPDATE could fire). The row sits in `running` forever
until manually cleaned up. The watchdog's job is to catch that
**before** the next instance of the same cron tries to fire and
blocks (or worse, runs in parallel and double-processes).

### Triage tree (stuck variant)

1. **Open `/admin/crons/<cron_name>`** to find the stuck row's id
   and started_at. Note them.

2. **Check worker liveness** — `kubectl get pods -l app=worker`.
   If a pod is in `CrashLoopBackOff` or has restarted recently,
   that's your culprit. The crash happened mid-cron.

3. **Check if a NEWER instance of the same cron has fired since**
   — if yes (and it's running normally), the stuck row is a
   leftover artefact from the previous worker. Mark it failed
   manually:

   ```sql
   UPDATE cron_runs
   SET status = 'failed',
       finished_at = NOW(),
       error_message = 'manually closed: worker crashed before finish-time UPDATE'
   WHERE id = '<row_id>';
   ```

4. **If no newer instance has fired** AND the worker is alive,
   the cron is genuinely hung (deadlocked SQL, infinite loop).
   Inspect:
    - `SELECT * FROM pg_stat_activity WHERE state != 'idle'` —
      a long-running query attributed to the worker is the
      common deadlock.
    - Worker stdout for a stack trace.
    - Restart the worker if the cron is critical (the next tick
      will fire fresh).

5. **After you've manually closed the row, the next watchdog tick
   will see no running rows for this cron** and the alerts stop.
   You don't need to silence anything.

### Why 3× p95?

- Healthy crons cluster within 2× p95 even on a slow day.
- 3× catches genuinely hung runs without false-flagging slow-but-
  progressing ones.
- Lower (1.5×, 2×) wakes on-call at 3am for healthy slow nights.
- Higher (5×, 10×) means slower MTTR on hung crons (a cron whose
  p95 is 1m has to run 10m before alerting at 10× — vs 3m at 3×).

A cron with **fewer than 3 successful samples** in the 7-day
window has no baseline; the watchdog skips it (returning False
from `_is_stuck`). This is the "fresh deploy doesn't get paged"
guard — first runs aren't alertable.

A cron with **p95 = 0** (a no-op cron whose successful runs all
took 0ms) is also skipped. Multiplier × 0 = 0 → every run would
flag. Pin in the source: `_is_stuck` returns False on `p95_ms <= 0`.

---

## When ALL crons stop alerting

This is the silent-watchdog failure mode. The cron failed but
the alerter failed too, so the only signal is "I haven't seen a
cron alert all day."

### Self-observability check

Every 5 min, the watchdog ITSELF appears in `/admin/crons` (it's
self-wrapped via `_telemetry`). If you suspect the alerter is
down:

1. Open `/admin/crons` and look for `cron_failure_watchdog_cron`.
2. Check its **Last run** cell:
    - **Green "succeeded"** within the last 5 min — alerter is
      healthy. If you're not seeing alerts but expected to, look
      at `/admin/slack-deliveries` filtered by kind=`cron_failure`
      to see what the alerter tried to send.
    - **Red "failed"** — the alerter itself is broken. The
      `error_message` will tell you why; recent suspects:
        - DB connection lost (cron_runs query fails)
        - Slack webhook revoked (`send_slack` returns
          `slack_http_404`)
    - **No row at all** — cron isn't registered. Check
      `workers/queue.py::WorkerSettings.cron_jobs`; the
      `cron_failure_watchdog_cron` entry MUST be present (pinned
      by `tests/test_arq_cron_schedules.py`).

### Cross-checks ops can run by hand

```sql
-- Did anything fail in the last hour?
SELECT cron_name, started_at, status, error_message
FROM cron_runs
WHERE status = 'failed'
  AND started_at >= NOW() - INTERVAL '1 hour'
ORDER BY started_at DESC;

-- Anything running longer than 15 minutes?
SELECT cron_name, id, started_at,
       EXTRACT(EPOCH FROM (NOW() - started_at)) AS elapsed_sec
FROM cron_runs
WHERE status = 'running'
  AND finished_at IS NULL
  AND started_at < NOW() - INTERVAL '15 min'
ORDER BY started_at;

-- Did the watchdog itself run in the last 15 min?
SELECT * FROM cron_runs
WHERE cron_name = 'cron:cron_failure_watchdog_cron'
ORDER BY started_at DESC
LIMIT 5;
```

If the watchdog hasn't run in 15+ min, the worker is dead.

---

## Related code

| Component                        | Lives in                                                |
| -------------------------------- | ------------------------------------------------------- |
| Watchdog service                 | `apps/api/services/cron_alerts.py`                      |
| `_is_stuck` decision rule        | `services/cron_alerts.py::_is_stuck`                    |
| Watchdog cron registration       | `apps/api/workers/queue.py::cron_failure_watchdog_cron` |
| Slack send primitive             | `apps/api/services/slack.py`                            |
| Slack telemetry persistence      | `apps/api/services/slack_telemetry.py`                  |
| Cron-runs table                  | `apps/api/migrations/0042_cron_runs.py`                 |
| Cron-registry dashboard          | `/admin/crons`                                          |
| Cron drilldown                   | `/admin/crons/<cron_name>`                              |
| Slack-deliveries dashboard       | `/admin/slack-deliveries` (filter kind=cron_failure / cron_stuck) |

## Pin tests (tripwires)

These guard the watchdog's calibration + wiring against silent
regressions:

- `apps/api/tests/test_cron_alerts_watchdog_pin.py` — constants
  (5 min window, 3× multiplier, 3-sample baseline floor, 7-day
  window), `_is_stuck` decision rule, source-grep on DISTINCT ON
  + Python-side filter, watchdog wiring (`_telemetry` wrap, both
  check paths called with independent try/except)
- `apps/api/tests/test_arq_cron_schedules.py::test_cron_failure_watchdog_cron_runs_every_5_minutes`
  — cross-pin that the cron tick matches `_FRESH_FAILURE_WINDOW_MINUTES`

If any go red on CI, the watchdog's contract has drifted —
investigate before merging the PR that broke them.
