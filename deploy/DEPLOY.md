# Free-tier deploy

Deploy the AEC Platform end-to-end on free hosting tiers so you can share a public URL. Total monthly cost: **$0** (within free quotas). Total setup time: **2-3 hours**, most of it spent waiting on first-time provisioning.

The existing `.github/workflows/deploy.yml` deploys to AWS ECS — that's the production-grade target. This guide is the parallel "demo / preview" path that doesn't need AWS.

## Stack at a glance

| Layer | Service | Why |
|---|---|---|
| Web (Next.js) | **Vercel** | First-class Next.js host, free hobby tier, automatic HTTPS, GitHub-push deploys |
| Backend API (FastAPI) | **Vercel Python serverless functions** | Co-located with the web app on Vercel; no extra host to manage |
| Postgres + pgvector | **Supabase** | Free 500MB DB with pgvector pre-enabled, managed auth, storage, REST proxy |
| Auth | **Supabase Auth** | Already wired into `apps/web/lib/supabase-browser.ts` and the FastAPI JWT middleware |
| Redis (queue + cache) | **Upstash Redis** | Free tier covers light traffic; serverless-friendly REST API option |
| File storage | **Supabase Storage** | Same project as DB, S3-compatible API |
| LLM | **Anthropic + OpenAI** | Bring your own keys (pay-per-use) |

## Caveats — what works and what doesn't

Be honest with yourself before starting:

✅ **Works on free tier**
- All 90+ UI pages
- Login / signup / password reset / invite flow
- CRUD across every module (projects, RFIs, submittals, change orders, daily logs, etc.)
- Synchronous LLM features: CodeGuard Q&A, Drawbridge document Q&A, WinWork proposal generation, weekly report drafting
- Multi-tenant row-level-security
- File uploads to Supabase storage

⚠️ **Degraded on free tier**
- **No background workers.** Vercel functions can't run ARQ. Dropped features: BidRadar's scheduled tender scraper, weekly-report cron, embedding backfills, RFQ dispatch on a delay, price-alert evaluator. Workarounds: trigger these manually via API endpoints, or wire to a free cron service like `cron-job.org` hitting a webhook endpoint.
- **60-second function timeout.** Long Q&A streams (>60s) get cut off. Most queries finish in <15s so this is rarely hit, but a complex CodeGuard scan over a 200-page PDF will fail.
- **Cold starts.** First request after ~5min of inactivity wakes the function (~2-4s). Acceptable for a demo, not for a real app.
- **50MB function size limit (free tier).** The full FastAPI + LangChain + pgvector bundle is borderline. If we exceed this, we'll need to either upgrade to Vercel Pro ($20/mo, 250MB limit) or split into multiple smaller functions per router group.

❌ **Won't work on free tier**
- **SiteEye safety detection (YOLOv8m).** Needs a GPU. Drop this feature or run the Ray Serve container elsewhere later.
- **Elasticsearch BM25 hybrid retrieval.** Drop; the platform falls back to pgvector-only dense search automatically.
- **WeasyPrint PDF export.** Needs `libpango` / `libcairo` system deps that Vercel Python doesn't provide. Use the `reportlab` PDF path for BOQ exports (already supported) or generate PDFs client-side.

## Prerequisites

1. **GitHub account** with the repo pushed to your fork
2. **Vercel account** (https://vercel.com/signup — sign in with GitHub)
3. **Supabase account** (https://supabase.com/dashboard — free tier)
4. **Upstash account** (https://upstash.com — free tier)
5. **Anthropic API key** (https://console.anthropic.com — pay-per-use, ~$5 credit usually enough for demo)
6. **OpenAI API key** (https://platform.openai.com — pay-per-use, used for embeddings)

The first 4 are free; the LLM keys are pay-per-use but very cheap for demo traffic (~$1-5/month at light usage).

## Deployment walkthrough

### Step 1 — Supabase project

1. Go to https://supabase.com/dashboard → "New Project". Name it `aec-platform`, pick the closest region (Singapore for SEA, Frankfurt for EU). Save the database password — you'll need the connection string.
2. In **Database → Extensions**, enable `vector` (pgvector). It comes pre-installed but disabled.
3. In **Settings → API**, copy:
   - **Project URL** → `NEXT_PUBLIC_SUPABASE_URL`
   - **anon / publishable key** → `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
   - **service_role secret** (under "Project API keys") → `SUPABASE_SECRET_KEY` *(server-only, never ship to browser)*
4. In **Settings → Database → Connection string**, grab the `URI` (the `postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres` one). You need BOTH:
   - **Session pooler URI** (port 5432, transaction mode) for runtime
   - **Direct connection** for alembic migrations
5. Run the database bootstrap script (creates the `aec_app` role + applies all 33 alembic migrations + seeds demo data):

   ```bash
   # From repo root
   cd apps/api
   export DATABASE_URL_SYNC="postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres"
   export DATABASE_URL="postgresql+asyncpg://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres"
   pip install -r requirements.txt
   alembic upgrade head
   PYTHONPATH=".:../:../ml" python -m scripts.seed_demo
   ```

   If `seed_demo` complains about LLM keys, set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` first — the seed populates synthetic embeddings for CodeGuard demo Q&A.

6. **Configure Supabase Auth** → Settings → Auth → URL Configuration:
   - **Site URL**: leave empty for now, set after Vercel deploy in Step 4
   - **Redirect URLs**: same — fill in after Step 4

### Step 2 — Upstash Redis

1. Go to https://upstash.com → "Create Database" → Redis. Pick the closest region. Tier: free.
2. Copy the **TLS connection string** (starts with `rediss://`). This becomes `REDIS_URL`.

### Step 3 — LLM keys

1. **Anthropic**: https://console.anthropic.com → API keys → create key. Copy → `ANTHROPIC_API_KEY`. Top up $5-10 credit.
2. **OpenAI**: https://platform.openai.com/api-keys → create key. Copy → `OPENAI_API_KEY`. Top up $5 credit (embeddings are very cheap, ~$0.10 per 1M tokens).

### Step 4 — Vercel deploy

1. Push the repo (with the `deploy/` and `api/` folders added by this branch) to GitHub.
2. Vercel dashboard → "Add New Project" → import your GitHub repo.
3. **Framework Preset**: Next.js (auto-detected). **Root Directory**: leave as `./` (the `vercel.json` at repo root configures the monorepo).
4. **Build & Output Settings** → override:
   - **Build Command**: `pnpm --filter @aec/web build`
   - **Install Command**: `pnpm install --frozen-lockfile || pnpm install`
5. **Environment Variables** — paste these:

   | Name | Value | Scope |
   |---|---|---|
   | `NEXT_PUBLIC_SUPABASE_URL` | `https://[ref].supabase.co` | All |
   | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | (anon key) | All |
   | `NEXT_PUBLIC_API_URL` | leave empty — same-origin via `/api` rewrite | All |
   | `DATABASE_URL` | postgresql+asyncpg://… session pooler | Production, Preview |
   | `DATABASE_URL_SYNC` | postgresql://… direct connection | Production, Preview |
   | `SUPABASE_URL` | `https://[ref].supabase.co` | Production, Preview |
   | `SUPABASE_SECRET_KEY` | (service_role secret) | Production, Preview |
   | `REDIS_URL` | rediss://… from Upstash | Production, Preview |
   | `ANTHROPIC_API_KEY` | sk-ant-… | Production, Preview |
   | `OPENAI_API_KEY` | sk-… | Production, Preview |
   | `AEC_ENV` | `production` | Production |
   | `WEB_BASE_URL` | `https://[your-vercel-domain].vercel.app` | Production |
   | `CORS_ORIGINS` | `["https://[your-vercel-domain].vercel.app"]` | Production |

6. Click **Deploy**. First build takes ~5-8 minutes (Python deps install slowly).
7. Once green, copy the deploy URL (e.g. `aec-platform-xyz.vercel.app`).
8. Go back to **Supabase → Auth → URL Configuration** and fill in:
   - Site URL: `https://[your-vercel-domain].vercel.app`
   - Redirect URLs: `https://[your-vercel-domain].vercel.app/**`

### Step 5 — Verify

1. Open `https://[your-vercel-domain].vercel.app`. You should see the login screen.
2. Sign up with an email + password. If Supabase email confirmation is **off** (default for new projects), you're logged in immediately.
3. The dashboard loads. The demo seed gave you 1 org + 1 project + sample data across every module.
4. Click into Pulse, SiteEye, CodeGuard, etc. CRUD should work. CodeGuard Q&A should return a real answer from Anthropic.

If something breaks, check **Vercel → Logs** (real-time function logs) and **Supabase → Logs → Postgres** in parallel.

## File map of what this branch adds

```
deploy/
  DEPLOY.md             this guide
  STEPS.md              checklist version for fast-tracking
  env.production.example  every env var template
api/
  index.py              Vercel Python serverless wrapper around FastAPI
  requirements.txt      slimmed deps for Vercel runtime (weasyprint dropped)
vercel.json             monorepo build + rewrite config
scripts/
  init-supabase.sh      idempotent migrate + seed runner
```

## Troubleshooting

**"Module not found" in Vercel function logs** — the Python entrypoint can't see `apps/api/`. Check `vercel.json` `functions[api/index.py].includeFiles` covers the FastAPI source.

**"Function exceeded 50MB"** — bundle too big. Options:
1. Remove unused deps from `api/requirements.txt`
2. Upgrade to Vercel Pro (250MB)
3. Split by router group into multiple Python functions (see `vercel.json` comments for how)

**Cold-start timeouts on first request** — Vercel Hobby functions sleep after ~5min idle. Wake takes ~3s. Either accept it for a demo or schedule a `cron-job.org` ping every 4min.

**Supabase Postgres throws "permission denied for schema public"** — you skipped the `aec_app` role creation in alembic migration `0010_app_role`. Re-run `alembic upgrade head` against the direct (not pooled) connection string.

**"User couldn't be created" on signup** — Supabase Auth requires the email domain to be allowed. Settings → Auth → Email Auth → make sure "Enable Email provider" is on. For demo, leave "Confirm email" off.

**LLM calls hang then time out at 60s** — that's the Vercel function timeout. Check Vercel function logs for the actual upstream error (OpenAI / Anthropic rate limit, no credit, etc.).

## Moving off the free tier later

If you want to graduate to the production path:
- The existing `.github/workflows/deploy.yml` runs AWS ECS deploys end-to-end. Provision the AWS account via `infra/terraform/` and `gh secret set` the OIDC credentials.
- Keep Vercel for the web frontend — it's a great frontend host even when the backend moves to ECS.
- Update `NEXT_PUBLIC_API_URL` in Vercel env to point at the ECS-hosted backend, drop the `/api` rewrite in `vercel.json`, redeploy.
