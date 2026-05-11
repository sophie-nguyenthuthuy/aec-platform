# AEC Platform

AI-powered platform for Architecture, Engineering & Construction — a Vietnam-first
SaaS that helps project teams win work, estimate cost, monitor sites, track progress,
check code compliance, automate drawing QA, and hand over assets to clients.

## Modules

| # | Module | Slug | What it does |
|---|--------|------|--------------|
| 1 | **BidRadar** | `bidradar` | Scrapes VN procurement portals; AI-filters RFPs against firm capability. |
| 2 | **WinWork** | `winwork` | Proposal & fee-letter authoring, templated with firm style. |
| 3 | **CostPulse** | `costpulse` | BoQ estimation, live material-price intel, RFQ to verified suppliers. |
| 4 | **SiteEye** | `siteeye` | Daily site photos → AI progress%, safety incident detection, weekly reports. |
| 5 | **CodeGuard** | `codeguard` | Q&A over Vietnamese building codes (QCVN) with pgvector + BM25 hybrid retrieval. |
| 6 | **ProjectPulse** | `pulse` | Task Kanban, milestones, change orders, meeting notes → AI client reports (HTML + PDF). |
| 7 | **Drawbridge** | `drawbridge` | Drawing-set Q&A and markup compliance — pgvector HNSW over drawing text. |
| 8 | **Handover** | `handover` | Client-facing handover package: O&M manuals, warranties, as-builts. |
| 9 | **SchedulePilot** | `schedulepilot` | CPM scheduling, baseline + actual comparison, what-if delay simulation. |
| 10 | **Submittals** | `submittals` | Materials/sample approval workflow between contractor + supervising consultant. |
| 11 | **DailyLog** | `dailylog` | Site-diary entries with photos + GPS + weather; one-click PDF export. |
| 12 | **ChangeOrder** | `changeorder` | CO lifecycle (draft → submitted → approved/rejected → executed) with cost + schedule impact. |
| 13 | **Punchlist** | `punchlist` | Snag-list workflow from defect-found through verified-resolved; pre-handover. |
| 14 | **Activity** | `activity` | Cross-module event feed with SSE push; one source-of-truth for "what's happening on this project". |

## Monorepo layout

```
apps/
  api/        FastAPI + async SQLAlchemy 2.0 + Alembic  (Python 3.11+)
  ml/         LangChain + LangGraph pipelines, shared by api/ and worker/
  worker/     Background jobs (scrapers, ingest, periodic aggregation)
  web/        Next.js 14 App Router + TanStack Query + Tailwind + shadcn-style UI
packages/
  ui/         Shared React components (Kanban, charts, primitives)
  types/      Shared TypeScript types mirroring Pydantic schemas
infra/
  docker/     Local Postgres (with pgvector), Redis, Elasticsearch
  terraform/  (Optional) cloud IaC
.github/
  workflows/  CI: lint, typecheck, pytest, alembic-check
```

## Prerequisites

- **Docker** + **Docker Compose** (Postgres 16 with pgvector, Redis, Elasticsearch)
- **Python 3.11+** with `pip` or `uv`
- **Node 20+** and **pnpm 9+**
- (optional) **WeasyPrint** native deps (`libpango`, `libcairo`) for PDF report export
- (optional) **Anthropic** + **OpenAI** API keys for AI features

## Quick start

```bash
# 1. Infra
cp .env.example .env        # fill in secrets
docker compose up -d        # Postgres + Redis + Elasticsearch

# 2. API
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head        # migrate to head
uvicorn main:app --reload   # http://localhost:8000

# 3. Web
cd ../../
pnpm install
pnpm dev:web                # http://localhost:3000

# 4. (optional) Seed CodeGuard fixture
make seed-codeguard
```

## Running tests

```bash
make test                    # api unit + web E2E (no infra needed)
make test-api                # ~5s; FakeAsyncSession + mocked pipelines
make test-web                # Playwright; auto-boots `next dev` + Chromium
make test-api-integration    # opt-in lane; spins up Postgres+Redis from compose

# Type + lint
pnpm -r typecheck
pnpm -r lint
```

Four lanes total: api unit, api integration (12 tests gated on
`--integration`), web E2E (80 tests across 28 specs), and worker tasks.
See [`docs/testing.md`](./docs/testing.md) for what each lane covers,
how the integration env is wired, the dual-`sys.path` gotcha that bit
us in worker tests, and where to find CI artifacts on failure.

CI also runs a non-blocking **security** job that posts `pnpm audit` +
`pip-audit` JSON reports as artifacts on every PR (`.github/workflows/ci.yml::security`).

## Architecture highlights

- **Multi-tenant by default** — Postgres Row-Level Security scoped by `app.current_org_id`;
  the API middleware sets it per request from a JWT + `X-Org-ID` header.
- **Envelope response contract** — every endpoint returns `{data, meta, errors}`; the
  web client enforces this via a typed `apiFetch<T>()` helper.
- **AI pipelines are stateful graphs** — LangGraph `StateGraph`s under `apps/ml/pipelines/`;
  routers call them; tests mock at the pipeline entrypoint.
- **Optimistic UI** — TanStack Query `onMutate` + `onError` rollback for Kanban drag,
  CO approvals, task bulk edits.
- **Graceful degradation** — PDF export, site photos, budget integration all fall
  back to "skip this section" rather than 5xx'ing the caller.

## Partner / integrator surface

The platform exposes a public API for partner integrations (CRM, ERP, ETL).

- **REST API** — auth via per-org API keys, rate-limited per key, scoped by a closed
  vocabulary (`projects:read`, `defects:write`, `*`, etc). Test-mode keys route to a
  synthetic-data layer so partners can build end-to-end without polluting real data.
  Per-project allowlists scope keys to specific projects (migration `0039`).
  Idempotency-Key header for retry-safe writes.
- **Webhooks** — HMAC-SHA256 signed event delivery with exponential-backoff retry
  (1m → 5m → 30m → 2h → 12h → 6 attempts). Subscribe via
  `POST /api/v1/webhooks` with `event_types[]`. Cross-tenant ops surface at
  `/admin/webhook-deliveries` for platform-side triage.
- **Public docs at `/docs`** — `/docs/api` (auth, scopes, rate limits, errors,
  idempotency, sandbox mode), `/docs/webhooks` (signing, retries, dead-letter),
  `/docs/webhooks/events` (auto-rendered catalog of every event type with payload
  samples — pulled from `services/webhooks.EVENT_CATALOG`), `/docs/ops` (health
  probes, Prometheus scrape).
- **TypeScript SDK** at `packages/sdk` (`@aec/sdk`) — typed client auto-generated
  from the OpenAPI snapshot, with `AecClient` wrapper handling 429/5xx retries +
  envelope unwrap + `AecApiError` for typed catch blocks. CI gate
  (`drift-check.mjs`) ensures the SDK stays in sync with the snapshot.

## Surface contracts (rollback defense)

The codebase has historically suffered from an aggressive linter / reformat pass
that silently reverts router includes, dataclass fields, and migration-backed
columns mid-development. Two **surface-snapshot tests** pin the structural contract
so a revert fails CI rather than landing silently:

- `apps/api/tests/test_codeguard_surface_snapshot.py` — codeguard router routes,
  metric registry entries, cron registrations, retention policies.
- `apps/api/tests/test_integrator_surface_snapshot.py` — `Settings.metrics_token`,
  `AuthContext.api_key_mode/api_key_id/api_key_project_ids`, `mint_key(mode=,
  project_ids=)`, `KEY_MODES`, the ops/webhook-deliveries-admin/slack-deliveries/
  cron-admin routers being mounted, `WebhookDeliveryOut.subscription_id`, the
  `EVENT_CATALOG ⊆ _KNOWN_EVENT_TYPES` invariant, audit-log JOINs, the
  cron-telemetry decorator preserving `__name__`/`__doc__`, the `cron_runs`
  retention policy.

Both run on every PR via dedicated CI jobs (`codeguard-surface`, `integrator-surface`)
AND as pre-commit hooks via `.pre-commit-config.yaml` so a revert is caught at
`git commit` time, not mid-PR. When adding a new surface that's load-bearing for
the frontend or partners, extend the snapshot pattern — comments at the top of
each test file explain how.

## Admin surface

The dashboard's `/admin` hub is the platform-ops view (admin-role gated):

| Page | What |
|------|------|
| `/admin/api-usage` | Cross-org API key leaderboard + per-key drilldown with hour-bucketed sparkline |
| `/admin/webhook-deliveries` | Cross-tenant webhook outbox health; per-event-type rate; per-delivery payload + error drilldown |
| `/admin/slack-deliveries` | Platform-Slack-webhook telemetry per delivery kind |
| `/admin/crons` | Static cron registry + last-run telemetry per cron (success/failed/duration/error) |
| `/admin/scrapers` | Provincial bulletin scraper drift trends |
| `/admin/normalizer-rules` | DB-backed material-name regex rules merged on top of the in-code normaliser |

The "own router file per admin surface" pattern — `routers/slack_deliveries.py`,
`routers/webhook_deliveries_admin.py`, `routers/cron_admin.py` — is a deliberate
dodge of the rollback pattern that targets `routers/admin.py`. New cross-tenant
admin routes go in their own file.

## Development conventions

- **Commits**: conventional prefix (`feat(pulse):`, `fix(api):`, `test(web):`)
- **Python**: ruff + mypy strict; `from __future__ import annotations` in every module
- **TypeScript**: strict mode; no `any`; shared types live in `packages/types/`
- **Migrations**: Alembic linear history with a periodic merge-heads commit when
  modules grow in parallel

### Pre-push checklist

CI gates every push on lint + format + typecheck + tests. To avoid bouncing
off CI, run the **same** checks locally before pushing:

```bash
make hooks                                     # one-time: install pre-commit
ruff check apps/api apps/worker apps/ml        # lint
ruff format --check apps/api apps/worker apps/ml  # format
pnpm --filter @aec/web typecheck                # web typecheck
```

The `make hooks` install adds a git pre-commit hook that runs ruff +
ruff-format + basic file hygiene on every commit automatically — that
covers ~90% of the gates above without you having to remember.

For the remaining 10% (TypeScript, Playwright, pytest), run them
manually before push if you've changed anything in their territory.

> **Why this matters**: ruff and ruff-format are pinned in
> `apps/api/requirements-dev.txt` and `.pre-commit-config.yaml` to the
> same version CI installs. Skipping the hook locally means your push
> can land lint that CI rejects — and because CI's lint gate runs *before*
> the heavyweight test gates, you'll wait for the queue twice.

## License

[GNU AGPL-3.0](./LICENSE). You're free to read, fork, modify, and self-host this
code. If you run a modified version as a network-accessible service, AGPL §13
requires you to offer the modified source to your users. For commercial use that
needs different terms, please reach out.
