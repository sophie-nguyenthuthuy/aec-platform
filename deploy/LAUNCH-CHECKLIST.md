# Launch checklist — AEC Platform production go-live

T-30 → T-0 → T+7 checklist for taking a fresh deploy to "customers
can sign up and pay" status. Pair with `scripts/verify_deployment.sh`
for the automated portion.

---

## T-30 days — infrastructure + accounts

### Cloud + DNS

- [ ] Domain `aec-platform.vn` registered + DNSSEC enabled
- [ ] Cloudflare zone configured + DNS records for:
  - [ ] `aec-platform.vn` → Vercel
  - [ ] `app.aec-platform.vn` → Vercel
  - [ ] `api.aec-platform.vn` → Railway
- [ ] Email DNS (SPF + DKIM + DMARC) on `aec-platform.vn`:
  - [ ] SPF: `v=spf1 include:_spf.mx.cloudflare.net include:resend.com ~all`
  - [ ] DKIM: Resend dashboard → Settings → DNS → copy the 3 CNAME records
  - [ ] DMARC: `v=DMARC1; p=quarantine; rua=mailto:dmarc@aec-platform.vn`

### Vercel project

- [ ] `aec-platform-web` project linked to GitHub repo
- [ ] Production branch: `main`
- [ ] Environment variables set (Vercel → Settings → Env):
  - [ ] `NEXT_PUBLIC_SUPABASE_URL`
  - [ ] `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
  - [ ] `NEXT_PUBLIC_API_URL=https://api.aec-platform.vn`
  - [ ] `NEXT_PUBLIC_AEC_REALTIME=on`
- [ ] Domain alias `app.aec-platform.vn` attached + verified

### Railway services

- [ ] `aec-platform-api` service deployed
- [ ] `aec-platform-worker` service deployed (separate config —
      see `deploy/RAILWAY-WORKER.md`)
- [ ] Environment variables (api + worker, both):
  - [ ] `DATABASE_URL` (Supabase transaction pooler)
  - [ ] `DATABASE_URL_ADMIN` (Supabase direct connection)
  - [ ] `DATABASE_URL_SYNC` (Supabase direct, sync driver — alembic uses)
  - [ ] `REDIS_URL` (Upstash)
  - [ ] `SUPABASE_URL`
  - [ ] `SUPABASE_JWT_SECRET`
  - [ ] `GOOGLE_API_KEY` (Gemini)
  - [ ] `AEC_ENV=production`
- [ ] Custom start command (api): `alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8080`
- [ ] Custom start command (worker): `arq workers.queue.WorkerSettings`
- [ ] Domain `api.aec-platform.vn` aliased to api service

### Supabase

- [ ] Project created in **Singapore region**
- [ ] Database password rotated + saved to password manager
- [ ] Alembic migrations applied (run `scripts/init-supabase.sh`)
- [ ] Auth → Providers → enabled:
  - [ ] Email
  - [ ] Google (Client ID + Secret from Google Cloud OAuth client)
  - [ ] Microsoft (Application ID + Secret from Entra app)
- [ ] Auth → URL Configuration → redirect URLs include:
  - [ ] `https://app.aec-platform.vn/auth/callback`
  - [ ] `https://app.aec-platform.vn/auth/callback?next=/**`
- [ ] RLS enabled on every tenant-scoped table (verify via
      `SELECT relname FROM pg_class WHERE relrowsecurity = false;`)

### MinIO (Enterprise only, skip for SaaS-only)

- [ ] MinIO server provisioned (S3 alternative; AWS S3 is the
      SaaS default)
- [ ] Bucket `aec-platform-files` created
- [ ] Lifecycle policy: drawings older than 5 years → glacier
- [ ] Cross-region replication to Tokyo (matches DB failover topology)

### Stripe

- [ ] Stripe account verified (business identity + bank account)
- [ ] Products created in dashboard:
  - [ ] "Chuyên nghiệp" monthly USD ($199/month)
  - [ ] "Chuyên nghiệp" annual USD ($1990/year, 17% discount)
- [ ] Webhook endpoint `https://api.aec-platform.vn/api/v1/billing/webhooks/stripe`
      added with events:
  - [ ] `checkout.session.completed`
  - [ ] `customer.subscription.deleted`
  - [ ] `invoice.payment_failed`
- [ ] Webhook signing secret copied → Railway env `STRIPE_WEBHOOK_SECRET`
- [ ] `STRIPE_SECRET_KEY` (live mode) → Railway env on both services

### VietQR / Bank

- [ ] Company bank account opened (Vietcombank / BIDV recommended)
- [ ] Statement export feed verified (manual download monthly OK)
- [ ] `BILLING_BANK_NAME`, `BILLING_BANK_ACCOUNT`, `BILLING_BANK_HOLDER`
      env vars set

### Resend

- [ ] Resend account signed up + domain `aec-platform.vn` verified
- [ ] API key generated (live, not test) → `RESEND_API_KEY` on worker
- [ ] `RESEND_FROM=AEC Platform <no-reply@aec-platform.vn>`
- [ ] Reply-to address: `support@aec-platform.vn`

### Sentry

- [ ] Project `aec-platform` created
- [ ] DSN copied → `SENTRY_DSN` on api + worker + web (`NEXT_PUBLIC_SENTRY_DSN`)
- [ ] Alert rule: "New issue in production with sev:major" → email
      `ops@aec-platform.vn`
- [ ] Release tracking: `SENTRY_RELEASE` auto-set from
      `RAILWAY_GIT_COMMIT_SHA`

### Upstash Redis

- [ ] Database created in Singapore region
- [ ] TLS connection string → `REDIS_URL` on api + worker
- [ ] Max memory policy: `allkeys-lru` (cache eviction)
- [ ] Persistence: AOF every second (default)

---

## T-7 days — pre-launch QA

### Smoke test sequence

Run all of these in production:

- [ ] `./scripts/verify_deployment.sh` returns 0 (all checks pass)
- [ ] Sign up new account via email → confirm email link → reach
      `/onboarding`
- [ ] Onboarding wizard: create org → pick modules → invite 1 email →
      seed demo data → land at `/inbox`
- [ ] Click through every module sidebar entry → no 404 / 500
- [ ] CodeGuard: run a scan against seeded demo project → see findings
- [ ] Drawbridge: upload 1 PDF → wait for "Sẵn sàng" → ask Q&A
- [ ] Billing: click "Chuyển khoản VietQR" → see modal with bank info
- [ ] Billing: click "Thanh toán bằng thẻ (USD)" → redirect to Stripe
      checkout (don't complete)
- [ ] SSO Google: click "Đăng nhập với Google Workspace" → consent → land at `/inbox`
- [ ] SSO Microsoft: same flow

### Eval gate

- [ ] `make eval-all` reports ≥80% CodeGuard accuracy
- [ ] `make eval-all` reports ≥70% Drawbridge accuracy
- [ ] No "missing rate" warnings in `apps/ml/eval_results/`

### Performance gate

- [ ] `/health` p99 < 50ms (10 concurrent VUs, 60s soak)
- [ ] `/api/v1/me/orgs` p99 < 100ms (cached path)
- [ ] `/api/v1/codeguard/scan` p99 < 15s (LLM-bound; warm Redis cache)

### Security gate

- [ ] Tenant isolation smoke: create 2 orgs, try cross-org reads via
      cURL with wrong `X-Org-ID` header → get 403/404
- [ ] Run `apps/api/tests/test_*_rls.py` integration suite
- [ ] Penetration test results reviewed (if completed)
- [ ] Secrets audit: no `sk_live_*` / `re_*` / `AIza*` in git history
      (`gitleaks detect`)

---

## T-0 — launch day

### Pre-launch (08:00 ICT)

- [ ] Coffee. No deploys today. Quiet morning to focus on real users.
- [ ] Status page green at `status.aec-platform.vn`
- [ ] On-call rotation set: ops@ phone + Slack alert
- [ ] Customer success answering inbox `support@aec-platform.vn`

### Launch (10:00 ICT)

- [ ] Send launch email to waitlist (if any)
- [ ] Post LinkedIn launch post from sophie's profile + AEC company page
- [ ] Pin tweet/Twitter X post linking to demo video
- [ ] Submit to relevant directories: Tools.zalo, ShareGroup VN, …

### First-hour monitoring (10:00-11:00)

Watch in real-time:

- [ ] Sentry: zero new issues. If issue spike → roll back via Vercel
      revert button + Railway service rollback.
- [ ] Better Stack logs: tail for 500s or repeated 401s.
- [ ] Stripe dashboard: webhook deliveries succeed (200 OK).
- [ ] Cloudflare analytics: traffic graph normal.

### Spike handling

If signup spike causes degradation:

1. Sentry "Workers queue depth high" alert fires → scale Railway worker
   service from 2 → 5 replicas via dashboard.
2. Postgres connection limit alert → check `pg_stat_activity` count;
   if near 200, increase Supabase plan or enable txn-mode pooler.
3. CodeGuard scan latency p99 > 30s → check Gemini quota in Google
   Cloud Console; usually self-heals after burst clears.

### End-of-day (18:00)

- [ ] Tally: signups today, demos booked, support emails received,
      VietQR transfer confirmations.
- [ ] Sentry top 5 issues triaged (close noise, file real bugs).
- [ ] Slack #aec-platform-launch summary post.

---

## T+7 — first week review

- [ ] Pull weekly metrics: WAU, signup → activation funnel, demo
      → POC conversion rate.
- [ ] Sentry trend chart: error rate by day. Should trend down or
      flat (not up).
- [ ] Compute infra cost burn rate vs revenue (gói Pro signups
      × 4.9M VNĐ).
- [ ] Customer interviews: pick 3 new signups, schedule 30-min calls
      asking "what worked / what didn't".
- [ ] Update `sales/PROSPECT-PROFILES.md` with learnings: which
      archetypes actually convert, which budget signals were
      reliable.
- [ ] Plan week 2 outbound cadence based on actual demo book rate.

---

## Rollback procedure

If launch goes sideways (sustained 5xx rate >5% or sev-1 security issue):

1. **Web rollback** (Vercel): Settings → Deployments → previous good
   → "Promote to production". <1 min.
2. **API rollback** (Railway): Deployments → previous successful
   build → "Rollback". 1-3 min.
3. **Worker rollback** (Railway): same flow.
4. **DB rollback** (Supabase): point-in-time restore via Backups
   tab → pick timestamp before incident. Acknowledged risk: any
   data written after that timestamp is lost.
5. **Communicate**: status page updates within 5 min of any rollback.

Don't rollback for:
- Single-customer cosmetic bug (file ticket + hotfix forward).
- Sentry noise from misconfigured 3rd-party integration (filter the
  error class instead).

Do rollback for:
- Sustained 5xx rate >5%.
- Data exposure between tenants (RLS leak).
- Auth pathway broken (login fails for all).
- Critical pricing/billing bug (Stripe overcharge, VietQR wrong reference).

---

## Communication templates

### Status page incident — initial post

> **Investigating** · Mất kết nối API
>
> Chúng tôi đang điều tra báo cáo người dùng không truy cập được
> dashboard. Cập nhật mỗi 15 phút.
>
> Bắt đầu: **[HH:mm]** Giờ Việt Nam

### Status page incident — resolved

> **Resolved** · Mất kết nối API
>
> Sự cố đã được khắc phục. Nguyên nhân: **[1-line]**. RCA chi tiết
> sẽ được gửi đến khách hàng Enterprise qua email trong 24h.
>
> Bắt đầu: HH:mm · Kết thúc: HH:mm · Thời gian downtime: **[X
> phút]**

### Customer email — incident post-mortem (Enterprise only)

Sent within 24h of any sev-1 sự cố:

> Kính gửi anh/chị **[Customer]**,
>
> Vào hôm **[ngày]** từ **[HH:mm - HH:mm]** Giờ Việt Nam, AEC Platform
> đã có sự cố ảnh hưởng đến **[mô tả]**.
>
> **Nguyên nhân**: **[1 đoạn]**
> **Tác động đến anh/chị**: **[có thể cụ thể nếu có]**
> **Khắc phục**: **[1 đoạn]**
> **Phòng ngừa tái diễn**: **[3 bullets]**
>
> Chúng tôi xin lỗi vì sự bất tiện này. Theo SLA hợp đồng, **[X%]**
> credit sẽ được áp dụng cho hoá đơn tháng tới.
>
> Trân trọng,
> Đội Operations AEC Platform
