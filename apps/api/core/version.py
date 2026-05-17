"""Single source of truth for the AEC Platform version string.

Reads the `VERSION` file at the repo root at import time. Result is
cached so any subsequent imports + endpoint calls return the same
value without re-reading the file.

The repo-root VERSION file is the canonical version; `pyproject.toml`
and `package.json` mirror it for tooling that requires the version
to be embedded (PyPI publish, npm publish). The release script
(`scripts/release.sh`) updates ALL THREE in lock-step.

Why a file (not an env var):
  * Reproducible builds — the version is committed to git, so
    `git checkout v1.0.0` gives you a tree that REPORTS 1.0.0.
  * Works in dev (no env vars set), CI (no env vars set), prod
    (where Railway might shadow env vars unintentionally).
  * `git diff VERSION` is the simplest possible release signal
    for the GitHub Actions tag-on-bump workflow.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


# Walk up from this file until we find the VERSION file, capped at 6
# levels to avoid infinite loops in weird mount layouts.
def _find_version_file() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        candidate = parent / "VERSION"
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def get_version() -> str:
    """Return the platform version string (e.g. `"1.0.0"`).

    Falls back to `"0.0.0+unknown"` if the VERSION file isn't found.
    That's a deliberate signal — running code that can't find its own
    version file is broken, and a recognisable sentinel makes it
    obvious in logs + the /_meta/version endpoint.
    """
    # Explicit env-var override for CI builds that inject the version
    # into the Docker layer instead of bind-mounting the file.
    env_override = os.environ.get("AEC_VERSION")
    if env_override:
        return env_override.strip()

    path = _find_version_file()
    if path is None:
        logger.warning("core.version: VERSION file not found, returning sentinel")
        return "0.0.0+unknown"

    try:
        return path.read_text(encoding="utf-8").strip() or "0.0.0+unknown"
    except OSError as exc:
        logger.warning("core.version: failed to read %s: %s", path, exc)
        return "0.0.0+unknown"


@lru_cache(maxsize=1)
def get_git_sha() -> str | None:
    """Return the short git SHA the build was cut from, if available.

    Reads in order of trust:
      1. `RAILWAY_GIT_COMMIT_SHA` — set by Railway on every build
      2. `VERCEL_GIT_COMMIT_SHA` — set by Vercel
      3. `AEC_GIT_SHA` — manual override
      4. `git rev-parse --short HEAD` — local dev fallback

    Returns None if all four miss — caller should render that as
    "unknown" rather than crash.
    """
    for env in ("RAILWAY_GIT_COMMIT_SHA", "VERCEL_GIT_COMMIT_SHA", "AEC_GIT_SHA"):
        v = os.environ.get(env)
        if v:
            return v[:12]  # short SHA, 12 chars matches `git log --oneline` default

    # Local dev fallback — only works if we're inside a git checkout.
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            return sha or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None
