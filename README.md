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
# API (pytest + async, uses in-memory FakeAsyncSession)
make test-api

# Web E2E (Playwright, intercepts API calls — no backend needed)
cd apps/web
npm run test:e2e:install    # one-time Chromium download
npm run test:e2e

# Type + lint
pnpm typecheck
pnpm lint
```

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
