"""Unit tests for the codeguard_bootstrap on_startup hook.

These tests verify that bootstrap fails *gracefully* under every branch
the worker will hit on Railway, so a misconfigured deploy degrades to
empty `/scan` results rather than crashing the worker process.

We don't test the happy "ingest 83 chunks against a real Gemini key + DB"
path here — that's covered by the existing make seed-codeguard-all
integration path and by manual smoke after deploy.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_bootstrap_skips_when_disabled_env_set(monkeypatch):
    """`CODEGUARD_BOOTSTRAP_DISABLED=1` short-circuits before any DB work."""
    from workers.codeguard_bootstrap import bootstrap_codeguard_if_empty

    monkeypatch.setenv("CODEGUARD_BOOTSTRAP_DISABLED", "1")

    # If the disabled path leaks through, this AsyncSessionFactory mock
    # would get called — fail loudly via AsyncMock side-effect.
    with patch("workers.codeguard_bootstrap._table_is_empty") as table_empty:
        table_empty.return_value = True
        await bootstrap_codeguard_if_empty(None)
        table_empty.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_skips_when_table_populated(monkeypatch):
    """Already-populated DB → fast COUNT no-op, no Gemini calls."""
    from workers.codeguard_bootstrap import bootstrap_codeguard_if_empty

    monkeypatch.delenv("CODEGUARD_BOOTSTRAP_DISABLED", raising=False)

    with (
        patch(
            "workers.codeguard_bootstrap._table_is_empty",
            new=AsyncMock(return_value=False),
        ),
        patch("workers.codeguard_bootstrap._fixture_dir") as fixture_dir,
    ):
        await bootstrap_codeguard_if_empty(None)
        # Bootstrap should exit before touching fixtures.
        fixture_dir.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_skips_when_db_unreachable(monkeypatch):
    """COUNT raises → log + skip, don't crash the worker boot."""
    from workers.codeguard_bootstrap import bootstrap_codeguard_if_empty

    monkeypatch.delenv("CODEGUARD_BOOTSTRAP_DISABLED", raising=False)

    with patch(
        "workers.codeguard_bootstrap._table_is_empty",
        new=AsyncMock(side_effect=ConnectionError("DB unreachable")),
    ):
        # Must not raise — that would prevent the worker from booting.
        await bootstrap_codeguard_if_empty(None)


@pytest.mark.asyncio
async def test_bootstrap_skips_when_no_google_key(monkeypatch):
    """Empty table + no GOOGLE_API_KEY → warn + skip, no fixture walk."""
    from workers.codeguard_bootstrap import bootstrap_codeguard_if_empty

    monkeypatch.delenv("CODEGUARD_BOOTSTRAP_DISABLED", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with (
        patch(
            "workers.codeguard_bootstrap._table_is_empty",
            new=AsyncMock(return_value=True),
        ),
        patch("workers.codeguard_bootstrap._fixture_dir") as fixture_dir,
    ):
        await bootstrap_codeguard_if_empty(None)
        fixture_dir.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_skips_when_fixture_dir_missing(monkeypatch, tmp_path):
    """Empty table + key present but no fixtures shipped → warn + skip."""
    from workers.codeguard_bootstrap import bootstrap_codeguard_if_empty

    monkeypatch.delenv("CODEGUARD_BOOTSTRAP_DISABLED", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-fake")

    missing_dir = tmp_path / "does_not_exist"

    with (
        patch(
            "workers.codeguard_bootstrap._table_is_empty",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "workers.codeguard_bootstrap._fixture_dir",
            return_value=missing_dir,
        ),
    ):
        # Should not raise even though the path doesn't exist.
        await bootstrap_codeguard_if_empty(None)


def test_fixtures_manifest_matches_committed_files():
    """Every entry in `_FIXTURES` resolves to a file under apps/ml/fixtures.

    Drift check — if someone renames a fixture file but forgets to update
    the manifest, this catches it before a deploy ships a broken bootstrap.
    """
    from workers.codeguard_bootstrap import _FIXTURES, _fixture_dir

    base = _fixture_dir()
    for entry in _FIXTURES:
        target = base / entry["source"]
        assert target.exists(), f"manifest references missing fixture: {target}"


def test_on_startup_hook_wired_into_worker_settings():
    """Regression guard — if someone removes `on_startup` we want to fail loud."""
    from workers.queue import WorkerSettings

    assert hasattr(WorkerSettings, "on_startup")
    assert callable(WorkerSettings.on_startup)
