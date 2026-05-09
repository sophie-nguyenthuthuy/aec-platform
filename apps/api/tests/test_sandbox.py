"""Tests for the sandbox / test-mode API key path.

Three layers:

  * `is_test_mode` — pure helper that classifies an AuthContext.
  * `mint_key(mode=...)` — service-side validation + INSERT bound params.
  * Sandbox router — `/api/v1/sandbox/*` returns fixture data with
    pinned UUIDs that partner integration tests can rely on.

The dual-auth `_api_key_auth` flow propagating `mode` from the DB row
to `AuthContext.api_key_mode` is exercised in test_api_keys.py via the
existing dual-auth E2E test; here we cover the service-level + router
seams.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role
from services.api_keys import hash_key, key_prefix, mint_key
from services.sandbox import (
    SAMPLE_DEFECT_ID,
    SAMPLE_PROJECT_ID,
    SAMPLE_RFI_ID,
    SAMPLE_SUPPLIER_ID,
    is_test_mode,
    sample_defects,
    sample_projects,
    sample_rfis,
    sample_suppliers,
    stub_mutation_response,
)

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
USER_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
KEY_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


# ---------- FakeAsyncSession (minimal — sandbox router doesn't query DB) ----------


class FakeAsyncSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.mappings.return_value.one.return_value = {}
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


# ---------- is_test_mode ----------


def _live_user_ctx() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="user@example.com",
    )


def _api_key_ctx(mode: str) -> AuthContext:
    """Build an api-key AuthContext. `mode` flows from `api_keys.mode`
    via `_api_key_auth` in production; the dataclass field is a
    keyword arg so tests can synthesise either branch directly."""
    return AuthContext(
        user_id=KEY_ID,
        organization_id=ORG_ID,
        role="api_key",
        email="",
        api_key_mode=mode,
        api_key_id=KEY_ID,
    )


async def test_is_test_mode_false_for_human_users():
    """Users (Supabase JWT) are always live — there's no UI affordance
    to "browse test data". Pin so a UI feature later doesn't
    accidentally route real users to fixtures."""
    assert is_test_mode(_live_user_ctx()) is False


async def test_is_test_mode_true_only_for_test_keys():
    """Live api-keys → False. Test api-keys → True."""
    assert is_test_mode(_api_key_ctx("live")) is False
    assert is_test_mode(_api_key_ctx("test")) is True


# ---------- Fixture content invariants ----------


async def test_sample_fixtures_use_pinned_ids():
    """Partners' integration tests hardcode these UUIDs. Pin so a
    refactor that randomises them breaks here, not in someone else's
    pipeline."""
    projects = sample_projects()
    assert any(p["id"] == str(SAMPLE_PROJECT_ID) for p in projects)
    defects = sample_defects()
    assert any(d["id"] == str(SAMPLE_DEFECT_ID) for d in defects)
    rfis = sample_rfis()
    assert any(r["id"] == str(SAMPLE_RFI_ID) for r in rfis)
    suppliers = sample_suppliers()
    assert any(s["id"] == str(SAMPLE_SUPPLIER_ID) for s in suppliers)


async def test_sample_projects_span_lifecycle_statuses():
    """At least one row each in planning / construction / completed —
    so a partner's `?status=construction` filter test returns data
    rather than empty."""
    statuses = {p["status"] for p in sample_projects()}
    assert {"planning", "construction", "completed"}.issubset(statuses)


async def test_stub_mutation_response_marks_test_mode():
    """The 202-shaped stub MUST flag itself as test-mode so partners
    don't conclude their write actually persisted."""
    out = stub_mutation_response(action="create_project")
    assert out["status"] == "accepted_test_mode"
    assert "test-mode" in out["note"].lower() or "test mode" in out["note"].lower()


# ---------- mint_key with mode ----------
#
# `mode` lives on the api_keys row (migration 0033) and threads through
# `mint_key(..., mode=...)` → DB INSERT → RETURNING → row dict. The
# tests below pin all three seams.


async def test_mint_key_persists_mode_in_bound_params(fake_db):
    """`mode` round-trips into the INSERT bound params and the
    RETURNING projection. Pin both sides so the router's POST body
    reaches the DB."""
    insert_result = MagicMock()
    insert_result.mappings.return_value.one.return_value = {
        "id": KEY_ID,
        "name": "Sandbox key",
        "prefix": "deadbeef",
        "scopes": ["projects:read"],
        "rate_limit_per_minute": None,
        "created_at": None,
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
        "mode": "test",
    }
    fake_db.push(insert_result)

    raw, row = await mint_key(
        fake_db,
        organization_id=ORG_ID,
        created_by=USER_ID,
        name="Sandbox key",
        scopes=["projects:read"],
        rate_limit_per_minute=None,
        expires_at=None,
        mode="test",
    )

    params = fake_db.calls[0][1]
    assert params["mode"] == "test"
    assert params["hash"] == hash_key(raw)
    assert params["prefix"] == key_prefix(raw)
    assert row["mode"] == "test"


async def test_mint_key_defaults_mode_to_live(fake_db):
    """Backward compat: callers that don't pass `mode` mint a live
    key. Pin the default so a future signature change doesn't
    silently flip every minted key to test."""
    insert_result = MagicMock()
    insert_result.mappings.return_value.one.return_value = {
        "id": KEY_ID,
        "name": "x",
        "prefix": "deadbeef",
        "scopes": [],
        "rate_limit_per_minute": None,
        "created_at": None,
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
        "mode": "live",
    }
    fake_db.push(insert_result)

    await mint_key(
        fake_db,
        organization_id=ORG_ID,
        created_by=USER_ID,
        name="x",
        scopes=[],
        rate_limit_per_minute=None,
        expires_at=None,
        # mode omitted on purpose
    )
    assert fake_db.calls[0][1]["mode"] == "live"


async def test_mint_key_rejects_unknown_mode(fake_db):
    """Service-side check: anything outside {'live','test'} raises
    before the INSERT. Defense in depth on top of the router's
    pydantic regex."""
    with pytest.raises(ValueError, match="unknown_mode"):
        await mint_key(
            fake_db,
            organization_id=ORG_ID,
            created_by=USER_ID,
            name="bad",
            scopes=["projects:read"],
            rate_limit_per_minute=None,
            expires_at=None,
            mode="staging",
        )
    assert fake_db.calls == []


# ---------- Sandbox router ----------


def _build_sandbox_app(role: str = "admin") -> FastAPI:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.api_key_auth import require_user_or_api_key
    from routers import sandbox as sandbox_router

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(sandbox_router.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="user@example.com",
    )
    # Override BOTH dual-auth and the underlying user auth so we don't
    # need a real Supabase JWT in test fixtures.
    app.dependency_overrides[require_user_or_api_key] = lambda: auth_ctx
    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[require_min_role(Role.ADMIN)] = lambda: auth_ctx
    return app


async def test_sandbox_projects_returns_fixture_set():
    """Pin the response shape — partner integration tests rely on
    deterministic JSON. The pinned project ID must surface so
    `assert response[0].id == "00000000-…-001"` keeps passing across
    deploys."""
    app = _build_sandbox_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/sandbox/projects")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert len(data) >= 1
    ids = {row["id"] for row in data}
    assert str(SAMPLE_PROJECT_ID) in ids


async def test_sandbox_defects_response_pins_pinned_ids():
    app = _build_sandbox_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/sandbox/defects")
    assert res.status_code == 200
    data = res.json()["data"]
    assert any(d["id"] == str(SAMPLE_DEFECT_ID) for d in data)


async def test_sandbox_rfis_endpoint_works():
    app = _build_sandbox_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/sandbox/rfis")
    assert res.status_code == 200
    assert res.json()["data"][0]["id"] == str(SAMPLE_RFI_ID)


async def test_sandbox_suppliers_endpoint_works():
    app = _build_sandbox_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/sandbox/suppliers")
    assert res.status_code == 200
    assert res.json()["data"][0]["id"] == str(SAMPLE_SUPPLIER_ID)
