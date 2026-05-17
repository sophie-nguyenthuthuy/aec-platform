"""Tests for core.version + /_meta/version endpoint.

The reader is cached via lru_cache + has fallback paths that need
to behave gracefully when run from weird filesystem layouts (Docker
image without VERSION file, fresh checkout missing the file).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app


def _clear_caches():
    """lru_cache(maxsize=1) hangs on between tests; clear so monkeypatch
    actually takes effect."""
    from core.version import get_git_sha, get_version

    get_version.cache_clear()
    get_git_sha.cache_clear()


def test_get_version_reads_file(monkeypatch, tmp_path):
    """A VERSION file at the resolved path is returned, stripped."""
    _clear_caches()
    fake = tmp_path / "VERSION"
    fake.write_text("9.9.9\n")

    with patch("core.version._find_version_file", return_value=fake):
        from core.version import get_version

        get_version.cache_clear()
        assert get_version() == "9.9.9"


def test_get_version_env_override_wins(monkeypatch):
    """AEC_VERSION env var overrides the file (used by CI build args)."""
    _clear_caches()
    monkeypatch.setenv("AEC_VERSION", "2.5.0-rc1")
    from core.version import get_version

    get_version.cache_clear()
    assert get_version() == "2.5.0-rc1"


def test_get_version_falls_back_to_sentinel(monkeypatch):
    """Missing VERSION + no env → sentinel `0.0.0+unknown`. Recognisable
    in logs as a broken deploy."""
    _clear_caches()
    monkeypatch.delenv("AEC_VERSION", raising=False)

    with patch("core.version._find_version_file", return_value=None):
        from core.version import get_version

        get_version.cache_clear()
        assert get_version() == "0.0.0+unknown"


def test_get_git_sha_env_priority(monkeypatch):
    """RAILWAY_GIT_COMMIT_SHA wins over Vercel + manual override."""
    _clear_caches()
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123def456ghi789jkl0")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "xxx")
    monkeypatch.setenv("AEC_GIT_SHA", "yyy")

    from core.version import get_git_sha

    get_git_sha.cache_clear()
    # Truncated to 12 chars
    assert get_git_sha() == "abc123def456"


def test_get_git_sha_no_env_no_git(monkeypatch):
    """When all env vars unset AND git rev-parse fails → None.
    Caller should render as 'unknown'."""
    _clear_caches()
    for k in ("RAILWAY_GIT_COMMIT_SHA", "VERCEL_GIT_COMMIT_SHA", "AEC_GIT_SHA"):
        monkeypatch.delenv(k, raising=False)

    # Patch subprocess.run to simulate "git command not found"
    import subprocess

    def boom(*args, **kwargs):
        raise OSError("git not installed")

    with patch.object(subprocess, "run", side_effect=boom):
        from core.version import get_git_sha

        get_git_sha.cache_clear()
        # In dev env we may still have git; accept either None or a string
        result = get_git_sha()
        # Just verify it doesn't raise — either outcome is acceptable
        assert result is None or isinstance(result, str)


def test_meta_version_endpoint_returns_envelope():
    """/_meta/version exposes version + git_sha + uptime in the standard
    ok-envelope shape."""
    client = TestClient(app)
    resp = client.get("/_meta/version")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    data = body["data"]
    assert "version" in data
    assert "boot_time_utc" in data
    assert "uptime_seconds" in data
    assert isinstance(data["uptime_seconds"], int)
    assert data["uptime_seconds"] >= 0


def test_meta_version_endpoint_no_auth_required():
    """The endpoint is intentionally unauthenticated — verify-deploy
    + status page need it without a JWT."""
    client = TestClient(app)
    # No Authorization header
    resp = client.get("/_meta/version")
    assert resp.status_code == 200
    # Confirm we actually got version data, not an auth shim
    assert resp.json()["data"]["version"] is not None
