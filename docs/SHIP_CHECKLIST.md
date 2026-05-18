# Ship checklist — aec-platform

## 1. AI infrastructure (OSS, self-hosted)

- [ ] **LLM model tier**
  - Dev/CPU: `LLM_CHAT_MODEL=qwen2.5:7b-instruct` (~4 GB).
  - Production GPU: `LLM_CHAT_MODEL=qwen2.5:32b-instruct` (~20 GB).
  - Vision (drawbridge title-block): `LLM_VISION_MODEL=qwen2.5vl:7b` — GPU
    strongly recommended; CPU works but ~30 s per page.
- [ ] **Embedding model**: `nomic-embed-text` (768-dim, matches pgvector).
- [ ] **GPU host**: single L40S / A100 covers 32b chat + vl:7b vision +
      embeddings concurrently for ~50 active tenants.

## 2. Data pipelines (operator must arrange)

- [ ] **Bidradar tender feed**
  - Sign an access agreement with **DauThau.MOF.gov.vn** (national
    procurement portal) OR contract a scraping vendor with the right
    licence.
  - Configure `apps/ml/pipelines/bidradar.py` source URLs + per-source
    XPath. Schema: `services.tender_ingest`.

- [ ] **Pulse / weekly-report data** — pulls from Postgres tables in the
      `pulse` schema; no external dependency.

- [ ] **CodeGuard standards corpus** — shared with `tcvn-compliance-copilot`.
      Same TCVN/QCVN licensing concerns apply if you co-host.

## 3. Supabase + Auth

- [ ] **Supabase project** created (free tier OK for pilot, Pro for prod).
  - Set `SUPABASE_URL`, `SUPABASE_SECRET_KEY`.
  - Configure email-OTP + Google OAuth in Supabase dashboard.
- [ ] **JWT verification** — set `SUPABASE_JWT_SECRET` (legacy HS256) or
      leave `SUPABASE_URL` set for asymmetric verification.

## 4. Storage

- [ ] **MinIO** (self-hosted) OR **AWS S3 ap-southeast-1**.
  - Bucket: `aec-platform-files` with versioning.
  - Lifecycle: drawings → Glacier after 90 days, reports → Glacier after 1 year.
- [ ] **CDN** in front for the public-read report bucket (CloudFront / Bunny).

## 5. Observability + paging

- [ ] **OTEL collector** running (compose includes prometheus + grafana).
- [ ] **Sentry DSN** set (`SENTRY_DSN`).
- [ ] **PagerDuty / Slack** webhook for `vngpu_worker_ttft_seconds` SLO
      breaches if you reuse the vngpu-inference SLOs.

## 6. RLS verification

- [ ] **Migration `0010_app_role`** applied — splits `aec` (DDL/superuser)
      from `aec_app` (request-time, RLS-enforced).
- [ ] **Smoke test** `apps/api/tests/test_rls_*.py` green.

## 7. Smoke before release

```
make smoke PROJECT=aec-platform
cd apps/api && .venv/bin/pytest -q
```
