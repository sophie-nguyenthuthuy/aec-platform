.PHONY: seed-codeguard eval-codeguard test test-api test-api-integration test-api-integration-up test-web hooks lint

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

# Run every test in the repo: API unit lane + web Playwright. The
# integration lane is intentionally NOT included — it requires the
# docker-compose stack to be up. Run `make test-api-integration` for
# that. Mirrors what CI does on every PR (see .github/workflows/ci.yml).
#
# `pnpm exec playwright install` ensures the chromium build is on the
# machine; subsequent runs no-op when already installed.
test: test-api test-web

test-api:
	cd apps/api && pytest -q

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
