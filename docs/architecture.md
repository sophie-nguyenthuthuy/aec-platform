# Architecture Overview

This doc is the map for new contributors. Read it once, keep it open
on a second monitor while you code, and `Ctrl+F` it whenever you see
a module name you don't recognise.

## 1. Top-level shape

```
apps/
├── api/      FastAPI service. All HTTP traffic, all DB writes.
├── ml/       Pipelines: LangGraph, OCR, Ray Serve client, etc.
├── worker/   Test scaffolding for arq workers; the workers
│             themselves run from apps/api/workers/queue.py.
└── web/      Next.js dashboard. Calls api over HTTP.
packages/
├── types/    Shared TypeScript shapes. The wire format between
│             web and api.
└── ui/       React component library. Per-module subdirs:
              ui/costpulse/, ui/codeguard/, etc.
docs/         Module-specific docs (this file's siblings).
infra/        Docker, terraform, k8s manifests.
```

The api process imports from `apps/ml` for pipeline code (LLM-driven
extraction, weekly-report rendering, OCR). The ml process is NOT a
separate service — it's a Python package the api loads in. The
"separation" exists so the dependency graph stays one-way: ml never
imports from api.

## 2. The 16 product modules

Each module has its own router (`apps/api/routers/{module}.py`),
SQLAlchemy model file (`models/{module}.py`), schema module
(`schemas/{module}.py`), and (usually) ML pipeline
(`apps/ml/pipelines/{module}.py`). UI lives in
`apps/web/app/(dashboard)/{module}/` + `packages/ui/{module}/`.

| Module | Stage | What it does | Tables |
|---|---|---|---|
| **WinWork** | Bidding | Proposal generation; fee benchmarks; quick fee calculator. | `proposals`, `proposal_templates`, `fee_benchmarks` |
| **BidRadar** | Bidding | Tender feed scrape (`mua-sam-cong.gov.vn`, etc.) → match against firm profile → digest emails. | `tenders`, `firm_profiles`, `tender_matches`, `tender_digests` |
| **CostPulse** | Bidding | Estimate pipeline: AI BOQ from brief / from drawings. Material price catalogue + supplier directory + RFQ → public supplier portal → quote comparison + acceptance. | `estimates`, `boq_items`, `material_prices`, `suppliers`, `rfqs`, `price_alerts` |
| **CodeGuard** | Design | RAG over QCVN/TCVN. Q&A endpoint, automated scans against fire/accessibility/structure/zoning, permit checklists. | `regulations`, `regulation_chunks`, `compliance_checks`, `permit_checklists` |
| **Drawbridge** | Design | Document ingestion + RAG over drawings + RFIs. Conflict detection across drawings. | `document_sets`, `documents`, `document_chunks`, `conflicts`, `rfis` |
| **SchedulePilot** | Construction | Project schedule + dependencies + risk assessments. | `schedules`, `schedule_activities`, `schedule_dependencies`, `schedule_risk_assessments` |
| **Pulse** | Construction | Tasks, milestones, change orders, meeting notes, client reports. The "PM" surface. | `tasks`, `milestones`, `change_orders`, `meeting_notes`, `client_reports` |
| **SiteEye** | Construction | YOLOv8 safety detection on site photos + LLM progress narration → weekly reports (with BOQ PDF attached). | `site_visits`, `site_photos`, `progress_snapshots`, `safety_incidents`, `weekly_reports` |
| **DailyLog** | Construction | Site diary: manpower, equipment, observations. Auto-syncs from SiteEye safety incidents. | `daily_logs`, `daily_log_manpower`, `daily_log_equipment`, `daily_log_observations` |
| **Submittals** | Construction | Submittal review workflow + RFI response drafting via RAG over submittals. | `submittals`, `submittal_revisions`, `rfi_embeddings`, `rfi_response_drafts` |
| **ChangeOrder** | Construction | Change-order intake: line items, approvals, AI-detected candidates from project events. | `change_order_sources`, `change_order_line_items`, `change_order_approvals`, `change_order_candidates` |
| **Punchlist** | Construction → Handover | Punch-list items per project (typed: defects, missing work). Status transitions auto-stamp the corresponding `closeout_item`. | `punch_lists`, `punch_items` |
| **Handover** | Handover | Closeout packages: as-builts, O&M manuals, warranties, defects, sign-off. | `handover_packages`, `closeout_items`, `as_built_drawings`, `om_manuals`, `warranty_items`, `defects` |
| **Assistant** | Cross-cutting | Conversational assistant; threads + messages stored per-org. | `assistant_threads`, `assistant_messages` |

Plus three platform-level concerns that are NOT product modules but
shape every module's surface:

| Concern | Where it lives | What it does |
|---|---|---|
| **Identity & orgs** | `models.core.{Organization,User,OrgMember,Invitation,Project,File}` + `routers/me.py` + `routers/org.py` | Org-membership join, user provisioning on first Supabase login, org-switcher cookie, invite flow. |
| **Audit** | `models.audit.AuditEvent` + `routers/activity.py` | Cross-module activity log. Routers emit `record_audit_event()` on side-effecting calls; UI's `/activity` page consumes it. |
| **Cross-module ops** | `routers/admin.py`, `services/ops_alerts.py`, `services/price_scrapers/` | Scraper telemetry (`scraper_runs` table), drift email alerts, the probe tool. Distinct from per-vertical work because the data is global ops, not tenant-scoped. |

## 3. Cross-module dependencies

A few non-obvious "this thing imports that thing" relationships:

```
SiteEye.weekly_report
  ↓ imports
CostPulse.boq_io   (attaches the latest approved BOQ PDF as a
                    sidecar artefact on the weekly report)

CostPulse.rfq_dispatch
  ↓ uses
services.rfq_tokens   (mints supplier-portal JWTs)
  ↓ verified by
routers.public_rfq    (no-auth response endpoint)

DailyLog.daily_log_observations
  ↑ written by
SiteEye._create_safety_incidents   (syncs incidents to the daily log)

ChangeOrder.change_order_candidates
  ↑ written by
Pulse.detect_change_order_candidates   (heuristic flag from PM events)

CostPulse.material_prices
  ↑ written by
services.price_scrapers.run_scraper   (provincial DOC site scrapers)
  ↑ telemetry written to
core.scraper_runs   (drift monitoring; admin dashboard)
```

## 4. The two DB factories (RLS posture)

Single most important platform-wide invariant. Both factories live in
`db/session.py`:

* **`SessionFactory`** — binds to `aec_app` role (NOBYPASSRLS).
  Default for request handlers via `Depends(get_db)`. RLS policies
  fire; tenant isolation is enforced.

* **`AdminSessionFactory`** — binds to `aec` role (BYPASSRLS).
  ONLY for cross-tenant batch jobs (`weekly_report_cron`,
  `evaluate_price_alerts`, scraper telemetry) and global ops tables
  (`scraper_runs`).

The split was added in migration `0010_app_role.py` after we noticed
the dev `aec` role was a Postgres superuser, making RLS effectively
a no-op. See `docs/public-rfq-portal.md` §4 for an example of the
admin factory in legitimate use (the supplier portal's token IS the
auth — there's no JWT subject to map to an org).

`tests/test_rls_coverage.py` is the standing guard: it sweeps
`pg_tables` + `pg_policies` against the live DB and fails if any
`organization_id`-bearing table is missing RLS.

## 5. Auth & tenancy

```
Browser → middleware.ts (Supabase server client refreshes session)
       → app/layout.tsx (getUser + getSession; fetches /me/orgs)
       → Providers (seeds session into React via SessionCtx)
       ↓
Browser → fetch with `Authorization: Bearer <jwt>` + `X-Org-ID: <uuid>`
       → api middleware/auth.py::require_auth
         (PyJWKClient verifies Supabase ES256/EdDSA from JWKS;
          falls back to HS256 for tests via `supabase_jwt_secret`)
       → AuthContext { user_id, organization_id, role, email }
       → Depends(get_db) sets `app.current_org_id` GUC for RLS
       → router handler runs
```

The `/api/v1/public/rfq/...` prefix is the only no-auth surface — see
`docs/public-rfq-portal.md` for the JWT-as-token rationale.

## 6. Workers

`apps/api/workers/queue.py` defines `WorkerSettings` for arq. Functions
+ cron jobs:

| Job | Cron | What it does |
|---|---|---|
| `photo_analysis_job` | (on-demand) | Per-photo LangGraph: safety + progress + describe |
| `weekly_report_job` | weekly_report_cron, Mon 06:00 UTC | One per (org, project) with site_photo activity |
| `weekly_report_cron` | Mon 06:00 UTC | Discovery: scans for projects with activity, fans out `weekly_report_job` |
| `rfq_dispatch_job` | (on-demand) | Per-RFQ: render email per supplier, send, record state |
| `retry_bounced_rfqs_cron` | hourly :15 | Re-enqueue dispatch for RFQs with bounced slots (cap: 5 attempts/slot) |
| `price_alerts_evaluate_job` | nightly 22:00 UTC | Walk price_alerts, compare against latest material_prices, fire alert email on threshold |
| `drawbridge_ingest_job` | (on-demand) | Document chunking + embedding for RAG |
| `scrape_prices_job` | (per-slug, on-demand) | Run one provincial scraper |
| `scrape_all_prices_job` | 2nd of each month, 01:00 UTC | Fan-out one `scrape_prices_job` per registered slug |
| `daily_activity_digest_cron` | daily 00:00 UTC | Digest emails to users who watch ≥1 project |

## 7. Observability

`core/observability.py::setup_observability(app)` wires:
- Structured logging (json/pretty per `LOG_FORMAT`)
- Request-ID middleware (`X-Request-ID` echo + contextvar threading)
- Slow-query SQLAlchemy listener on both engines (threshold via `SLOW_QUERY_MS`)
- Sentry init (no-op when `SENTRY_DSN` empty)

Plus `OPS_ALERT_EMAILS` (comma-separated) drives email alerts for
events that need ops attention — drift-threshold breach is the only
caller today; future calls plug into `services.ops_alerts`.

## 8. Where to look first when…

| Question | Start here |
|---|---|
| "Why did this RFQ supplier never get an email?" | `services.rfq_dispatch._send_with_retry` + `rfqs.responses[].attempts` |
| "Why is the dashboard empty for this user?" | `middleware.auth.require_auth` + `app.current_org_id` GUC + `org_members` row |
| "Why did this scraper run produce 0 rows?" | `scraper_runs` row → `unmatched_sample` → `services.price_scrapers.normalizer._RULES` |
| "Why did the BOQ export render `?` instead of `ố`?" | `services.boq_io.pdf._ensure_unicode_fonts` — DejaVu must register |
| "Why does this estimate edit not persist?" | `_supersede_and_clone` forks a new id; the URL changed. Check the redirect. |
| "Why is the supplier-portal page 401-ing?" | Token's `aud != "rfq_response"`, or `supabase_jwt_secret` differs between dispatcher and api processes. See `test_e2e_public_rfq.py`. |
| "Why is RLS not isolating this tenant?" | Connecting as `aec` (BYPASSRLS) instead of `aec_app`. Check `DATABASE_URL` — the runtime URL must point at `aec_app`. |

## 9. Sibling docs

* [`docs/codeguard.md`](./codeguard.md) — RAG implementation, dim caps, hallucination guards.
* [`docs/costpulse-boq-io.md`](./costpulse-boq-io.md) — Excel/PDF I/O, column detection, decimal coercion.
* [`docs/public-rfq-portal.md`](./public-rfq-portal.md) — Supplier portal, signed-link flow, rate limiting, comparison view.
* [`docs/scraper-drift-monitoring.md`](./scraper-drift-monitoring.md) — `scraper_runs`, drift threshold, ops dashboard.
* [`docs/testing.md`](./testing.md) — Test taxonomy, integration lane, E2E gating.
