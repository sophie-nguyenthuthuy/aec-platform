.PHONY: seed-codeguard seed-demo eval-codeguard test test-cov test-api test-api-cov test-api-integration test-api-integration-up test-ml test-ml-cov test-ui test-ui-cov test-web test-web-unit test-web-unit-cov hooks lint backfill-rfi-embeddings backfill-dailylog

# Install local pre-commit hooks. Run once per clone. After this, every
# `git commit` runs ruff check + ruff format + basic hygiene checks on
# staged files. Skips bigger-but-slower gates (typecheck, pytest, build) —
# those still run in CI.
hooks:
	pip install pre-commit
	pre-commit install

# Run all pre-commit hooks across the entire repo (not just staged files).
# Useful right after a big rebase or before a release tag.
lint:
	pre-commit run --all-files

# Runs the CODEGUARD ingest CLI against the committed QCVN excerpt so
# /api/v1/codeguard/query works end-to-end in a fresh dev environment
# without needing to source a real PDF.
#
# Requires: DATABASE_URL + OPENAI_API_KEY in the environment, and the
# 0005_codeguard migration applied.
seed-codeguard:
	PYTHONPATH=apps/api:apps/ml python -m pipelines.codeguard_ingest \
		--source apps/ml/fixtures/codeguard/qcvn_06_2022_excerpt.md \
		--code "QCVN 06:2022/BXD" \
		--country VN \
		--jurisdiction national \
		--category fire_safety \
		--effective 2022-10-25 \
		--language vi

# Bootstrap a demo organization populated across every major workflow:
# project, site visits + photos, an approved estimate, two change orders
# (approved + draft), two RFIs, two defects, a won proposal. Idempotent —
# re-running upserts existing rows by stable natural keys, so it's safe
# to run on a tenant that's already been seeded once.
#
# Useful for sales demos and for new contributors who need a populated
# environment to evaluate the platform without manually creating data
# across 13 modules. Prints a dev JWT + org/project IDs at the end so
# you can hit the API immediately.
#
# Requires DATABASE_URL pointing at a writable DB at migration head.
seed-demo:
	cd apps/api && PYTHONPATH=".:../:../ml" python -m scripts.seed_demo

# Tier 4 quality eval — runs the curated Q&A pairs against the seeded
# QCVN 06:2022/BXD fixture using the *real* LLM (OpenAI embeddings +
# Anthropic generation). Burns ~25–40¢ per run; gate this on manual or
# nightly invocations, never per-commit CI.
#
# Prereqs:
#   * OPENAI_API_KEY + ANTHROPIC_API_KEY exported
#   * `make seed-codeguard` already run against TEST_DATABASE_URL
#   * Migrations applied (0009_codeguard_hnsw at head)
#
# TEST_DATABASE_URL defaults to the integration-test DB (port 5438) but
# can be overridden — useful if your dev compose stack publishes Postgres
# on a different port (e.g. 5437). The test file is gated on this var
# *and* the API keys, so missing any of them produces a clean skip
# instead of a confusing failure.
eval-codeguard:
	@test -n "$$OPENAI_API_KEY" || { echo "ERROR: OPENAI_API_KEY not set" >&2; exit 1; }
	@test -n "$$ANTHROPIC_API_KEY" || { echo "ERROR: ANTHROPIC_API_KEY not set" >&2; exit 1; }
	TEST_DATABASE_URL=$${TEST_DATABASE_URL:-postgresql+asyncpg://aec:aec@localhost:5438/aec} \
		pytest apps/ml/tests/test_codeguard_quality_eval.py -v

# Run every test in the repo: API unit lane + UI component lane + web
# Playwright. The integration lane is intentionally NOT included — it
# requires the docker-compose stack to be up. Run `make test-api-integration`
# for that. Mirrors what CI does on every PR (see .github/workflows/ci.yml).
#
# `pnpm exec playwright install` ensures the chromium build is on the
# machine; subsequent runs no-op when already installed.
test: test-api test-ml test-ui test-web-unit test-web

# Run every coverage lane — api + ml (pytest-cov) + ui + web (Vitest +
# coverage-v8). Each lane enforces its own floor (see vitest.config.ts
# / pyproject.toml [tool.coverage.report]). A single failure red-gates
# the whole aggregator. Useful before opening a PR — gives you the
# global coverage picture in one command, vs. running 4 separately.
#
# Order matters slightly: web-unit-cov has typecheck baked in, so
# running it last surfaces TS regressions even if earlier lanes pass.
test-cov: test-api-cov test-ml-cov test-ui-cov test-web-unit-cov

test-api:
	cd apps/api && pytest -q

# apps/ml — codeguard pipeline + scan + retrieval + winwork pipeline
# unit tests. Self-contained: mocks LLMs + DB at the public-import
# boundary. Excludes the Tier 4 quality eval that burns real OpenAI/
# Anthropic credit (run via `make eval-codeguard` when intentional).
test-ml:
	pytest apps/ml/tests/ -q --ignore=apps/ml/tests/test_codeguard_quality_eval.py

# Same with coverage. Baseline + uncovered modules tracked in
# `docs/ml-coverage-audit.md` — raise the floor as new tests land.
test-ml-cov:
	pytest apps/ml/tests/ -q \
	    --ignore=apps/ml/tests/test_codeguard_quality_eval.py \
	    --cov=apps/ml \
	    --cov-report=term-missing:skip-covered \
	    --cov-report=html:apps/ml/test-results/coverage \
	    --cov-report=xml:apps/ml/test-results/coverage.xml

# Run the API unit lane with coverage measurement. Branch + line coverage
# over apps/api/{core,db,middleware,models,routers,schemas,services,workers}.
# Configuration lives in apps/api/pyproject.toml `[tool.coverage.*]`.
# The `--cov-report=term-missing:skip-covered` flag prints only files
# that DON'T have full coverage — keeps the output focused on gaps.
test-api-cov:
	cd apps/api && pytest -q \
	    --cov \
	    --cov-report=term-missing:skip-covered \
	    --cov-report=html:test-results/coverage \
	    --cov-report=xml:test-results/coverage.xml

# Component-level tests for `packages/ui` — Vitest + React Testing Library
# in jsdom. Fast (~2s), no browser, runs every PR via the Node CI job.
# Complements the Playwright suite: Playwright covers full-page wiring,
# Vitest covers prop / state / event-handler logic in isolation.
test-ui:
	pnpm --filter @aec/ui test

# Same lane with v8 coverage measurement. Slower (~3x) due to
# instrumentation. Thresholds in `packages/ui/vitest.config.ts`;
# CI fails if line/branch/function coverage drops below the pinned floor.
test-ui-cov:
	pnpm --filter @aec/ui test:coverage

# Library-level Vitest tests for `apps/web/lib/*` — the fetch wrappers
# (apiFetch, apiRequest, apiRequestWithMeta) and other pure-function
# helpers. Catches contract regressions (e.g. `usePriceAlert` sending
# query-string vs JSON body) at unit-test speed instead of waiting for
# Playwright to surface them.
test-web-unit:
	pnpm --filter @aec/web test

# Same lane with v8 coverage. Thresholds in `apps/web/vitest.config.ts`.
# Numerator covers `lib/` + `hooks/` only — `app/` is Server-Component +
# Next-router territory, exercised by Playwright; including it would
# skew the % toward "framework files we can't unit-test."
test-web-unit-cov:
	pnpm --filter @aec/web test:coverage

test-web:
	pnpm --filter @aec/web exec playwright install chromium
	pnpm --filter @aec/web test:e2e

# Integration lane: spins up Postgres + Redis, waits for both to be healthy,
# applies migrations, and runs the `--integration`-tagged tests against them.
#
# Host ports are *derived* from `docker compose port` rather than hardcoded —
# any developer-local `docker-compose.override.yml` (e.g. remapping Postgres
# to 5437 because 5432/5438 collide with another project) just works. The
# resolution happens once per recipe via shell substitution; if the service
# isn't up yet, `docker compose port` returns nothing and the recipe errors
# loudly with "host port not published".
#
# Env vars cover all 5 integration test modules:
#   * test_costpulse_rls / _pipeline_openai / _price_scrapers_writer:
#       need COSTPULSE_RLS_DB_URL (uses `aec` superuser; RLS tests
#       `SET LOCAL ROLE aec_app` themselves)
#   * test_admin_session_factory:
#       needs COSTPULSE_RLS_APP_URL (aec_app, NOBYPASSRLS) and
#       COSTPULSE_RLS_ADMIN_URL (aec, BYPASSRLS) — provisioned by 0010_app_role
#   * test_e2e_arq:
#       needs REDIS_URL and DATABASE_URL_ADMIN
test-api-integration-up:
	docker compose up -d postgres redis
	docker compose exec -T postgres sh -c 'until pg_isready -U aec; do sleep 1; done'
	@PG_PORT=$$(docker compose port postgres 5432 | cut -d: -f2); \
	  test -n "$$PG_PORT" || { echo "ERROR: postgres host port not published"; exit 1; }; \
	  cd apps/api && DATABASE_URL_SYNC=postgresql://aec:aec@localhost:$$PG_PORT/aec alembic upgrade head

test-api-integration: test-api-integration-up
	@PG_PORT=$$(docker compose port postgres 5432 | cut -d: -f2); \
	 REDIS_PORT=$$(docker compose port redis 6379 | cut -d: -f2); \
	 test -n "$$PG_PORT"    || { echo "ERROR: postgres host port not published"; exit 1; }; \
	 test -n "$$REDIS_PORT" || { echo "ERROR: redis host port not published"; exit 1; }; \
	 cd apps/api && \
		COSTPULSE_RLS_DB_URL=postgresql+asyncpg://aec:aec@localhost:$$PG_PORT/aec \
		COSTPULSE_RLS_APP_URL=postgresql+asyncpg://aec_app:aec_app@localhost:$$PG_PORT/aec \
		COSTPULSE_RLS_ADMIN_URL=postgresql+asyncpg://aec:aec@localhost:$$PG_PORT/aec \
		DATABASE_URL=postgresql+asyncpg://aec:aec@localhost:$$PG_PORT/aec \
		DATABASE_URL_ADMIN=postgresql+asyncpg://aec:aec@localhost:$$PG_PORT/aec \
		REDIS_URL=redis://localhost:$$REDIS_PORT/0 \
		pytest --integration -q

# ---------- Backfill / data-ops scripts ----------
#
# These are one-shot CLIs you run against a writable DB to retroactively
# populate state added by a feature that landed AFTER the affected rows
# were created. Both are idempotent on their natural keys, so re-running
# is safe (handy when the first pass got Ctrl-C'd halfway through).
#
# Forward extra flags via `ARGS=`. Common ones:
#   * `--dry-run` — count what would be touched, write nothing.
#   * `--org-id <uuid>` — scope to one tenant (e.g. after a cross-tenant
#     restore that left only one org's rows missing the new state).
#   * `-v` — verbose per-row logging.
#
# Examples:
#   make backfill-rfi-embeddings ARGS="--dry-run -v"
#   make backfill-dailylog ARGS="--org-id 00000000-... --batch-size 50"
#
# Both require `DATABASE_URL` in the environment — same async DSN the
# API server uses. See docs/operations.md "Backfills" for when to run
# each, what it does, and rollback notes.

# Walk every row in `rfis` and call ml.pipelines.rfi.upsert_rfi_embedding.
# Idempotent on `rfi_id` — refreshing an existing row also updates
# `model_version`, which is what you want when re-embedding against a new
# OpenAI model. Without OPENAI_API_KEY, the pipeline degrades to zero
# vectors — the script will complete but the embeddings will all hash to
# the same point, so the similar-RFI search becomes useless. Run this in
# an environment with credentials set when you actually want hits.
backfill-rfi-embeddings:
	@test -n "$$DATABASE_URL" || { echo "ERROR: DATABASE_URL not set" >&2; exit 1; }
	cd apps/api && PYTHONPATH=".:../" python -m scripts.backfill_rfi_embeddings $(ARGS)

# Mirror existing safety_incidents into dailylog observations via
# services.dailylog_sync.sync_incident_to_dailylog. Idempotent — incidents
# whose mirror observation already exists (linked via
# `related_safety_incident_id`) are skipped by the sync helper. Commits
# per incident, so a Ctrl-C leaves the partial backfill intact and the
# next run picks up where it stopped.
backfill-dailylog:
	@test -n "$$DATABASE_URL" || { echo "ERROR: DATABASE_URL not set" >&2; exit 1; }
	cd apps/api && PYTHONPATH="." python -m scripts.backfill_dailylog_from_siteeye $(ARGS)
