# Runbook: `/admin/slack-deliveries` dashboard

## What this is

The platform Slack webhook fires alerts to ops (today: scraper drift;
future: RFQ-deadline summary, weekly digest, dispatcher backlog).
Without telemetry, the only signal that delivery has stopped working
is a worker log WARNING — easy to miss, especially on a quiet on-call
rotation.

The `/admin/slack-deliveries` dashboard surfaces per-`kind` delivery
health from the `slack_deliveries` table (one row per attempt,
written by `services.slack_telemetry.record_delivery_attempt`).

## How to read the dashboard

Each summary card is one `kind` of alert (e.g. `scraper_drift`).
Card colour encodes severity:

| Colour | Meaning                                          | Action                                        |
| ------ | ------------------------------------------------ | --------------------------------------------- |
| Green  | All attempts in window delivered                 | Nothing                                       |
| Amber  | At least one failure but some delivered          | Investigate when convenient                   |
| Red    | Every attempt failed (delivered_rate = 0)        | **Page on-call** — the alert pipeline is down |
| Grey   | No attempts in window                            | Likely fine; cron may not have fired yet      |

The "Last failure" breadcrumb on each card is what tells you what
broke. Click into the recent-attempts table below the cards and
toggle "Failures only" to see the full list.

## Common reason strings (the `reason` column)

These come straight from `services.slack.send_slack`'s return shape
— what you see is what the Slack webhook returned.

| Reason                         | What it means                                    | Fix                                                               |
| ------------------------------ | ------------------------------------------------ | ----------------------------------------------------------------- |
| `slack_not_configured`         | `OPS_SLACK_WEBHOOK_URL` env var is empty         | Expected in dev; in prod, set the env var via deploy config       |
| `transport:TimeoutException`   | Slack didn't respond in 5s                       | Usually transient. Page if it persists >10 minutes                |
| `transport:TransportError`     | TCP / TLS issue reaching Slack                   | Check egress firewall + DNS; usually network-side                 |
| `slack_http_429`               | Slack rate-limited us                            | We're publishing too fast — back off or batch                     |
| `slack_http_404` / `_410`      | Webhook URL revoked or invalid                   | The Slack admin needs to mint a new URL; rotate `OPS_SLACK_WEBHOOK_URL` |
| `slack_http_400`               | Bad payload (usually invalid Block Kit)          | The `render_*` function for that `kind` produced bad blocks       |

## Delivery `kind` decoder (the `kind` column on the dashboard)

The `kind` discriminator groups attempts by what triggered them.
Filter the cards by kind to triage one alert pipeline at a time.

| Kind             | What sent it                                     | What "every attempt failed" means                                                                                                                              |
| ---------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scraper_drift`  | Drift detector in `services.price_scrapers`      | Slack pipeline broken AT THE SAME TIME as a drift event. Email path may still be working — check `OPS_ALERT_EMAILS` recipients haven't received it either.    |
| `cron_failure`   | `services.cron_alerts.check_failing_crons`       | A cron failed AND we couldn't tell ops about it. Read the recent `cron_runs` table directly: `SELECT * FROM cron_runs WHERE status='failed' ORDER BY started_at DESC LIMIT 10`. |
| `cron_stuck`     | `services.cron_alerts.check_stuck_crons`         | A cron has been `running` past 3× its 7d p95 — likely a crashed worker. Restart the worker; look for un-finished `cron_runs` rows: `SELECT * FROM cron_runs WHERE status='running' AND started_at < NOW() - INTERVAL '15 min'`. |

If you add a new alert pipeline, add it to this table AND pin the
new `kind` literal in `services.cron_alerts._KIND`-style + the
`/admin/slack-deliveries` filter.

## When the dashboard goes red

1. **First, sanity-check Slack itself** — open <https://status.slack.com/>.
   If Slack is having an incident, the alerts will resume on their own.

2. **Check the recent-attempts table** for the failing kind. Look at
   `reason` + `status_code` (HTTP) for each row. If they're all the
   same, you have a systematic failure (URL rotated, payload broken).
   If they're varied, it's likely flapping infrastructure.

3. **Check the worker logs** for the `services.slack` logger. Search
   for `slack.send_slack:` to see what was tried just before each
   failure. The dashboard's text preview shows the rendered text
   fallback, but logs have the full stacktrace if a render function
   raised mid-payload.

4. **For a webhook URL rotation**, edit the env var via the deploy
   pipeline (don't commit the URL). The next cron tick will pick
   up the new URL — the dashboard's red card flips to green within
   one cron interval.

## Escalation

- **Slack URL needs rotating**: ping the platform-admin Slack owner
  (the human who controls the workspace's incoming webhook config).
- **Sustained 5xx from Slack** with no status-page incident: open a
  Slack support ticket; their incidents lag the public status page.
- **`render_*` function broken** (HTTP 400 with Block Kit error):
  this is our bug, not Slack's. Roll back the most recent deploy
  that touched `services/slack.py` or the relevant alert pipeline
  (e.g. `services/ops_alerts.py` for drift alerts).

## What this dashboard *isn't* useful for

- **Per-tenant webhook health** — that's `/admin/webhook-deliveries`.
  The platform Slack webhook is single-URL cross-tenant; customer-
  facing webhooks are per-org.

- **Knowing when ops_alerts decided NOT to send** — the `delivered=False`
  + `reason="slack_not_configured"` rows ARE the "we decided not to"
  signal. Pre-decision filtering (e.g. "this drift wasn't bad enough
  to alert on") is in `services.price_scrapers` upstream of the
  Slack call and won't show up here.

## Related code

| Component                                       | Lives in                                        |
| ----------------------------------------------- | ----------------------------------------------- |
| ORM model                                       | `apps/api/models/slack_delivery.py`             |
| Persistence helper (writes the rows)            | `apps/api/services/slack_telemetry.py`          |
| Slack send primitive (returns the shape we log) | `apps/api/services/slack.py`                    |
| Migration that creates the table                | `apps/api/alembic/versions/0037_slack_deliveries.py` |
| Admin router (the dashboard endpoints)          | `apps/api/routers/slack_deliveries.py`          |
| Frontend page                                   | `apps/web/app/(dashboard)/admin/slack-deliveries/page.tsx` |
| Frontend hook                                   | `apps/web/hooks/admin/useSlackDeliveries.ts`    |

## Pin tests (tripwires)

These tests guard the dashboard's contract from silent regressions:

- `apps/api/tests/test_slack_deliveries_surface_pin.py` — schema +
  router shape
- `apps/api/tests/test_slack_render_contract_pin.py` — `send_slack`
  + `render_slack_drift_alert` return shapes
- `apps/web/hooks/admin/__tests__/useSlackDeliveries.test.tsx` —
  URL, query keys, tri-state filter

If any of these go red on CI, the dashboard's contract has drifted —
investigate before merging the PR that broke them.
