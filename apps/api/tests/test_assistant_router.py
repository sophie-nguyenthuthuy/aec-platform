"""Router + service tests for the cross-module AI assistant.

The LLM call is bypassed in these tests by leaving `ANTHROPIC_API_KEY`
unset — the service falls into its deterministic stub path. We assert
the wiring (404 for cross-tenant, sources reflect non-empty modules,
question echoed in stub answer) rather than the actual LLM output.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
    """Queued-result session — same pattern as the projects/activity tests."""

    def __init__(self) -> None:
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def execute(self, *_a: Any, **_kw: Any) -> Any:
        if self._results:
            return self._results.pop(0)
        # Default: empty mappings + 0 scalars. The service does many
        # COUNT queries; an empty default is a safe "no signal".
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.scalar_one.return_value = 0
        r.mappings.return_value.all.return_value = []
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture
def app(fake_db) -> FastAPI:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from middleware.auth import AuthContext, require_auth
    from routers import assistant as assistant_router

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="tester@example.com",
    )

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(assistant_router.router)

    async def _db_override() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[get_db] = _db_override
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _ensure_no_anthropic_key(monkeypatch):
    """Force the stub branch so tests don't try to hit the real API."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Settings is lru_cached — clear it so the env change takes effect.
    from core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _project_row(**overrides: Any):
    base = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        name="Tower A",
        type="commercial",
        status="construction",
        budget_vnd=1_500_000_000,
        area_sqm=None,
        floors=20,
        address={"province": "Hanoi"},
        start_date=None,
        end_date=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _push_full_context(fake_db: FakeAsyncSession, project, *, activity_count: int = 0):
    """Helper: queue the standard 8 results the service requests."""
    proj_q = MagicMock()
    proj_q.scalar_one_or_none.return_value = project
    fake_db.push(proj_q)
    activity_q = MagicMock()
    activity_q.mappings.return_value.all.return_value = [
        {
            "module": "pulse",
            "event_type": "change_order_created",
            "title": f"CO #{i}",
            "timestamp": datetime(2026, 4, 25, tzinfo=UTC),
        }
        for i in range(activity_count)
    ]
    fake_db.push(activity_q)
    # 6 _scalar() calls — open tasks, open COs, open RFIs, conflicts,
    # defects, incidents.
    for n in (3, 1, 2, 0, 4, 0):
        s = MagicMock()
        s.scalar_one.return_value = n
        fake_db.push(s)


# ---------- Happy path (stub answer) ----------


async def test_ask_returns_envelope_with_stub_answer_when_no_api_key(client, fake_db):
    project = _project_row()
    _push_full_context(fake_db, project, activity_count=2)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask",
        json={"question": "What's blocking us this week?"},
    )

    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["project_id"] == str(project.id)
    # Stub branch echoes the question back so callers see *something*.
    assert "What's blocking us this week?" in body["answer"]
    # Sources reflect every module that had non-zero signal in the
    # context (pulse, drawbridge, handover — siteeye is 0, omitted).
    modules = {s["module"] for s in body["sources"]}
    assert "pulse" in modules
    assert "drawbridge" in modules
    assert "handover" in modules
    # Activity bucket appears when there are recent events.
    assert "activity" in modules


async def test_ask_omits_sources_for_zero_signal_modules(client, fake_db):
    """A project with no open issues should produce a clean stub with
    no per-module citations — only the activity citation if there's
    any (here zero, so none)."""
    project = _project_row()
    proj_q = MagicMock()
    proj_q.scalar_one_or_none.return_value = project
    fake_db.push(proj_q)
    activity_q = MagicMock()
    activity_q.mappings.return_value.all.return_value = []
    fake_db.push(activity_q)
    for _ in range(6):
        s = MagicMock()
        s.scalar_one.return_value = 0
        fake_db.push(s)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask",
        json={"question": "Status?"},
    )

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["sources"] == []


# ---------- 404 path ----------


async def test_ask_404_for_cross_tenant_project(client, fake_db):
    """Project not in caller's org → clean 404, not RLS error."""
    proj_q = MagicMock()
    proj_q.scalar_one_or_none.return_value = None
    fake_db.push(proj_q)

    res = await client.post(
        f"/api/v1/assistant/projects/{uuid4()}/ask",
        json={"question": "hi"},
    )
    assert res.status_code == 404


# ---------- Validation ----------


async def test_ask_rejects_empty_question(client, fake_db):
    res = await client.post(
        f"/api/v1/assistant/projects/{uuid4()}/ask",
        json={"question": ""},
    )
    assert res.status_code == 422


async def test_ask_rejects_overlong_question(client, fake_db):
    res = await client.post(
        f"/api/v1/assistant/projects/{uuid4()}/ask",
        json={"question": "x" * 5000},
    )
    assert res.status_code == 422


async def test_ask_caps_history_length(client, fake_db):
    """Prevent unbounded chat history blowing up token budget."""
    res = await client.post(
        f"/api/v1/assistant/projects/{uuid4()}/ask",
        json={
            "question": "Follow-up?",
            "history": [{"role": "user", "content": f"q{i}"} for i in range(25)],
        },
    )
    assert res.status_code == 422


# ---------- Token estimate ----------


async def test_ask_reports_context_token_estimate(client, fake_db):
    """The token estimate field exists on every response so ops can see
    how heavy each call was without parsing logs."""
    project = _project_row()
    _push_full_context(fake_db, project)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask",
        json={"question": "Status?"},
    )

    assert res.status_code == 200
    estimate = res.json()["data"]["context_token_estimate"]
    assert estimate > 0  # the JSON dump is at least a few hundred tokens
