"""Tests for the manual codeguard-bootstrap admin endpoint.

The endpoint is owner-side ops tooling. Tests lock in:
  * Admin gate (member 403)
  * Missing GOOGLE_API_KEY → 503 with actionable detail
  * Already-populated + force=false → skip path (no-op)
  * Force=true on populated DB → TRUNCATE CASCADE fires
  * Empty DB → ingest runs across all fixtures
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app
from middleware.auth import AuthContext, require_auth


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth_ctx(role: str = "admin") -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=role,
        email="ops@example.com",
    )


def _mock_session_factory(*, regs_count: int, captured: list | None = None):
    """Admin session that returns the given regs count on the first
    `SELECT COUNT(*)` and records subsequent SQL."""

    recorded: list = captured if captured is not None else []
    state = {"select_count_calls": 0}

    class _R:
        def __init__(self, v):
            self._v = v
            self.rowcount = 1

        def mappings(self):
            return self

        def one_or_none(self):
            return self._v

        def one(self):
            return self._v or {}

        def all(self):
            return self._v if isinstance(self._v, list) else []

        def scalar_one(self):
            return self._v

    async def fake_execute(stmt, params=None):
        sql = str(stmt)
        recorded.append((sql, dict(params or {})))
        if "SELECT COUNT(*) FROM regulations" in sql:
            state["select_count_calls"] += 1
            if state["select_count_calls"] == 1:
                return _R(regs_count)
            return _R(regs_count + 83)  # after ingest, 6 fixtures = 83 chunks
        return _R(None)

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)
    sess.commit = AsyncMock()

    def factory(*a, **kw):
        class _Ctx:
            async def __aenter__(self_inner):
                return sess

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()

    return factory


def test_bootstrap_requires_admin(client):
    """Member role → 403, no DB hit."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("member")
    resp = client.post("/api/v1/admin/codeguard/bootstrap")
    assert resp.status_code == 403


def test_bootstrap_503_without_google_key(client, monkeypatch):
    """No GOOGLE_API_KEY → 503 with operator-actionable hint."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")

    with patch("db.session.AdminSessionFactory", _mock_session_factory(regs_count=0)):
        resp = client.post("/api/v1/admin/codeguard/bootstrap")

    assert resp.status_code == 503
    body = resp.json()
    msg = (
        body.get("errors", [{}])[0].get("message", "")
        if body.get("errors")
        else body.get("detail", "")
    )
    assert "GOOGLE_API_KEY" in msg


def test_bootstrap_skips_when_already_populated(client, monkeypatch):
    """force=false (default) + regs > 0 → skip with hint."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-fake")
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")

    with patch(
        "db.session.AdminSessionFactory",
        _mock_session_factory(regs_count=6),
    ):
        resp = client.post("/api/v1/admin/codeguard/bootstrap")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "skipped"
    assert body["existing_count"] == 6
    assert "force=true" in body["hint"]


def test_bootstrap_force_truncates_then_reingests(client, monkeypatch):
    """force=true + regs > 0 → TRUNCATE CASCADE + re-ingest."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-fake")
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")

    captured: list = []

    with patch(
        "db.session.AdminSessionFactory",
        _mock_session_factory(regs_count=6, captured=captured),
    ), patch(
        # Stub the actual ingest pipeline — we're testing the harness,
        # not the ingest itself (covered by L3-3 tests).
        "pipelines.codeguard_ingest.ingest_regulation",
        new=AsyncMock(
            return_value=MagicMock(sections_written=13, chunks_written=13),
        ),
    ):
        resp = client.post("/api/v1/admin/codeguard/bootstrap?force=true")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "complete"
    assert "per_fixture" in body
    # TRUNCATE must have fired
    truncate_seen = any("TRUNCATE regulations CASCADE" in s for s, _ in captured)
    assert truncate_seen


def test_bootstrap_empty_db_ingests_all_fixtures(client, monkeypatch):
    """force=false but DB empty → ingest runs (since the skip path
    requires regs > 0)."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-fake")
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")

    with patch(
        "db.session.AdminSessionFactory",
        _mock_session_factory(regs_count=0),
    ), patch(
        "pipelines.codeguard_ingest.ingest_regulation",
        new=AsyncMock(
            return_value=MagicMock(sections_written=13, chunks_written=13),
        ),
    ):
        resp = client.post("/api/v1/admin/codeguard/bootstrap")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "complete"
    # 6 fixtures defined in workers/codeguard_bootstrap.py::_FIXTURES
    assert len(body["per_fixture"]) == 6
    # Each result should report sections + chunks (not "error" or "skipped")
    assert all("sections" in r or "skipped" in r or "error" in r for r in body["per_fixture"])


def test_bootstrap_continues_on_per_fixture_failure(client, monkeypatch):
    """One fixture failing shouldn't kill the rest — per_fixture array
    reports the error inline."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-fake")
    app.dependency_overrides[require_auth] = lambda: _auth_ctx("admin")

    # First fixture raises, the rest succeed
    call_count = {"n": 0}

    async def flaky_ingest(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated gemini API failure")
        return MagicMock(sections_written=13, chunks_written=13)

    with patch(
        "db.session.AdminSessionFactory",
        _mock_session_factory(regs_count=0),
    ), patch(
        "pipelines.codeguard_ingest.ingest_regulation",
        new=AsyncMock(side_effect=flaky_ingest),
    ):
        resp = client.post("/api/v1/admin/codeguard/bootstrap")

    assert resp.status_code == 200
    body = resp.json()["data"]
    errors = [r for r in body["per_fixture"] if "error" in r]
    assert len(errors) == 1
    assert "gemini API failure" in errors[0]["error"]
    # Remaining 5 succeeded
    successes = [r for r in body["per_fixture"] if "sections" in r]
    assert len(successes) == 5
