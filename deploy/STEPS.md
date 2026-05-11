# Deploy in 12 steps

Fast-track checklist — full reasoning is in `DEPLOY.md`. Total time ~2 hours, mostly waiting on provisioning + the first Vercel build.

## What only YOU can do

These require your hands on a browser or your GitHub account. I can't do them from here.

- [ ] **1. Push this branch to GitHub** — `git push` from your machine.
- [ ] **2. Create a Supabase project** — https://supabase.com/dashboard → New Project, named `aec-platform`, closest region (Singapore for SEA). Save the DB password.
- [ ] **3. Enable pgvector** — Supabase → Database → Extensions → search "vector" → enable.
- [ ] **4. Grab credentials from Supabase** — Settings → API:
  - Project URL → save as `SUPABASE_URL_VALUE`
  - anon key → save as `SUPABASE_ANON_KEY_VALUE`
  - service_role secret → save as `SUPABASE_SECRET_KEY_VALUE`
- [ ] **5. Grab DB connection strings from Supabase** — Settings → Database:
  - Connection pooling (Transaction mode) → save as `DATABASE_URL_VALUE` (prepend `postgresql+asyncpg://`)
  - Direct connection → save as `DATABASE_URL_SYNC_VALUE`
- [ ] **6. Create an Upstash Redis** — https://upstash.com → Create Database (Redis) → free tier, closest region. Copy the TLS URL (starts `rediss://`) → save as `REDIS_URL_VALUE`.
- [ ] **7. Get a Google AI Studio key** — https://aistudio.google.com → "Get API key" → Create. Free, no card. Starts `AIza…`. This is your `GOOGLE_API_KEY`.
- [ ] **8. Run database bootstrap from your machine** (one time):
  ```bash
  export DATABASE_URL_SYNC="<paste from step 5>"
  export DATABASE_URL="<paste from step 5>"
  export GOOGLE_API_KEY="<paste from step 7>"
  ./scripts/init-supabase.sh
  ```
  Takes ~3 minutes. Prints a dev JWT + org/project IDs at the end — save the org ID, you'll log in as that org's owner once auth is wired.
- [ ] **9. Create a Vercel project** — https://vercel.com/new → import your GitHub repo. Framework: Next.js (auto-detected). Root directory: `./` (don't change). Keep the build & install commands as configured in `vercel.json`.
- [ ] **10. Paste env vars in Vercel** — Project → Settings → Environment Variables. Copy each value from `deploy/env.production.example` and the ones you saved in steps 4-7. **Don't skip `AEC_ENV=production`** — without it the API boots with the dev JWT secret and refuses any real Supabase token.
- [ ] **11. Trigger deploy** — Vercel auto-deploys on import. First build is ~5-8 minutes (Python deps). Watch the build log for "Build Completed".
- [ ] **12. Wire Supabase Auth → Vercel domain** — Supabase → Authentication → URL Configuration:
  - Site URL: `https://YOUR-PROJECT.vercel.app`
  - Redirect URLs: `https://YOUR-PROJECT.vercel.app/**`

## Smoke test (≈ 2 min)

Open `https://YOUR-PROJECT.vercel.app/login`:

1. **Signup** — register a fresh email + password. If Supabase email confirmation is OFF (default), you're in.
2. **Dashboard loads** — sidebar visible, "Hôm nay" page renders.
3. **Pulse → Dự án** — your seeded project shows up.
4. **CodeGuard → Hỏi quy chuẩn** — type "Khoảng cách thoát hiểm tối đa?" → should return an answer with citations. **This is the critical end-to-end test** — it exercises Vercel + Supabase + LLM keys + pgvector all at once.

If the CodeGuard query hangs or fails: open Vercel → Logs and grep for `codeguard` to see the upstream error.

## What's NOT working on the free tier (and that's OK)

- BidRadar's auto-scraper (no background worker on Vercel). The UI works, the data won't refresh — to trigger a manual scrape, call `POST /api/v1/bidradar/scrape` from `/docs/api`.
- Weekly report cron. Manual trigger via `POST /api/v1/siteeye/reports`.
- SiteEye photo safety detection (needs a GPU server). The upload UI works, the AI tagging just won't run.
- Long Q&A streams (>60s). Rarely an issue.
- WeasyPrint PDF reports. `reportlab` fallback handles BOQs.

If any of these become important: graduate to the AWS ECS path (`infra/terraform/` + the existing `.github/workflows/deploy.yml`).

## Files this branch added

```
deploy/
  DEPLOY.md                 long-form deploy guide
  STEPS.md                  this checklist
  env.production.example    every Vercel env var with explanation
api/
  index.py                  Vercel Python serverless entry — wraps FastAPI
  requirements.txt          slim deps (no weasyprint / no elasticsearch / etc.)
scripts/
  init-supabase.sh          one-shot DB migrate + seed runner
vercel.json                 monorepo build + /api rewrite config
```

## Rollback

To remove the free-tier deploy entirely:
- Vercel → Project → Settings → Delete Project. No charges, no DNS to clean up.
- Supabase → Project → Settings → General → Pause / Delete.
- Upstash → Database → Delete.
- API keys: revoke from each provider's console.

The git branch with these files is independent — keep or delete as you like; nothing in `apps/api` or `apps/web` was modified, so reverting is `git rm vercel.json api deploy scripts/init-supabase.sh`.
