"""Ray Serve deployment for the SiteEye YOLOv8m safety model.

Deploy:
    serve run apps.ml.serve.siteeye_safety:safety_app

The pipeline in `apps/ml/pipelines/siteeye.py` POSTs JPEG bytes to
`/siteeye-safety/infer` and parses the returned detections. This module
owns the model lifecycle and async batching — nothing else should import
the ultralytics YOLO runtime directly.
"""

from __future__ import annotations

import io
import logging
import os
from typing import Any

from fastapi import FastAPI, UploadFile
from ray import serve

logger = logging.getLogger(__name__)

MODEL_PATH = os.environ.get(
    "SITEEYE_YOLO_WEIGHTS",
    "s3://aec-platform-models/siteeye/yolov8m-safety-vi.pt",
)

CLASSES = [
    "hard_hat",
    "no_hard_hat",
    "safety_vest",
    "no_vest",
    "harness",
    "safety_boots",
    "scaffold_unsafe",
    "open_trench",
    "fire_hazard",
    "electrical_hazard",
]

CONFIDENCE_THRESHOLD = 0.35

api = FastAPI(title="siteeye-safety")


@serve.deployment(
    num_replicas=2,
    ray_actor_options={"num_gpus": 1, "num_cpus": 2},
    max_ongoing_requests=32,
)
@serve.ingress(api)
class SafetyDetector:
    def __init__(self) -> None:
        from ultralytics import YOLO

        local_weights = _ensure_local_weights(MODEL_PATH)
        self._model = YOLO(local_weights)
        logger.info("YOLOv8m safety model loaded from %s", local_weights)

    @api.get("/health")
    async def health(self) -> dict:
        return {"status": "ok", "classes": CLASSES}

    @api.post("/infer")
    async def infer(self, image: UploadFile) -> dict[str, Any]:
        raw = await image.read()
        return {"detections": await self._batched_infer(raw)}

    # Ray's async batching: up to 16 images per forward pass.
    @serve.batch(max_batch_size=16, batch_wait_timeout_s=0.1)
    async def _batched_infer(self, images: list[bytes]) -> list[list[dict[str, Any]]]:
        from PIL import Image

        pil_images = [Image.open(io.BytesIO(b)).convert("RGB") for b in images]
        results = self._model.predict(
            pil_images,
            conf=CONFIDENCE_THRESHOLD,
            verbose=False,
        )

        out: list[list[dict[str, Any]]] = []
        for pil, res in zip(pil_images, results, strict=True):
            w, h = pil.size
            detections: list[dict[str, Any]] = []
            for box, conf, cls_idx in zip(
                res.boxes.xyxy.tolist(),
                res.boxes.conf.tolist(),
                res.boxes.cls.tolist(),
                strict=True,
            ):
                x1, y1, x2, y2 = box
                detections.append(
                    {
                        "label": CLASSES[int(cls_idx)],
                        "confidence": float(conf),
                        # normalized [x, y, w, h]
                        "bbox": [x1 / w, y1 / h, (x2 - x1) / w, (y2 - y1) / h],
                    }
                )
            out.append(detections)
        return out


def _ensure_local_weights(uri: str) -> str:
    if not uri.startswith("s3://"):
        return uri
    import boto3

    bucket, _, key = uri[5:].partition("/")
    local = f"/tmp/{os.path.basename(key)}"
    if not os.path.exists(local):
        boto3.client("s3").download_file(bucket, key, local)
    return local


safety_app = SafetyDetector.bind()
