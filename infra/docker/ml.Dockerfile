FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY apps/ml/requirements.txt ./apps/ml/requirements.txt
RUN pip install -r apps/ml/requirements.txt "ray[serve]==2.36.0" mlflow==2.17.0

COPY apps/ml ./apps/ml

ENV PYTHONPATH=/app/apps/ml
WORKDIR /app/apps/ml

EXPOSE 8265
CMD ["serve", "run", "server:deployment"]
