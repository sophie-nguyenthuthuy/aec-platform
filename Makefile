.PHONY: seed-codeguard test-api

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
