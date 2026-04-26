# Testing

Four lanes, four invocations. Use the Make target — it sets the env, picks the right working dir, and survives docker-compose port remapping.

## Quick reference

| What | When | Command | Needs |
| --- | --- | --- | --- |
| API unit | every commit | `make test-api` | Python only |
| API integration | before merging RLS / arq / scraper changes | `make test-api-integration` | docker compose up |
| Web E2E | UI changes | `make test-web` | pnpm + chromium |
| Everything | pre-push sanity | `make test` | both above (no integration) |

`make test` runs `test-api` + `test-web`. The integration lane is opt-in because it needs the docker stack — running it implicitly would surprise people on a fresh clone.

## API unit lane (`make test-api`)

230 tests under `apps/api/tests/`. Fully self-contained: every router is mounted onto a local `FastAPI()` with `require_auth` + `get_db` dependency-overridden to a `FakeAsyncSession`. ML pipelines are mocked at their public entry points (`apps.ml.pipelines.X.Y`) via `monkeypatch.setattr` or `sys.modules` stubs.

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

12 Playwright specs under `apps/web/tests/e2e/` covering Drawbridge (8 specs), CodeGuard, Pulse Kanban, Projects, Schedule, WinWork, CostPulse, SiteEye, BidRadar, Handover.

Each spec intercepts API calls with `page.route()` — there's no API backend running. The Playwright config boots `next dev --port 3101` itself (port 3100 is held by an unrelated dev container on at least one workstation).

Running locally:

```bash
make test-web                                # headless
pnpm --filter @aec/web exec playwright test --ui  # interactive
```

CI uploads `apps/web/test-results/` (traces + screenshots from retries) on failure as the `playwright-traces` artifact.

## Adding tests

| Adding a... | Pattern | Example |
| --- | --- | --- |
| Router test | mock router's external boundary (S3 / pipelines) | `tests/test_drawbridge_router.py` |
| Service test | mock at the SQL boundary | `tests/test_drawbridge_queue.py` |
| Pipeline test | tag with `@pytest.mark.integration` if it needs DB | `tests/test_costpulse_pipeline_openai.py` |
| Web page test | `page.route(...)` + `getByRole`/`getByText` | `apps/web/tests/e2e/drawbridge-documents.spec.ts` |

### Router tests gotcha — dual-import sys.path

`apps/api/tests/conftest.py` puts both `apps/api/` and the repo root on `sys.path`, so `workers.queue` and `apps.api.workers.queue` resolve to **two distinct `sys.modules` entries**. If your SUT does `from workers.queue import get_pool` and your test patches `apps.api.workers.queue.get_pool`, the patch lands on the wrong module and the real function runs against real Redis. Match the import path, or stub both in `sys.modules` (see `tests/test_drawbridge_queue.py::test_drawbridge_ingest_job_forwards_to_pipeline`).

## CI artifacts

| Lane | On failure |
| --- | --- |
| API | `pytest-results` (junit.xml) |
| Web | `playwright-traces` (trace.zip + screenshots) |

Both retained 7 days. Download from the failed run's "Summary" page on GitHub.
