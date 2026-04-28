FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY apps/worker/requirements.txt ./apps/worker/requirements.txt
COPY apps/api/requirements.txt    ./apps/api/requirements.txt
COPY apps/ml/requirements.txt     ./apps/ml/requirements.txt
RUN pip install -r apps/worker/requirements.txt -r apps/api/requirements.txt -r apps/ml/requirements.txt

COPY apps/worker ./apps/worker
COPY apps/api    ./apps/api
COPY apps/ml     ./apps/ml

ENV PYTHONPATH=/app/apps:/app/apps/worker:/app/apps/api:/app/apps/ml
WORKDIR /app/apps/worker

CMD ["celery", "-A", "tasks", "worker", "--loglevel=info", "--concurrency=4"]
