# Testing

Seven lanes, each with its own Make target. Use the Make target — it sets the env, picks the right working dir, and survives docker-compose port remapping.

## Quick reference

| What | When | Command | Needs |
| --- | --- | --- | --- |
| API unit | every commit | `make test-api` | Python only |
| API integration | before merging RLS / arq / scraper changes | `make test-api-integration` | docker compose up |
| ML pipelines | `apps/ml/*` changes | `make test-ml` | Python only |
| UI components | `packages/ui/*` changes | `make test-ui` | pnpm |
| Web lib + hooks | `apps/web/{lib,hooks}/*` changes | `make test-web-unit` | pnpm |
| Web E2E | UI / page changes | `make test-web` | pnpm + chromium |
| Worker tasks | Celery / beat changes | `pytest apps/worker/tests` | Python + celery |
| **Everything** | pre-push sanity | `make test` | pnpm + chromium |
| **Coverage everywhere** | quarterly / pre-release | `make test-cov` | pnpm + Python |

`make test` runs `test-api` + `test-ml` + `test-ui` + `test-web-unit` + `test-web`. The integration lane is opt-in because it needs the docker stack — running it implicitly would surprise people on a fresh clone.

`make test-cov` runs `test-api-cov` + `test-ml-cov` + `test-ui-cov` + `test-web-unit-cov` and **enforces the per-lane coverage floors** (a PR that drops any lane below its threshold red-gates). Use this before opening a PR if you've touched code that affects multiple lanes (e.g. a hook + the api route it calls).

## Coverage floors at a glance

Each `*-cov` target enforces a pinned floor — the contract is "don't go down meaningfully." Floors are at the current baseline minus ~1pt of headroom for v8 / pytest-cov run-to-run jitter.

| Lane | Lines | Branches | Functions | Where it's pinned |
| --- | --- | --- | --- | --- |
| `apps/api` | 80% | — | — | `apps/api/pyproject.toml` `[tool.coverage.report]` |
| `apps/ml` | 56% | — | — | `Makefile::test-ml-cov` (`--cov-fail-under=56`) |
| `packages/ui` | 25% | 69% | 47% | `packages/ui/vitest.config.ts` |
| `apps/web` | 12% | 57% | 32% | `apps/web/vitest.config.ts` |

## Bundle-size guard (`apps/web/.bundle-baseline.json`)

Separate from coverage but in the same spirit: the Node CI job compares the just-built `.next/static/{chunks,css}` against a checked-in baseline and fails if any section grew by more than **10%**. Catches the kind of regression that lands when someone pulls in a heavy library by accident (the full `lodash` bundle, all of `moment`, etc.) — exactly the class of bug coverage % can't see.

When a feature legitimately needs more bytes:

```bash
pnpm --filter @aec/web build       # regenerate .next/static
pnpm --filter @aec/web bundle:update  # rewrite the baseline
```

Commit the updated `apps/web/.bundle-baseline.json` in the same PR. CI's `Bundle size guard` step then passes against the new floor. The 10% threshold is per-section and total; the script (`apps/web/scripts/check-bundle-size.mjs`) writes `::error::` annotations naming any section that breaches.

## API unit lane (`make test-api`)

~620 tests under `apps/api/tests/`. Fully self-contained: every router is mounted onto a local `FastAPI()` with `require_auth` + `get_db` dependency-overridden to a `FakeAsyncSession`. ML pipelines are mocked at their public entry points (`apps.ml.pipelines.X.Y`) via `monkeypatch.setattr` or `sys.modules` stubs.

No Postgres, no Redis, no LLM, no S3 — all mocked. Runs in ~10 seconds.

The 12 `@pytest.mark.integration`-tagged tests are deselected (not skipped, so they don't show up as noise).

### Coverage (`make test-api-cov`)

`make test-api-cov` runs the same suite with `pytest-cov` measuring branch + line coverage over `apps/api/{core,db,middleware,models,routers,schemas,services,workers}`. Configuration in `apps/api/pyproject.toml::[tool.coverage.*]`. Reports:

- `apps/api/test-results/coverage.xml` — Cobertura XML, what CI uploads.
- `apps/api/test-results/coverage/index.html` — clickable HTML, easiest to triage gaps with.
- terminal — files with <100% coverage and the missing line numbers (`skip_covered = true` keeps the noise down).

CI runs the full suite (`--integration -q --cov`) on every PR; coverage XML is uploaded as part of the `pytest-results` artifact on failure. **Baseline: 78% line+branch over 619 tests**. Top gaps to attack first (all `services/`):

- `invitation_email.py` 0%, `price_alerts.py` 0%, `webhooks.py` 0% — never exercised by any test.
- `winwork.py` 30%, `price_scrapers/hcmc.py` 24%, `mailer.py` 40% — partial.

Pin `--cov-fail-under=78` in `[tool.coverage.report]` once the three 0%-covered services have test coverage. Doing it today would gate on a baseline that already includes 0%-covered files; the floor would just match where we are.

## API integration lane (`make test-api-integration`)

The 12 tests that hit a live Postgres + Redis. Covers:

- **`test_costpulse_rls`** — `SET LOCAL ROLE aec_app` and assert RLS policies block cross-tenant reads. The `aec` dev superuser has `BYPASSRLS`, so testing as `aec` would silently no-op every policy.
- **`test_costpulse_pipeline_openai`** — full LangGraph + SQLAlchemy pipeline against real DB; OpenAI is faked by `_FakeLLM`.
- **`test_price_scrapers_writer`** — exercises real `ON CONFLICT` upsert SQL.
- **`test_admin_session_factory`** — proves `SessionFactory` (aec_app, NOBYPASSRLS) sees less than `AdminSessionFactory` (aec, BYPASSRLS). Drift here would silently break every cross-tenant batch job.
- **`test_e2e_arq`** — enqueue → real Redis → real arq worker → real Postgres, end-to-end.

The Make recipe runs `docker compose up -d postgres redis`, applies migrations (which provisions `aec_app` via 0010), then derives the host ports from `docker compose port` — so a developer-local `docker-compose.override.yml` remapping Postgres from `5438` to `5437` (because of port collisions) just works. No magic numbers in the env vars.

CI runs this same lane on every PR (`.github/workflows/ci.yml::python-api`). The Postgres + Redis service containers are pre-wired; the env vars in the workflow mirror the Make recipe.

## ML pipelines lane (`make test-ml`)

~155 tests across 23 spec files in `apps/ml/tests/`. Covers the LangGraph CodeGuard pipeline (query + scan + retrieval + telemetry + abstain logic), the WinWork proposal pipeline, and the daily-log + pulse-client report generators. Self-contained — Anthropic + OpenAI clients are mocked via `monkeypatch.setattr` against the module-level `_llm()` factory; the pgvector retrieval path uses a SQLite-backed fake; the schema-walking tests stub `AsyncSession` directly.

The Tier 4 quality eval (`test_codeguard_quality_eval.py`) is excluded by default — it burns real OpenAI/Anthropic credit (~25-40¢/run). Run it via `make eval-codeguard` when intentional; see `docs/codeguard.md` §10.

`make test-ml-cov` adds `--cov=apps/ml` measurement. **Baseline 55%** as of 2026-05-02. Top remaining gaps tracked in [`docs/ml-coverage-audit.md`](./ml-coverage-audit.md):

- `apps/ml/server.py` (Ray Serve entrypoint) — intentionally untested at unit level; covered by integration only.
- The non-pure `_node_*` functions in `winwork.py` are now at 61% (round 4 of 2026-05-02 added DB + LLM-mock coverage); the remaining 39% is the orchestration glue (`_build_graph`, `run_proposal_pipeline`).

CI runs this lane on every PR (`.github/workflows/ci.yml::python-api`, separate step from `apps/api`).

## UI component lane (`make test-ui`)

~80 tests across 10 specs in `packages/ui/**/__tests__/` (drawbridge, pulse, handover, codeguard so far). Vitest + React Testing Library running in jsdom. **No browser, no dev server, no API mocks** — the lane finishes in ~2 seconds.

The split with the Web E2E lane is intentional:

- **Vitest** covers prop / state / handler-invocation logic in isolation. Easier to assert on with `vi.fn()` than to round-trip through Playwright + `page.route` + a server-rendered page.
- **Playwright** covers full-page wiring: TanStack Query state, route navigation, form submission against intercepted API endpoints. Things you can only see in a real browser.

Test files live alongside their subject under `__tests__/<Name>.test.tsx` — same convention as `apps/api/tests/test_<router>.py`. The Vitest config (`packages/ui/vitest.config.ts`) forces `esbuild.jsx: "automatic"` so test files don't need `import React`; the repo's tsconfig sets `jsx: "preserve"` (Next handles the transform downstream) which would otherwise leave JSX untransformed at test time.

The `pnpm test` script runs `tsc --noEmit && vitest run` so a TS error in any test file (or in the source it imports from) red-gates before Vitest starts. The first time this caught a bug was a hook test using a stale `ProposalGenerateRequest` shape — would have shipped silently otherwise.

CI runs this lane via `:coverage` (slower, but enforces the threshold floor) in the Node job, between Lint and "Build web". See `.github/workflows/ci.yml::node`.

## Web lib + hooks lane (`make test-web-unit`)

**85 tests across 18 specs** in `apps/web/{lib,hooks}/__tests__/` (as of 2026-05-02 round 3). Two slices:

- `lib/__tests__/` — both fetch wrappers (`apiFetch`, `apiRequest`, `apiRequestWithMeta`) — URL building, header merging, body shapes, error envelope unwrap. ~25 tests.
- `hooks/__tests__/` — TanStack Query hook contract tests for the highest-mutation surface area: `usePriceAlert` (query-not-body bug regression), `useDrawbridgeQuery`, `useExtract`, `useToggleWatch`, `useConflicts`, `useUploadDocument` (FormData multipart), `useUploadDrawing`, `useGenerateProposal`, `useCodeguardScan`, `useGenerateRFI`, `useAnswerRFI`, plus the list-query hooks (`useDocuments`, `useProposals`, `useTenders`, `usePackages`, `useEstimates`). Each tests the URL/method/payload shape against a mocked global `fetch`. ~60 tests.

What the contract pins:

- **URL construction** — relative paths join `NEXT_PUBLIC_API_URL`; absolute paths pass through; `query`/`params` become search-string entries; `null` and `undefined` values are dropped (not stringified to `"null"` / `"undefined"`).
- **Headers** — `Authorization: Bearer <token>` always present; `X-Org-ID` always set in `apiFetch`, optional in `api-client.ts` (the public RFQ supplier portal is anonymous).
- **Body shapes** — `body: undefined` → no body sent (critical for query-only POSTs like `usePriceAlert`); explicit `body: null` is JSON-stringified to `"null"` (documented behaviour, pinned by test).
- **Error envelope** — non-2xx → `ApiError` with `status` / `code` / `message` / `field` from `errors[0]`, falling back to `res.statusText` when the body is empty or non-JSON.

Why this is a separate lane from the UI components: Vitest in jsdom can't faithfully model Next's server-side request scope (cookies/headers/middleware). Library helpers that don't depend on that scope go here; full-page workflows go through Playwright. The `apps/web/vitest.config.ts` `exclude` list keeps the Playwright suite from being picked up by Vitest.

CI runs this lane in the Node job, right after the UI component lane.

## Web E2E lane (`make test-web`)

80 tests across 28 Playwright specs under `apps/web/tests/e2e/` — covers every dashboard module: Drawbridge (8 specs), CodeGuard, Pulse Kanban, Projects (incl. detail with all 11 module roll-ups), Schedule, WinWork, CostPulse, SiteEye, BidRadar, Handover, DailyLog.

Each spec intercepts API calls with `page.route()` — there's no API backend running. The Playwright config boots `next dev --port 3101` itself (port 3100 is held by an unrelated dev container on at least one workstation).

### Auth bypass

The Supabase auth middleware (`apps/web/middleware.ts`) and the layout's Supabase session pull (`apps/web/app/layout.tsx`) both honour an `E2E_BYPASS_AUTH=1` env var that the Playwright config sets in `webServer.env`. With that flag, the middleware skips its session check and the layout injects a deterministic fake session — so specs can exercise authenticated pages without provisioning a real Supabase project. Production never sets this flag.

Running locally:

```bash
make test-web                                # headless
pnpm --filter @aec/web exec playwright test --ui  # interactive
```

CI uploads `apps/web/test-results/` (traces + screenshots from retries) on failure as the `playwright-traces` artifact.

## Worker lane (`pytest apps/worker/tests`)

5 tests under `apps/worker/tests/` exercising the Celery glue in `apps/worker/tasks.py`:

- The 3 BIDRADAR tasks (`bidradar_scrape_source`, `bidradar_scrape_all` fan-out, `bidradar_weekly_digest`) — `services.bidradar_jobs.*` is mocked at the import boundary; we verify wiring + retry semantics.
- A **beat-schedule drift detector** that asserts every `app.conf.beat_schedule` entry points at a task name actually registered on `app.tasks`. Without this, a typo or rename in the schedule would let the scheduler tick forever, logging "received unknown task" to /dev/null.

Skipped: the 3 trivial stubs (`send_proposal_email`, `process_upload`, `backfill_embeddings`) which are literal log + return statements.

## Adding tests

| Adding a... | Pattern | Example |
| --- | --- | --- |
| Router test | mock router's external boundary (S3 / pipelines) | `tests/test_drawbridge_router.py` |
| Service test | mock at the SQL boundary | `tests/test_drawbridge_queue.py` |
| Pipeline test | tag with `@pytest.mark.integration` if it needs DB | `tests/test_costpulse_pipeline_openai.py` |
| Web page test | `page.route(...)` + `getByRole`/`getByText` | `apps/web/tests/e2e/drawbridge-documents.spec.ts` |

### Router tests gotcha — dual-import sys.path

`apps/api/tests/conftest.py` puts both `apps/api/` and the repo root on `sys.path`, so `workers.queue` and `apps.api.workers.queue` resolve to **two distinct `sys.modules` entries**. If your SUT does `from workers.queue import get_pool` and your test patches `apps.api.workers.queue.get_pool`, the patch lands on the wrong module and the real function runs against real Redis. Match the import path, or stub both in `sys.modules` (see `tests/test_drawbridge_queue.py::test_drawbridge_ingest_job_forwards_to_pipeline`).

## ML pipeline coverage gaps

`apps/ml/pipelines/` has 14 pipeline modules. Direct ml-level unit-test coverage as of this writing:

| Pipeline | Direct tests | Notes |
| --- | --- | --- |
| `codeguard.py` | ✅ 11 tests | Heaviest coverage (abstain, citation grounding, hybrid search, retrieval, scan stream, telemetry, etc.) |
| `codeguard_ingest.py` | ✅ 1 test | Parser test |
| `schedulepilot.py` | ✅ 1 test | CPM math |
| `siteeye.py` | ✅ 2 tests | DailyLog sync + weekly-report BoQ attach |
| `dailylog.py` | ✅ 1 test | `aggregate_patterns` rollup math |
| `pulse.py` | ❌ — | Tested indirectly via `apps/api/tests/test_pulse_router.py` mocks |
| `costpulse.py` | ❌ — | Tested indirectly via router + integration `test_costpulse_pipeline_openai.py` |
| `winwork.py` | ❌ — | Tested indirectly via router |
| `handover.py` | ❌ — | Tested indirectly via router |
| `bidradar.py` | ❌ — | Tested indirectly via router + worker tasks |
| `drawbridge.py` | ❌ — | Tested indirectly via router |
| `rfi.py` | ❌ — | Tested indirectly via router |
| `changeorder.py` | ❌ — | Tested indirectly via router |
| `serve/siteeye_safety.py` | ❌ — | Ray Serve handler; routed-tested in api |

The "indirect" pipelines have private helper functions (sorting, dedup, prompt building, JSON parsing) that aren't exercised against their inputs at the ml level. Adding focused unit tests for those — pattern is `apps/ml/tests/test_dailylog_patterns.py` — is a known follow-up.

## CI artifacts

| Lane | On failure | Always |
| --- | --- | --- |
| API | `pytest-results` (junit.xml) | — |
| Web | `playwright-traces` (trace.zip + screenshots) | — |
| Security | — | `security-audit` (pnpm + pip-audit JSON, 30 days) |

The `security` job runs on every PR. The pnpm leg is **gated on critical**: `pnpm audit --prod --audit-level critical` red-gates the PR if any new critical advisory enters the dependency tree. 0 criticals today (the Next.js middleware-auth bypass GHSA-f82v-jwr5-mffw was patched by bumping `next` 14.2.15 → 14.2.35). Three HIGH advisories remain — 1 is a `glob`-CLI vector that doesn't apply to library usage, 2 are Next.js DoS issues patched in 15.x. Ratcheting the gate to `--audit-level high` is the next step once the Next 15 migration lands — see [`docs/migrations/next-15.md`](./migrations/next-15.md) for the planned upgrade path.

The pip-audit leg is still **non-blocking** because pip-audit lacks a severity filter (all-or-nothing via `--strict`) and the langchain ecosystem ships advisories faster than we can triage them. The JSON report is uploaded on every run for review.

API and Web artifacts retained 7 days; Security retained 30. Download from the failed run's "Summary" page on GitHub.
