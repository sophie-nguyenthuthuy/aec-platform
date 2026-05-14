# Arq background worker.
#
# Runs the same Python code as the API container but with `arq` as the
# entrypoint instead of `uvicorn`. Used for:
#   * drawbridge_ingest_job        — chunk + embed uploaded drawings
#   * weekly_report_job            — Pulse client reports (cron Mondays)
#   * price_alerts_evaluate_job    — CostPulse price-trigger fanout (cron nightly)
#   * scrape_prices_job            — BidRadar / material-price scrapers
#   * photo_analysis_job           — SiteEye PPE detection
#   * rfq_dispatch_job             — CostPulse RFQ email fanout
#
# Why a separate image instead of the celery one in worker.Dockerfile:
#   * arq is the pattern actually used by routers (see uses in
#     apps/api/routers/{costpulse,siteeye,drawbridge}.py — all
#     `from workers.queue import enqueue_*`).
#   * Celery tasks in apps/worker/tasks.py are legacy / kept for tests.
#   * arq plugs into Redis directly via the same REDIS_URL the API uses;
#     no separate broker container.

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Same Python deps as the API — the worker imports api routers' service
# modules to share business logic + ORM models. Installing both
# requirements files keeps drift between API + worker impossible.
COPY apps/api/requirements.txt ./apps/api/requirements.txt
COPY apps/ml/requirements.txt  ./apps/ml/requirements.txt
RUN pip install -r apps/api/requirements.txt -r apps/ml/requirements.txt

COPY apps/api ./apps/api
COPY apps/ml  ./apps/ml

# arq discovers `WorkerSettings` via dotted-path
ENV PYTHONPATH=/app/apps:/app/apps/api:/app/apps/ml

CMD ["arq", "workers.queue.WorkerSettings"]
