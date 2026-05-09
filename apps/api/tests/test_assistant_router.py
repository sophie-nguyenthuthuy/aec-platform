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
    """Queued-result session — same pattern as the projects/activity tests.

    Now also tracks `add()` / `flush()` / `commit()` / `delete()` so the
    thread-persistence tests can assert that the right rows were
    persisted (AssistantThread + 2 AssistantMessages per ask)."""

    def __init__(self) -> None:
        self._results: list[Any] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None: ...
    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def refresh(self, obj: Any) -> None: ...

    async def execute(self, *_a: Any, **_kw: Any) -> Any:
        if self._results:
            return self._results.pop(0)
        # Default: empty mappings + 0 scalars + empty scalars. The
        # service fires many COUNT queries plus a "load existing thread"
        # query; an empty default is a safe "no signal / new thread".
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.scalar_one.return_value = 0
        r.mappings.return_value.all.return_value = []
        r.scalars.return_value.all.return_value = []
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
    """Helper: queue ALL the results the service requests during a full
    context roll-up — 23 queries in total, covering every module
    (pulse + drawbridge + handover + siteeye + costpulse + codeguard +
    schedulepilot + submittals + dailylog + changeorder + punchlist).

    Why 23 specifically: `services.assistant._get_full_context` walks
    every module in turn, firing one or more `session.execute(...)`
    per. The test fixture pushes exactly that many so any per-test
    `fake_db.push(...)` lands at query #24+ (typically the thread
    SELECT). Without this padding, a test that pushes a `thread_q`
    after the helper sees its `thread_q` consumed by query #9 (a
    costpulse `_scalar` call) — and the actual thread query at #24
    falls through to the FakeAsyncSession's empty-queue default,
    creating a fresh thread instead of loading the existing one.

    Hard-coded 23 rather than auto-detected because:
      * The count is a contract between the service and the test —
        adding a module that fires a 24th query is a deliberate change
        and should require updating this helper.
      * Auto-detecting (e.g. by counting `session.execute` calls in
        the source) would tie the helper to the service's import-time
        AST, which is brittle.

    If a new module adds a context query: bump the padding count below
    AND add the bookkeeping signal to the matching service rollup. The
    snapshot tests don't catch this — the service's `_get_full_context`
    will silently return `[]` for the new module's signal, and the
    assistant's prompt will be missing one bullet point.
    """
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
    # 15 padding results — covering costpulse (3) + codeguard (3) +
    # schedulepilot (3) + submittals (1) + dailylog (3) + changeorder
    # (2). Each module's contribution counts every session.execute
    # the service fires during its rollup, including the non-_scalar
    # ones (estimates list, schedules list, etc).
    #
    # Defaults match the FakeAsyncSession's empty-queue mock — empty
    # mappings / scalars / scalar=0 — which cleanly reads as "no
    # signal" through every module's rollup logic. Tests that need a
    # specific signal (e.g. a populated estimates list) push their
    # own results AFTER calling this helper; those land at query
    # 24+, past the context-rollup window.
    for _ in range(15):
        pad = MagicMock()
        pad.scalar_one_or_none.return_value = None
        pad.scalar_one.return_value = 0
        pad.mappings.return_value.all.return_value = []
        pad.mappings.return_value.first.return_value = None
        pad.scalars.return_value.all.return_value = []
        pad.scalars.return_value.first.return_value = None
        fake_db.push(pad)


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


# ---------- Thread persistence ----------


async def test_ask_auto_creates_thread_when_thread_id_omitted(client, fake_db):
    """First turn with no thread_id should mint a new AssistantThread,
    persist 2 messages (user + assistant), and round-trip the thread_id
    in the response so the next turn can append."""
    from models.assistant import AssistantMessage, AssistantThread

    project = _project_row()
    _push_full_context(fake_db, project)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask",
        json={"question": "Tóm tắt nhanh tình trạng dự án"},
    )
    assert res.status_code == 200, res.text
    body = res.json()["data"]

    threads = [o for o in fake_db.added if isinstance(o, AssistantThread)]
    assert len(threads) == 1
    # Title derived from the question, capped at 80 chars.
    assert threads[0].title.startswith("Tóm tắt nhanh tình trạng dự án")
    assert threads[0].user_id == USER_ID
    assert threads[0].project_id == project.id

    messages = [o for o in fake_db.added if isinstance(o, AssistantMessage)]
    assert len(messages) == 2
    assert {m.role for m in messages} == {"user", "assistant"}

    assert body["thread_id"] == str(threads[0].id)


async def test_ask_appends_to_existing_thread_when_thread_id_provided(client, fake_db):
    """Follow-up turn: client passes thread_id, server loads prior messages
    from the DB, appends new turn, does NOT create a second thread."""
    from models.assistant import AssistantMessage, AssistantThread

    project = _project_row()
    existing_thread = SimpleNamespace(
        id=uuid4(),
        organization_id=ORG_ID,
        project_id=project.id,
        user_id=USER_ID,
        title="Earlier convo",
        last_message_at=datetime(2026, 4, 26, tzinfo=UTC),
        created_at=datetime(2026, 4, 26, tzinfo=UTC),
    )
    prior_messages = [
        SimpleNamespace(
            id=uuid4(),
            thread_id=existing_thread.id,
            role="user",
            content="Earlier question",
            sources=[],
            tool_calls=[],
            context_token_estimate=None,
            created_at=datetime(2026, 4, 26, 10, 0, tzinfo=UTC),
        ),
        SimpleNamespace(
            id=uuid4(),
            thread_id=existing_thread.id,
            role="assistant",
            content="Earlier answer",
            sources=[],
            tool_calls=[],
            context_token_estimate=120,
            created_at=datetime(2026, 4, 26, 10, 0, tzinfo=UTC),
        ),
    ]

    # Service order: project SELECT, activity UNION, 6 scalars, thread
    # SELECT, prior-messages SELECT.
    _push_full_context(fake_db, project)
    thread_q = MagicMock()
    thread_q.scalar_one_or_none.return_value = existing_thread
    msgs_q = MagicMock()
    msgs_q.scalars.return_value.all.return_value = prior_messages
    fake_db.push(thread_q)
    fake_db.push(msgs_q)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask",
        json={
            "thread_id": str(existing_thread.id),
            "question": "Follow-up?",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["thread_id"] == str(existing_thread.id)

    # No NEW thread created — we appended.
    new_threads = [o for o in fake_db.added if isinstance(o, AssistantThread)]
    assert new_threads == []
    # 2 fresh AssistantMessage rows (user + assistant) added.
    new_messages = [o for o in fake_db.added if isinstance(o, AssistantMessage)]
    assert len(new_messages) == 2


# ---------- Threads CRUD ----------


async def test_list_threads_returns_user_recent_threads(client, fake_db):
    """Sidebar query: scoped to caller's user_id + project, ordered by
    last_message_at DESC."""
    project_id = uuid4()
    threads = [
        SimpleNamespace(
            id=uuid4(),
            organization_id=ORG_ID,
            project_id=project_id,
            user_id=USER_ID,
            title=f"Thread {i}",
            last_message_at=datetime(2026, 4, 26 - i, tzinfo=UTC),
            created_at=datetime(2026, 4, 26 - i, tzinfo=UTC),
        )
        for i in range(3)
    ]
    q = MagicMock()
    q.scalars.return_value.all.return_value = threads
    fake_db.push(q)

    res = await client.get(f"/api/v1/assistant/projects/{project_id}/threads")
    assert res.status_code == 200
    body = res.json()["data"]
    assert len(body) == 3
    assert body[0]["title"] == "Thread 0"


async def test_get_thread_returns_full_transcript(client, fake_db):
    """Detail endpoint: thread metadata + every message in created_at order."""
    thread = SimpleNamespace(
        id=uuid4(),
        organization_id=ORG_ID,
        project_id=uuid4(),
        user_id=USER_ID,
        title="My thread",
        last_message_at=datetime(2026, 4, 27, tzinfo=UTC),
        created_at=datetime(2026, 4, 26, tzinfo=UTC),
    )
    messages = [
        SimpleNamespace(
            id=uuid4(),
            thread_id=thread.id,
            role="user",
            content="Q1",
            sources=[],
            tool_calls=[],
            context_token_estimate=None,
            created_at=datetime(2026, 4, 26, 10, 0, tzinfo=UTC),
        ),
        SimpleNamespace(
            id=uuid4(),
            thread_id=thread.id,
            role="assistant",
            content="A1",
            sources=[{"module": "pulse", "label": "1 task mở", "route": "/pulse"}],
            tool_calls=[],
            context_token_estimate=120,
            created_at=datetime(2026, 4, 26, 10, 1, tzinfo=UTC),
        ),
    ]
    thread_q = MagicMock()
    thread_q.scalar_one_or_none.return_value = thread
    msgs_q = MagicMock()
    msgs_q.scalars.return_value.all.return_value = messages
    fake_db.push(thread_q)
    fake_db.push(msgs_q)

    res = await client.get(f"/api/v1/assistant/threads/{thread.id}")
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["title"] == "My thread"
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"
    assert body["messages"][1]["sources"][0]["module"] == "pulse"


async def test_get_thread_404_for_cross_user_thread(client, fake_db):
    """A thread owned by a different user must 404 (existence hidden)."""
    thread_q = MagicMock()
    thread_q.scalar_one_or_none.return_value = None
    fake_db.push(thread_q)

    res = await client.get(f"/api/v1/assistant/threads/{uuid4()}")
    assert res.status_code == 404


async def test_delete_thread_removes_existing(client, fake_db):
    thread = SimpleNamespace(
        id=uuid4(),
        organization_id=ORG_ID,
        project_id=uuid4(),
        user_id=USER_ID,
        title="To delete",
        last_message_at=datetime(2026, 4, 27, tzinfo=UTC),
        created_at=datetime(2026, 4, 26, tzinfo=UTC),
    )
    q = MagicMock()
    q.scalar_one_or_none.return_value = thread
    fake_db.push(q)

    res = await client.delete(f"/api/v1/assistant/threads/{thread.id}")
    assert res.status_code == 204
    assert fake_db.deleted == [thread]


async def test_delete_thread_is_idempotent_for_missing(client, fake_db):
    """Deleting a non-existent thread is a 204 — desired end state achieved."""
    q = MagicMock()
    q.scalar_one_or_none.return_value = None
    fake_db.push(q)

    res = await client.delete(f"/api/v1/assistant/threads/{uuid4()}")
    assert res.status_code == 204
    assert fake_db.deleted == []


# ---------- Streaming ----------


async def test_ask_stream_emits_meta_token_done_frames(client, fake_db):
    """Stub-path streaming: meta → token (single chunk with stub answer) → done."""
    project = _project_row()
    _push_full_context(fake_db, project)

    async with client.stream(
        "POST",
        f"/api/v1/assistant/projects/{project.id}/ask/stream",
        json={"question": "Tóm tắt nhanh"},
    ) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        body = b""
        async for chunk in res.aiter_bytes():
            body += chunk

    text_body = body.decode()
    # Order matters: meta first, then token(s), then done last.
    meta_idx = text_body.find("event: meta")
    token_idx = text_body.find("event: token")
    done_idx = text_body.find("event: done")
    assert meta_idx >= 0, f"missing meta frame: {text_body!r}"
    assert token_idx > meta_idx, "token must come after meta"
    assert done_idx > token_idx, "done must come last"
    # The meta frame should carry a thread_id.
    assert '"thread_id"' in text_body
    # Stub answer ends up inside a token frame.
    assert "Tóm tắt nhanh" in text_body


async def test_ask_stream_emits_error_for_cross_tenant_project(client, fake_db):
    """Project not in caller's org → in-band `event: error` (the response
    is already 200 by the time the body starts streaming, so we can't
    use 404)."""
    proj_q = MagicMock()
    proj_q.scalar_one_or_none.return_value = None
    fake_db.push(proj_q)

    async with client.stream(
        "POST",
        f"/api/v1/assistant/projects/{uuid4()}/ask/stream",
        json={"question": "hi"},
    ) as res:
        assert res.status_code == 200
        body = b""
        async for chunk in res.aiter_bytes():
            body += chunk

    text_body = body.decode()
    assert "event: error" in text_body
    assert "Project not found" in text_body
    # No thread should be created when the project lookup fails.
    from models.assistant import AssistantThread

    assert not any(isinstance(o, AssistantThread) for o in fake_db.added)


# ---------- RBAC: role gate on cost-bearing endpoints -------------------
#
# `/ask` and `/ask/stream` invoke the LLM, which costs the org real
# money. Both are gated at `Role.MEMBER` and above so viewers (the
# role given to clients, auditors, contractor liaisons) can't burn
# tokens against the org's cap.
#
# The READ endpoints (`/threads`, `/threads/{id}`, DELETE) keep
# `require_auth` only — they're scoped to `auth.user_id` so a viewer
# only ever sees their own conversation history. Pin both directions
# so a refactor that loosens `/ask` (or tightens `/threads`) surfaces
# loudly here.


def _build_app_for_role(fake_db: FakeAsyncSession, role: str):
    """Build the assistant router app with `auth.role` set to a
    specific value. Mirrors the `app` fixture above but parameterized
    so the role-gate tests can sweep across {viewer, member, admin,
    owner} without four separate fixtures."""
    from fastapi import FastAPI, HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from middleware.auth import AuthContext, require_auth
    from routers import assistant as assistant_router

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="tester@example.com",
    )

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(assistant_router.router)

    async def _db_override():
        yield fake_db

    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[get_db] = _db_override
    return app


async def test_ask_endpoint_returns_403_for_viewer_role(fake_db):
    """A viewer hitting POST /ask must get 403 — the cost-bearing
    endpoint is gated. Pin so a refactor that drops the role floor
    silently lets viewers burn LLM tokens."""
    app = _build_app_for_role(fake_db, role="viewer")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/assistant/projects/{uuid4()}/ask",
            json={"question": "anything"},
        )
    assert res.status_code == 403, (
        f"Viewer should be 403'd from /ask; got {res.status_code}. "
        "The role floor on /ask has been lowered or removed — "
        "viewers can now burn LLM tokens, which the branch's RBAC "
        "is supposed to prevent."
    )
    # Error body carries the role-floor message so the UI can render
    # something better than a raw 403. Pin the substring.
    body = res.json()
    detail = body.get("detail") or body.get("errors", [{}])[0].get("message", "")
    assert "member" in str(detail).lower(), (
        f"403 body did not mention the role floor; got {body!r}. "
        "The frontend keys off this string to render a friendly "
        "'you don't have permission' message."
    )


async def test_ask_stream_endpoint_returns_403_for_viewer_role(fake_db):
    """Streaming variant of the same gate — the 403 must fire BEFORE
    the StreamingResponse is constructed (otherwise the headers go
    out as 200 and the client gets confused by an in-band error
    frame on a "successful" response)."""
    app = _build_app_for_role(fake_db, role="viewer")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/assistant/projects/{uuid4()}/ask/stream",
            json={"question": "anything"},
        )
    assert res.status_code == 403, (
        f"Viewer should be 403'd from /ask/stream; got {res.status_code}. "
        "If this was a 200 with an in-band error frame, the role gate "
        "is firing too late — it must be a HARD 4xx so EventSource "
        "clients see the error."
    )


@pytest.mark.parametrize("role", ["member", "admin", "owner"])
async def test_ask_endpoint_passes_for_member_admin_owner(fake_db, role):
    """The hierarchy floor — `member`, `admin`, `owner` all pass.
    Pin all three so a refactor that re-keyed off `Role.ADMIN`
    instead of `Role.MEMBER` (silently locking out members) is
    caught here, not via a customer ticket.

    Stub the LLM path (no ANTHROPIC_API_KEY set by the autouse
    fixture above) so the request returns 200 with the deterministic
    stub answer. We're not testing the LLM here, just the gate.
    """
    project = _project_row()
    _push_full_context(fake_db, project, activity_count=0)

    app = _build_app_for_role(fake_db, role=role)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/assistant/projects/{project.id}/ask",
            json={"question": "What's the project status?"},
        )
    assert res.status_code == 200, (
        f"role={role!r} should pass the /ask gate; got {res.status_code}. "
        f"Body: {res.text}. The role floor was likely raised above "
        "Role.MEMBER, locking out a tier that should have access."
    )


async def test_threads_list_remains_open_to_viewer(fake_db):
    """Read-only `/threads` is intentionally NOT gated at the member
    floor — a viewer who once had member access and got demoted can
    still see their own conversation history. Pin so a future
    "tighten everything to member+" refactor doesn't accidentally
    lock viewers out of their own data.
    """
    # No threads — empty result. The handler short-circuits to ok([]).
    app = _build_app_for_role(fake_db, role="viewer")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/assistant/projects/{uuid4()}/threads")
    assert res.status_code == 200, (
        f"Viewer should be able to LIST their own threads; got {res.status_code}. "
        "If this is a 403, /threads got over-tightened — viewers have a "
        "legitimate read use case (see their own past conversations)."
    )
