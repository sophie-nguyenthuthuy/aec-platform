# Ray Serve deployment for the SiteEye YOLOv8m safety model.
# The image bundles ultralytics + torch + ray[serve]; weights are pulled at runtime
# from S3 (`SITEEYE_YOLO_WEIGHTS`) by `apps/ml/serve/siteeye_safety.py`.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

# torch + opencv (ultralytics dep) need libgl/libglib/ffmpeg stubs.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libgl1 libglib2.0-0 ffmpeg libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY apps/ml/serve/requirements.txt ./apps/ml/serve/requirements.txt
RUN pip install -r apps/ml/serve/requirements.txt

COPY apps/ml ./apps/ml

ENV PYTHONPATH=/app
EXPOSE 8000 8265

# `serve run` blocks in the foreground and manages the Ray head + replicas.
# --route-prefix=/siteeye-safety aligns with the pipeline caller
# (`apps/ml/pipelines/siteeye.py` hits `${base}/siteeye-safety/infer`) and the
# k8s readiness probe (`/siteeye-safety/health`). Without this, `serve run`
# defaults to `/` and both the pipeline and the probe would 404.
CMD ["serve", "run", "--host", "0.0.0.0", "--port", "8000", \
     "--route-prefix", "/siteeye-safety", \
     "apps.ml.serve.siteeye_safety:safety_app"]
