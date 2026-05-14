# Observability — Sentry + log drains

Three things to wire so an incident is recoverable:

  1. **Sentry** — error capture + tracing + (optional) profiling.
     Three deployables emit events into the same Sentry project,
     each tagged with `service=<api|worker|web>`:
       * `api` — FastAPI handlers (Railway).
       * `worker` — arq queue jobs (Railway, separate service).
       * `web` — Next.js browser SDK (Vercel).
  2. **Log drains** — stream stdout/stderr from Railway + Vercel to
     a queryable backend so a 3am incident isn't grep'd by clicking
     through 200-line dashboard panels.
  3. **Metrics** — `/metrics` endpoint on the API service exposes
     Prometheus exposition format (already wired, see
     `apps/api/core/metrics.py`). Scrape from Grafana Cloud or
     Better Stack; out of scope for this doc.

---

## 1. Sentry project setup

### 1a. Create the project

1. https://sentry.io → **+ Create Project** → **Python** platform.
2. Project name: `aec-platform`. Single project for api + worker +
   web — we tag events by service, not by project, so the issue
   list stays unified.
3. Skip the "configure your code" wizard — Sentry generates a DSN
   like `https://<key>@o123.ingest.sentry.io/<project_id>`. Copy it.
4. Settings → **Releases** → enable "Auto-resolve issues on deploy"
   so a regression that ships a fix auto-closes.

### 1b. Wire the API + worker (Railway)

Set on **both** the `aec-platform-api` and `aec-platform-worker`
services in Railway:

| Env var | Value | Notes |
|---|---|---|
| `SENTRY_DSN` | `https://...@.../...` | from step 1a-3 |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | 10% of requests traced |
| `SENTRY_PROFILES_SAMPLE_RATE` | `0` | turn on later if CPU-heavy endpoints need profiling |
| `SENTRY_RELEASE` | _(unset)_ | leave blank — `init_sentry` reads `RAILWAY_GIT_COMMIT_SHA` automatically |
| `AEC_ENV` | `production` | tags events with `environment=production` |

Verify on next deploy: Railway logs should show no Sentry warning;
trigger a 500 with `curl https://api.../api/v1/projects/00000000-0000-0000-0000-000000000000`
(unknown UUID → handled 404, not 500 — for a real test, use
`/_health/sentry` if defined, or wait for the first real exception).

### 1c. Wire the web (Vercel)

The web SDK is loaded **lazily** by `apps/web/components/SentryClient.tsx`
— no dependency churn until you opt in. To activate:

1. `cd apps/web && npm install @sentry/browser` (commit + push).
2. Vercel → Project → **Settings → Environment Variables**:

| Env var | Value | Scope |
|---|---|---|
| `NEXT_PUBLIC_SENTRY_DSN` | same DSN as the api | Production + Preview |
| `NEXT_PUBLIC_AEC_ENV` | `production` | Production |
| `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Production |
| `NEXT_PUBLIC_SENTRY_RELEASE` | _(optional)_ — set to `$VERCEL_GIT_COMMIT_SHA` if you want browser/server release correlation | Production |

`NEXT_PUBLIC_*` is required because the value ships to the browser.
If you accidentally use plain `SENTRY_DSN`, the client SDK won't
see it and you'll get silent no-op behaviour.

After redeploy, open the production site → open DevTools console →
run `Sentry.captureMessage("hello from web")`. The message should
appear in Sentry within ~30s, tagged `service=web`.

### 1d. Service grep in the Sentry issue list

Issues are tagged with one of:
  * `service:api` — Python exceptions from FastAPI handlers
  * `service:worker` — exceptions from arq jobs (when the worker
    service eventually runs its own `init_sentry` — same module,
    set `SENTRY_DSN` on the worker service env)
  * `service:web` — browser errors

Pin saved searches in Sentry for each so dashboards stay legible:

```
service:api environment:production
service:worker environment:production
service:web environment:production
```

---

## 2. Log drains

### 2a. Vercel → Better Stack (or Axiom)

1. Better Stack → **Sources** → **+ Create source** → "Vercel".
2. Copy the **Source token** + the ingestion URL.
3. Vercel → **Project Settings → Log Drains** → **+ Add log drain**:
   * **Type**: Datadog HTTP (compatible format)
   * **URL**: paste the Better Stack URL
   * **Secret**: paste the source token
4. Vercel ships every function log + edge log to the drain within
   ~30s of emission. Verify by clicking on any page → check the
   Better Stack live tail.

### 2b. Railway → Better Stack

Railway has built-in log drains via the **Observability** tab on
each service:

1. Service → **Observability** → **+ Add log drain**.
2. **Datadog HTTP** sink with the same Better Stack URL + token.

(Railway also supports raw `https://`/`syslog`/`tcp` sinks for
self-hosted log backends. The Datadog-format wrapper has the
widest compatibility — Better Stack, Datadog itself, Axiom, and
Grafana Cloud all parse it.)

### 2c. Search examples

The structured-log middleware on the API (`core.observability.setup_logging`)
emits one-line JSON in production, so every log entry already has
`request_id`, `user_id`, `org_id`, `path`. Better Stack search
syntax:

```
service:api status:500
service:worker job:weekly_report_job
service:api path:/api/v1/codeguard/scan duration_ms:>1000
```

For a long incident, pivot from a Sentry issue to the matching log
window: copy the `request_id` tag off the Sentry event, paste into
Better Stack → see every log line that request emitted.

---

## 3. Runbook checklist

When a customer reports a problem:

1. **Sentry first** — search issue list for `service:api` +
   `org_id:<their-org>` + last 24h. Most prod bugs surface here
   before the customer notices.
2. **Logs** — if the issue isn't in Sentry (e.g. a 200 with wrong
   data, not an exception), grep the log drain for the customer's
   `org_id` + the affected `path`.
3. **Reproduce** — use `?next=` against a local supabase to step
   through. The full middleware stack is identical to prod so
   reproduction parity is high.
4. **Fix forward** — commits to `main` ship to api (Railway) +
   web (Vercel) within ~3 min. Sentry's "Auto-resolve on deploy"
   closes the issue when the release tag matches.

---

## 4. What's *not* wired (and where to draw the line)

  * **Session replay** — Sentry can record DOM mutations of every
    session. We default `replaysSessionSampleRate: 0` because SOE
    customers haven't approved screen recording for vendor analysis.
    Enable per-customer after security review.
  * **Slack/email alerts** — Sentry's built-in alert rules cover
    "new issue", "regression", "spike in volume". Wire to a shared
    `#aec-platform-incidents` channel — but only after the issue
    list has been triaged once or twice, otherwise you'll firehose
    every cold-start exception into the channel.
  * **APM dashboards** — `/metrics` is Prometheus-formatted, so
    Grafana Cloud's free tier auto-scrapes if you point it at the
    Railway URL. Out of scope for this doc; raise a separate task
    when you need request-rate / p99-latency charts.
