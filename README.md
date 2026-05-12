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
| 9 | **PermitFlow** | `permitflow` | VN permit chain: chủ trương đầu tư → quy hoạch 1/500 → thẩm định TKCS → GPXD → nghiệm thu PCCC. Stage state-machine, ministry-specific submission packs, expiry/lapse alerts. |
| 10 | **NghieThu** | `nghiemthu` | Statutory acceptance (BBNT) per NĐ 06/2021/NĐ-CP. Công việc / giai đoạn / hoàn thành with CĐT–TVGS–NT signoff matrix, photo + drawing evidence, finalize gate. |
| 11 | **ThanhToan** | `thanhtoan` | Monthly progress payment claims (hồ sơ thanh toán giai đoạn). VAT 8/10% + retention 5% + TNDN tạm thu 1% computed automatically; CĐT–TVGS signoff lane; cross-period cumulative views. |
| 12 | **PCCC** | `pccc` | Fire-safety certification per QCVN 06:2022/BXD + NĐ 136/2020. PC07 design/acceptance round-trip, QCVN 06 checklist seed, on-site inspection rounds with auto-cascade to cert status, 5-year expiry alerts. |
| 13 | **InvoiceVN** | `einvoice` | HĐĐT issue/receive per NĐ 123/2020 + TT 78/2021. Server-computed VAT breakdown across 0/5/8/10% rates, MST format + GDT-status cache, GDT submission lifecycle + accept-reject callback, 24h cancellation window. |
| 14 | **LotusEdge** | `greenmark` | VGBC LOTUS + IFC EDGE green-building scoring. Per-credit catalog seeded from VGBC v3 / EDGE templates, per-category breakdown, gap-to-next-level engine recommends highest-points credits to push the score across the next threshold. |
| 15 | **BondLine** | `bondline` | VN bank-issued bonds (bảo lãnh dự thầu / thực hiện / tạm ứng / bảo hành) per Luật Đấu thầu 2023 + NĐ 24/2024. Bank-code allow-list (VCB/BIDV/TCB/…), claim workflow with default-call auto-flips, coverage-below-contract + 14/30/60-day expiry alerts. |
| 16 | **WorkforceVN** | `workforce` | Worker manifest, ATLĐ training (NĐ 44/2016 — 6 groups, 2y/3y renewal cycles), BHXH/BHYT/BHTN enrollment with monthly contribution math (17.5/8/3/1.5/1/1 + 2% KPCĐ), foreign worker permits per NĐ 152/2020, project assignments + compliance alerts. |

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
