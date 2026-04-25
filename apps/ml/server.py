"""Ray Serve entrypoint for ML model serving.

Loads CV / classification models once per replica and exposes them behind a thin HTTP
surface. The FastAPI gateway calls into here only for GPU-heavy or latency-sensitive
paths that don't fit in the async worker pipeline.

Run locally:
    serve run apps.ml.server:deployment
"""

from __future__ import annotations

import logging
from typing import Any

import ray
from fastapi import FastAPI
from pydantic import BaseModel
from ray import serve

log = logging.getLogger(__name__)

api = FastAPI(title="AEC ML Serve")


class EmbedRequest(BaseModel):
    texts: list[str]
    model: str = "text-embedding-3-large"


class EmbedResponse(BaseModel):
    vectors: list[list[float]]


class ClassifyImageRequest(BaseModel):
    image_url: str
    task: str  # "site_safety" | "element_segmentation"


class ClassifyImageResponse(BaseModel):
    labels: list[dict[str, Any]]


@serve.deployment(num_replicas=1, ray_actor_options={"num_cpus": 1})
@serve.ingress(api)
class MLService:
    def __init__(self) -> None:
        # Lazy-load models on first request to keep startup fast.
        self._embed_client = None
        self._yolo = None

    def _embed(self):
        if self._embed_client is None:
            from openai import OpenAI

            self._embed_client = OpenAI()
        return self._embed_client

    def _yolo_model(self):
        if self._yolo is None:
            try:
                from ultralytics import YOLO

                self._yolo = YOLO("yolov8n.pt")
            except Exception as exc:  # pragma: no cover
                log.warning("YOLO unavailable: %s", exc)
        return self._yolo

    @api.get("/health")
    async def health(self) -> dict:
        return {"status": "ok"}

    @api.post("/embed", response_model=EmbedResponse)
    async def embed(self, body: EmbedRequest) -> EmbedResponse:
        client = self._embed()
        resp = client.embeddings.create(model=body.model, input=body.texts)
        return EmbedResponse(vectors=[d.embedding for d in resp.data])

    @api.post("/classify-image", response_model=ClassifyImageResponse)
    async def classify_image(self, body: ClassifyImageRequest) -> ClassifyImageResponse:
        model = self._yolo_model()
        if model is None:
            return ClassifyImageResponse(labels=[])
        results = model.predict(body.image_url, verbose=False)
        labels: list[dict[str, Any]] = []
        for r in results:
            for box in r.boxes:
                labels.append(
                    {
                        "class": r.names.get(int(box.cls[0].item()), "unknown"),
                        "confidence": float(box.conf[0].item()),
                        "bbox": [float(v) for v in box.xyxy[0].tolist()],
                    }
                )
        return ClassifyImageResponse(labels=labels)


deployment = MLService.bind()


if __name__ == "__main__":  # pragma: no cover
    ray.init()
    serve.run(deployment, host="0.0.0.0", port=8265)
