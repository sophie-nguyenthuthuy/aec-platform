# Deploying the arq worker on Railway

The API service runs request-handlers only. Long-running and cron jobs
(drawbridge ingest, BidRadar scrape, weekly reports, CostPulse price
alerts, SiteEye photo analysis) belong on a separate service so they
don't block requests or get killed by Railway's per-request timeout.

## What this service does

| Job | Trigger | Why it can't run in the API |
|---|---|---|
| `drawbridge_ingest_job` | enqueued by `POST /api/v1/files` after upload | PDF chunk + embed = 30-60s per drawing |
| `weekly_report_job` | cron Mondays 06:00 UTC | LLM call + PDF render = 90s |
| `price_alerts_evaluate_job` | cron nightly 22:00 UTC | fanout per-org, ~5s × N tenants |
| `scrape_all_prices_job` | cron Sundays 03:00 UTC | network-bound, 10+ min |
| `photo_analysis_job` | enqueued from SiteEye uploads | GPU-bound (when wired to a remote model server) |
| `rfq_dispatch_job` | enqueued from CostPulse RFQ create | per-supplier SMTP fanout |

## Setup (one-time, ~3 minutes)

1. `https://railway.app/dashboard` → select your existing project (the one hosting `aec-platform-api`)
2. **+ New** (top-right) → **GitHub Repo** → pick `aec-platform` again
3. The service spins up. In the **Settings** tab:
   - **Service name**: `aec-platform-worker`
   - **Source repo**: `sophie-nguyenthuthuy/aec-platform` (auto-set)
   - **Branch**: `main`
   - **Root directory**: `./`
   - **Config-as-code path**: `railway.worker.json` ← **important**, otherwise Railway uses the default `railway.json` which builds the API

4. **Variables** tab → add (same values as the API service):

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | `postgresql+asyncpg://postgres.ejoxmgufldlsbmixqjcm:nguyenthuthuy182@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres` |
   | `DATABASE_URL_SYNC` | `postgresql://postgres.ejoxmgufldlsbmixqjcm:nguyenthuthuy182@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres` |
   | `DATABASE_URL_ADMIN` | same as `DATABASE_URL` |
   | `SUPABASE_URL` | `https://ejoxmgufldlsbmixqjcm.supabase.co` |
   | `SUPABASE_SECRET_KEY` | (sb_secret_…) |
   | `GOOGLE_API_KEY` | (AIza…) |
   | `REDIS_URL` | (rediss://… — same as API) |
   | `AEC_ENV` | `production` |
   | `SUPABASE_JWT_SECRET` | (same as API) |
   | `S3_ENDPOINT_URL` | (MinIO endpoint, e.g. `http://minio.aec-platform.vn:9000`) |
   | `S3_ACCESS_KEY_ID` | (MinIO access key) |
   | `S3_SECRET_ACCESS_KEY` | (MinIO secret) |
   | `S3_BUCKET` | `aec-platform-files` |
   | `S3_FORCE_PATH_STYLE` | `true` |

5. **Deploy** — Railway builds the worker image (~4 min first time) and
   starts the arq process. There's no HTTP endpoint to probe; check the
   logs for `arq:starting` + `arq:Starting worker for N functions`.

## Cron jobs

arq cron lives in `apps/api/workers/queue.py::WorkerSettings.cron_jobs`.
No external scheduler needed — arq's own scheduler fires the cron
specs against Redis. Railway's "Cron Schedule" feature is **not** used.

## Logs / observability

Logs stream to Railway's Logs tab. For richer observability:

- **Sentry**: set `SENTRY_DSN` on the worker service too (see L3-10)
- **arq metrics**: `/metrics` from the API service includes worker
  queue depth (instrumented in `apps/api/core/metrics.py`)

## Scaling

Single worker handles ~10 jobs/min. To scale:

- **Vertical**: bump Railway service plan ($10 → $20 → $50/mo for more CPU/RAM)
- **Horizontal**: change `concurrency` in `WorkerSettings` (default 10),
  or spin up a second `aec-platform-worker-2` service with the same
  config

## Local dev

`docker-compose up` already includes the worker service (Celery flavour
historically; switch to arq by changing `infra/docker/worker.Dockerfile`
`CMD` line to `arq workers.queue.WorkerSettings`).
