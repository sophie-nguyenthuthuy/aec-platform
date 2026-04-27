"""Shared sys.path fixup for ML-side tests.

Mirrors `apps/api/tests/conftest.py` so pipelines that bridge into the
API package (e.g. `siteeye._maybe_render_boq_attachment` importing
`services.boq_io`) resolve under pytest the way they do under Docker.

Without this, tests fail with `ModuleNotFoundError: No module named 'core'`
because the ML test runner only puts `apps/ml/tests/` on the path —
none of the cross-package imports (`from core.config`, `from models.*`,
`from services.*`) would resolve.

Production already has the equivalent paths via the api Dockerfile's
`ENV PYTHONPATH=/app/apps:/app/apps/api:/app/apps/ml`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ML_ROOT = Path(__file__).resolve().parent.parent
_APPS_ROOT = _ML_ROOT.parent
_REPO_ROOT = _APPS_ROOT.parent
_API_ROOT = _APPS_ROOT / "api"

for _p in (_ML_ROOT, _API_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Minimal env so `core.config.Settings` doesn't trip on a missing .env
# during test collection. Mirrors the `apps/api/tests/conftest.py` block.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
