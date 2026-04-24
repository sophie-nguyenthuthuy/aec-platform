# Deployment

Two parallel job systems run beside the API:

| System | Lives in | Runs | Handles |
| --- | --- | --- | --- |
| Celery | `apps/worker/tasks.py` | `worker.Dockerfile` | BidRadar scraping, WinWork email, file post-processing |
| Arq    | `apps/api/workers/queue.py` | `api.Dockerfile` + `arq` command | SiteEye photo analysis, weekly reports, RFQ dispatch, price alerts |

Both use the same Redis instance but different key namespaces.

## Local (docker-compose)

```bash
# Core stack (postgres, redis, api, worker [celery], web)
docker compose up

# Include the Ray Serve YOLO model too (pulls ~500MB image):
docker compose --profile ml up
```

The `arq-worker` service starts by default. Photo analysis submitted via the
API will sit in the Arq queue until this worker processes it.

## Kubernetes

```bash
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/config.yaml        # secrets (fill PLACEHOLDER) + configmap
kubectl apply -f infra/k8s/api.yaml
kubectl apply -f infra/k8s/worker.yaml        # Celery
kubectl apply -f infra/k8s/arq-worker.yaml    # Arq + embedded cron
kubectl apply -f infra/k8s/siteeye-safety.yaml
kubectl apply -f infra/k8s/web.yaml
kubectl apply -f infra/k8s/ingress.yaml
```

## Scheduled jobs

Cron schedules are **embedded in each worker's own configuration**; there are
no separate Kubernetes `CronJob` resources.

- **Celery Beat** — declared in `app.conf.beat_schedule` inside
  `apps/worker/tasks.py`. Currently: BidRadar daily scrape (21:30 UTC), weekly
  digest (Mon 00:00 UTC).

- **Arq cron** — declared in `WorkerSettings.cron_jobs` inside
  `apps/api/workers/queue.py`. Currently:
  - `weekly_report_cron` — Mon 06:00 UTC (~13:00 ICT). Fans out one
    `weekly_report_job` per project with activity in the past week.
  - `price_alerts_evaluate_job` — 22:00 UTC daily.

Arq's `cron()` uses `unique=True` by default, so scaling `arq-worker` to
multiple replicas is safe — only one replica will claim each scheduled tick.
We still run a single replica by default to minimize coordination overhead.

## Ray Serve (SiteEye safety model)

`apps/ml/serve/siteeye_safety.py` defines a `SafetyDetector` deployment with
`num_replicas=2` and `@serve.batch(max_batch_size=16)`. The Kubernetes
`Deployment` runs one pod that hosts the Ray head + serve replicas. **To scale
inference throughput, edit `num_replicas` in that file**, not the k8s replica
count (unless you're running a multi-node Ray cluster).

Weights are pulled at startup from `s3://aec-platform-models/siteeye/...`
(`SITEEYE_YOLO_WEIGHTS`). First-call readiness can take ~60s.

The API + Arq worker reach the model via the `SITEEYE_RAY_SERVE_URL` env var
(defaults to `http://siteeye-safety:8000` in-cluster).
