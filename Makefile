.PHONY: seed-codeguard test-api test-api-integration test-api-integration-up

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

test-api:
	cd apps/api && pytest -q

# Integration lane: spins up Postgres + Redis, waits for both to be healthy,
# applies migrations, and runs the `--integration`-tagged tests against them.
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
	cd apps/api && DATABASE_URL_SYNC=postgresql://aec:aec@localhost:5438/aec alembic upgrade head

test-api-integration: test-api-integration-up
	cd apps/api && \
		COSTPULSE_RLS_DB_URL=postgresql+asyncpg://aec:aec@localhost:5438/aec \
		COSTPULSE_RLS_APP_URL=postgresql+asyncpg://aec_app:aec_app@localhost:5438/aec \
		COSTPULSE_RLS_ADMIN_URL=postgresql+asyncpg://aec:aec@localhost:5438/aec \
		DATABASE_URL=postgresql+asyncpg://aec:aec@localhost:5438/aec \
		DATABASE_URL_ADMIN=postgresql+asyncpg://aec:aec@localhost:5438/aec \
		REDIS_URL=redis://localhost:6379/0 \
		pytest --integration -q
