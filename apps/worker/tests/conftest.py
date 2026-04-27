"""Shared pytest setup for `apps/worker/tests`.

The worker module imports service-level glue from `apps/api/services` —
e.g. `tasks.py::bidradar_scrape_source` does `from services.bidradar_jobs
import scrape_and_score_for_all_orgs`. That bare-package import is the
production path (apps/api is on PYTHONPATH inside the worker Dockerfile,
see infra/docker/worker.Dockerfile), so we mirror it here.

We also stub out the env vars that the api side reads at module-load
time (DATABASE_URL, SUPABASE_JWT_SECRET) — `services.bidradar_jobs`
imports `db.session` which builds the engine eagerly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Mirror the worker container's PYTHONPATH:
#   apps/worker  → the `tasks` module under test
#   apps/api     → bare-package `services.*`, `db.*`, `models.*`
#   apps/ml      → `ml.pipelines.*` (pulled in transitively by services.bidradar_jobs)
#   repo root    → `apps.*` form, used by some lazy imports
_WORKER_ROOT = Path(__file__).resolve().parent.parent
_APPS_ROOT = _WORKER_ROOT.parent
_API_ROOT = _APPS_ROOT / "api"
_ML_ROOT = _APPS_ROOT / "ml"
_REPO_ROOT = _APPS_ROOT.parent

for _p in (_WORKER_ROOT, _API_ROOT, _ML_ROOT, _APPS_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# `_APPS_ROOT` (= `apps/`) is the one that lets `from ml.pipelines.X import ...`
# resolve — `ml` is itself a package at `apps/ml/`, so its parent dir must be
# importable. `_ML_ROOT` (= `apps/ml/`) supports the bare-package
# `from pipelines.X import ...` form used in places where the api lazy-imports.

# Stub env so `db.session` doesn't refuse to import. Real values are
# provided in CI / local dev; tests here mock at the function boundary
# so the engine is never actually used.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("DATABASE_URL_ADMIN", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
