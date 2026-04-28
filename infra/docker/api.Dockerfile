FROM python:3.14-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt ./apps/api/requirements.txt
COPY apps/ml/requirements.txt  ./apps/ml/requirements.txt
RUN pip install -r apps/api/requirements.txt -r apps/ml/requirements.txt

COPY apps/api ./apps/api
COPY apps/ml  ./apps/ml

ENV PYTHONPATH=/app/apps:/app/apps/api:/app/apps/ml
WORKDIR /app/apps/api

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
