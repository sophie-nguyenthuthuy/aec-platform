# Testing

Five lanes, five invocations. Use the Make target — it sets the env, picks the right working dir, and survives docker-compose port remapping.

## Quick reference

| What | When | Command | Needs |
| --- | --- | --- | --- |
| API unit | every commit | `make test-api` | Python only |
| API integration | before merging RLS / arq / scraper changes | `make test-api-integration` | docker compose up |
| Web E2E | UI changes | `make test-web` | pnpm + chromium |
| Worker tasks | Celery / beat changes | `pytest apps/worker/tests` | Python + celery |
| Everything | pre-push sanity | `make test` | both above (no integration) |

`make test` runs `test-api` + `test-web`. The integration lane is opt-in because it needs the docker stack — running it implicitly would surprise people on a fresh clone.

## API unit lane (`make test-api`)

~340 tests under `apps/api/tests/`. Fully self-contained: every router is mounted onto a local `FastAPI()` with `require_auth` + `get_db` dependency-overridden to a `FakeAsyncSession`. ML pipelines are mocked at their public entry points (`apps.ml.pipelines.X.Y`) via `monkeypatch.setattr` or `sys.modules` stubs.

No Postgres, no Redis, no LLM, no S3 — all mocked. Runs in ~5 seconds.

The 12 `@pytest.mark.integration`-tagged tests are deselected (not skipped, so they don't show up as noise).

## API integration lane (`make test-api-integration`)

The 12 tests that hit a live Postgres + Redis. Covers:

- **`test_costpulse_rls`** — `SET LOCAL ROLE aec_app` and assert RLS policies block cross-tenant reads. The `aec` dev superuser has `BYPASSRLS`, so testing as `aec` would silently no-op every policy.
- **`test_costpulse_pipeline_openai`** — full LangGraph + SQLAlchemy pipeline against real DB; OpenAI is faked by `_FakeLLM`.
- **`test_price_scrapers_writer`** — exercises real `ON CONFLICT` upsert SQL.
- **`test_admin_session_factory`** — proves `SessionFactory` (aec_app, NOBYPASSRLS) sees less than `AdminSessionFactory` (aec, BYPASSRLS). Drift here would silently break every cross-tenant batch job.
- **`test_e2e_arq`** — enqueue → real Redis → real arq worker → real Postgres, end-to-end.

The Make recipe runs `docker compose up -d postgres redis`, applies migrations (which provisions `aec_app` via 0010), then derives the host ports from `docker compose port` — so a developer-local `docker-compose.override.yml` remapping Postgres from `5438` to `5437` (because of port collisions) just works. No magic numbers in the env vars.

CI runs this same lane on every PR (`.github/workflows/ci.yml::python-api`). The Postgres + Redis service containers are pre-wired; the env vars in the workflow mirror the Make recipe.

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

The `security` job runs on every PR and is currently **non-blocking** — `continue-on-error: true` plus per-step `|| true` so existing pile of advisories don't red CI. The Critical Next.js middleware-auth bypass (GHSA-f82v-jwr5-mffw) was patched by bumping `next` 14.2.15 → 14.2.35; once the rest of the High-severity backlog is cleared, drop the `|| true` and the `continue-on-error` to ratchet to gating. Recommend `--audit-level critical` as the first gate, not `high`.

API and Web artifacts retained 7 days; Security retained 30. Download from the failed run's "Summary" page on GitHub.
