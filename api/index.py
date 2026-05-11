"""
Vercel Python serverless entrypoint for the FastAPI app.

Vercel's @vercel/python runtime executes a single `app` (ASGI) or
`handler(request)` (WSGI) from this file. We expose `app` so the entire
FastAPI surface (every router in `apps/api/main.py`) gets served from
one function. This works because individual handlers are short-lived
(<60s) and Vercel happily warm-starts a single Python process.

What this DOES NOT do:
  * Run ARQ workers / cron jobs. Vercel functions are request-scoped;
    there's no place to host a long-running consumer. Background work
    is either dropped (BidRadar scraper, weekly-report cron) or must
    be triggered manually via API endpoints + an external scheduler.
  * Serve WebSockets. Vercel Python functions are HTTP-only.

Path setup mirrors `infra/docker/api.Dockerfile`:
  PYTHONPATH = apps/:apps/api/:apps/ml/
so that `from routers import projects`, `from ml.pipelines.codeguard …`,
etc. resolve the same way they do in the Docker image.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------
# Vercel mounts the repo at /var/task. apps/ is one level up from this
# file (which sits at api/index.py). Resolve symlink-safely.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_APPS = _REPO_ROOT / "apps"

for p in (
    _APPS,
    _APPS / "api",
    _APPS / "ml",
):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)


# ---------------------------------------------------------------------
# Environment defaults
# ---------------------------------------------------------------------
# `core.config.Settings.environment` defaults to `development`. In a
# Vercel production deploy we want `AEC_ENV=production` to flip on the
# strict-secret guard and the JSON log format. The user is supposed to
# set this in Vercel's env UI; this fallback is here so a misconfigured
# preview deploy doesn't silently boot in dev mode and run with default
# secrets.
os.environ.setdefault("AEC_ENV", "production")
os.environ.setdefault("LOG_FORMAT", "json")


# ---------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------
# Import last so the path + env tweaks above land before `main.py` runs
# its top-level `register_all_models()` + `create_app()`.
from main import app  # type: ignore[no-redef]  # noqa: E402

# Vercel's @vercel/python runtime auto-detects an ASGI app named `app`.
# Nothing else to do — every request becomes `await app(scope, receive, send)`.
__all__ = ["app"]
