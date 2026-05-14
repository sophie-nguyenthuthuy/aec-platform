"""Tests for the org modules-preference endpoint.

PATCH /api/v1/orgs/{id}/modules backs the onboarding wizard's
step 2 (module selection) + the Settings → Modules surface later.

Auth posture:
  * Authenticated caller required
  * Caller must be owner OR admin of the target org
  * Non-members get 404 (not 403) so org existence doesn't leak
  * Member-role gets 403 (they're in the org but can't change
    its preferences)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app
from middleware.auth import UserContext, require_user


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _user_ctx() -> UserContext:
    return UserContext(user_id=uuid4(), email="alice@example.com")


def _mock_admin_session_factory(role_for_caller: str | None, captured: list):
    """Build a TenantAwareSession-style async context manager whose
    `execute` returns (role | None) for the membership check and records
    every (sql, params) for assertion.
    """

    class _Result:
        def __init__(self, value):
            self._v = value

        def scalar_one_or_none(self):
            return self._v

    async def fake_execute(stmt, params=None):
        sql = str(stmt)
        captured.append((sql, dict(params or {})))
        if "FROM org_members" in sql:
            return _Result(role_for_caller)
        return _Result(None)

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)
    sess.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return sess

        async def __aexit__(self, *a):
            return False

    return lambda *a, **kw: _Ctx()


def test_patch_modules_requires_auth(client):
    """Anonymous call → 401/403 from require_user."""
    resp = client.patch(
        f"/api/v1/orgs/{uuid4()}/modules",
        json={"modules": ["pulse"]},
    )
    assert resp.status_code in (401, 403)


def test_patch_modules_validates_payload_shape(client):
    """`modules` must be a list of strings."""
    app.dependency_overrides[require_user] = lambda: _user_ctx()
    captured: list = []
    with patch(
        "routers.orgs.AdminSessionFactory",
        _mock_admin_session_factory("owner", captured),
    ):
        resp = client.patch(
            f"/api/v1/orgs/{uuid4()}/modules",
            json={"modules": "not-a-list"},
        )
    assert resp.status_code == 400


def test_patch_modules_404_for_non_member(client):
    """Caller has no membership → 404 (no existence leak)."""
    app.dependency_overrides[require_user] = lambda: _user_ctx()
    captured: list = []
    with patch(
        "routers.orgs.AdminSessionFactory",
        _mock_admin_session_factory(None, captured),
    ):
        resp = client.patch(
            f"/api/v1/orgs/{uuid4()}/modules",
            json={"modules": ["pulse"]},
        )
    assert resp.status_code == 404


def test_patch_modules_403_for_member_role(client):
    """Member is in the org but can't change preferences → 403."""
    app.dependency_overrides[require_user] = lambda: _user_ctx()
    captured: list = []
    with patch(
        "routers.orgs.AdminSessionFactory",
        _mock_admin_session_factory("member", captured),
    ):
        resp = client.patch(
            f"/api/v1/orgs/{uuid4()}/modules",
            json={"modules": ["pulse"]},
        )
    assert resp.status_code == 403


def test_patch_modules_writes_for_owner(client):
    """Owner role → writes the JSONB array, returns it back."""
    app.dependency_overrides[require_user] = lambda: _user_ctx()
    captured: list = []
    with patch(
        "routers.orgs.AdminSessionFactory",
        _mock_admin_session_factory("owner", captured),
    ):
        resp = client.patch(
            f"/api/v1/orgs/{uuid4()}/modules",
            json={"modules": ["pulse", "siteeye", "costpulse"]},
        )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["modules"] == ["pulse", "siteeye", "costpulse"]

    # Verify the UPDATE statement was fired
    update_called = any("UPDATE organizations" in s for s, _ in captured)
    assert update_called


def test_patch_modules_writes_for_admin(client):
    """Admin role also has write access (not just owner)."""
    app.dependency_overrides[require_user] = lambda: _user_ctx()
    captured: list = []
    with patch(
        "routers.orgs.AdminSessionFactory",
        _mock_admin_session_factory("admin", captured),
    ):
        resp = client.patch(
            f"/api/v1/orgs/{uuid4()}/modules",
            json={"modules": ["drawbridge"]},
        )
    assert resp.status_code == 200
