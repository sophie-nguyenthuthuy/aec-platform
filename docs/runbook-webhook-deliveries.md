# Runbook: `/admin/webhook-deliveries` dashboard

## What this is

Customers configure outbound webhooks (per-org, per-event-type) via
`POST /api/v1/webhooks/subscriptions`. When an event fires, the
dispatcher cron drains pending rows in `webhook_deliveries`, POSTs
the payload to the customer's URL, and records the response.

When delivery fails, the platform sees it but the customer often
doesn't — we retry with backoff, and they get the message
eventually (or don't, if we exhaust attempts). The dashboard at
`/admin/webhook-deliveries` is the cross-tenant view of that
delivery health: who's broken, when, and is it one customer's
receiver or our dispatcher.

## How to read the dashboard

Each summary card is one **event type** (e.g. `rfq.created`)
aggregated **across all orgs** in the lookback window. The colour
scheme matches `/admin/slack-deliveries`:

| Colour | Meaning                                              |
| ------ | ---------------------------------------------------- |
| Green  | All attempts delivered                               |
| Amber  | Some failures but most delivered                     |
| Red    | Every attempt failed                                 |
| Grey   | No attempts in window                                |

The single most important field on each card is **`distinct_orgs`**:

| Card state                                             | Most likely root cause                                              | Who to wake up                              |
| ------------------------------------------------------ | ------------------------------------------------------------------- | ------------------------------------------- |
| Red, `distinct_orgs > 1` (chip: "platform-wide")       | Our dispatcher, network egress, or DB                               | **Page on-call** — it's our infra           |
| Red, `distinct_orgs == 1`                              | One customer's receiver is misconfigured (DNS, cert, deploy)        | Tell support to email/call the customer    |
| Amber, `distinct_orgs > 1`                             | Flapping somewhere — check the recent-attempts table               | Triage, don't page                          |
| Amber, `distinct_orgs == 1`                            | Same single-customer pattern as above                               | Support, low priority                       |

The **"platform-wide"** chip on a red card is the explicit signal that
this is your problem, not the customer's.

The recent-attempts table below the cards has filter pills for
each status (failed, in-flight, pending, delivered). The default
filter is "failed" — that's the triage view for "what's broken?"

## State machine

The `status` column on each row is one of:

| Status      | Meaning                                                  | Next transition                                  |
| ----------- | -------------------------------------------------------- | ------------------------------------------------ |
| `pending`   | Queued by the publisher; not yet attempted               | → `in_flight` when the cron picks it up          |
| `in_flight` | Currently being POSTed to the customer's URL             | → `delivered` (200), `pending` (retry), `failed` (max attempts)  |
| `delivered` | Customer's receiver returned 2xx                         | Terminal                                         |
| `failed`    | Exhausted retry budget (typically 5 attempts)            | Terminal                                         |

A row stuck in `in_flight` for >5 minutes means a stuck dispatcher
worker — check the arq worker logs.

## Common error_message values

| Pattern                                  | What it means                                              | Action                                                     |
| ---------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------- |
| `Connection refused`                     | Customer's receiver isn't listening                        | Tell customer to bring their endpoint back up              |
| `Name resolution failed` / `nodename`    | Customer's webhook URL DNS doesn't resolve                 | Customer's DNS issue; have them update the URL             |
| `SSL: CERTIFICATE_VERIFY_FAILED`         | Customer's TLS cert is expired / self-signed               | Customer's cert issue; we don't accept self-signed         |
| `received 502 Bad Gateway`               | Customer's reverse proxy is up but their app is down       | Tell customer to restart their app                         |
| `received 401 Unauthorized`              | Customer's receiver rejected our HMAC signature            | They've changed the secret; have them re-mint              |
| `received 5xx` from many orgs            | Common upstream — could be a shared SaaS receiver          | Check if many customers use the same hostname pattern      |

## When the dashboard goes red

### Path A: `distinct_orgs > 1` (platform-wide)

1. **Check arq worker logs** — search for the dispatcher cron's run
   entries. If they've stopped firing, the worker is dead. Page
   on-call.

2. **Check egress** — try `curl https://example.com/anything` from
   inside the API container. If that fails too, our outbound
   network path is broken.

3. **Check the database** — `SELECT count(*), status FROM webhook_deliveries
   WHERE created_at > now() - interval '15 min' GROUP BY status;`.
   If you see a flood of `pending` and zero `delivered`, the
   dispatcher isn't draining. If you see lots of `in_flight` not
   transitioning, workers are stuck mid-POST (look for httpx
   timeouts in the logs).

4. **Roll back the most recent deploy** that touched
   `services/webhooks.py` or the dispatcher cron — see the pin
   `apps/api/tests/test_webhook_outbox_state_machine_pin.py` for
   the state-machine literals; a typo in any of those (`pending` →
   `Pending`) would silently break the drain query.

### Path B: `distinct_orgs == 1` (single-customer)

1. **Click the failing card to filter the recent-attempts table**
   to that event type, then sort by org. Confirm the failures
   really are all one org.

2. **Pull the org's contact** from `organizations.id =
   <organization_id>`. Hand off to support with:
    - The org's id
    - The event type
    - The error_message pattern
    - When it started

3. **No on-call action** unless the customer is on a plan that
   commits to webhook delivery; even then, our side is healthy
   and they need to fix theirs.

## When the dashboard shows pending backlog

The card shows "{n} pending in queue" when `pending_count > 0`. A
small backlog is normal — events queue between cron runs. A growing
backlog (>5 min worth of events) means the dispatcher isn't keeping
up.

```sql
-- How big is the backlog right now?
SELECT count(*) FROM webhook_deliveries WHERE status = 'pending';

-- How old is the oldest pending row?
SELECT now() - min(created_at) AS oldest_pending_age
FROM webhook_deliveries WHERE status = 'pending';
```

If `oldest_pending_age` is >15 minutes, the dispatcher is stuck.
Page on-call.

## What this dashboard *isn't* useful for

- **Customer-side debugging** — customers see their own webhook
  deliveries via `GET /api/v1/webhooks/deliveries` (per-org). If
  you're trying to help one customer, that's the better surface
  because it shows them the payload they configured.

- **Replay / retrigger** — read-only by design (admin telemetry,
  not a debugging tool that exposes customer payloads). For replay,
  query the DB directly with the row id.

- **Per-org reliability SLOs** — the rollup is per-event-type,
  cross-tenant. If you need "what's org X's delivery success rate?"
  filter the recent-attempts table by `organization_id` and count
  manually, or write a one-off SQL query against `webhook_deliveries`.

## Related code

| Component                                          | Lives in                                                   |
| -------------------------------------------------- | ---------------------------------------------------------- |
| ORM models                                         | `apps/api/models/webhooks.py`                              |
| Dispatcher cron                                    | `apps/api/services/webhooks.py`                            |
| Migration that creates the tables                  | `apps/api/alembic/versions/0025_webhooks.py`               |
| Admin router (the dashboard endpoints)             | `apps/api/routers/webhook_deliveries_admin.py`             |
| Customer-facing router (per-org)                   | `apps/api/routers/webhooks.py`                             |
| Frontend page                                      | `apps/web/app/(dashboard)/admin/webhook-deliveries/page.tsx` |
| Frontend hook                                      | `apps/web/hooks/admin/useWebhookDeliveriesAdmin.ts`        |

## Pin tests (tripwires)

These tests guard the dashboard from silent regressions:

- `apps/api/tests/test_webhook_deliveries_admin_surface_pin.py` —
  schema + router shape; the security pin that `payload` MUST NOT
  surface in the admin view (cross-tenant payload exposure)
- `apps/api/tests/test_webhook_outbox_state_machine_pin.py` — the
  four `status` literals (`pending`/`in_flight`/`delivered`/`failed`),
  ORM column shape, default values
- `apps/api/tests/test_webhook_delivery_headers_pin.py` —
  outbound HMAC + timestamp headers
- `apps/api/tests/test_webhooks_backoff_schedule.py` — retry budget
- `apps/web/hooks/admin/__tests__/useWebhookDeliveriesAdmin.test.tsx`
  — URL, query keys, status filter, query-key collision avoidance

If any of these go red on CI, the dashboard's contract has drifted —
investigate before merging the PR that broke them.
