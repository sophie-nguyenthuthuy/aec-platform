"""SSE streaming tests for the AI assistant.

The non-streaming `/ask` endpoint is well-covered by
`test_assistant_router.py`. This file targets the
`POST /projects/{id}/ask/stream` SSE endpoint, which has its own
contract:

  event: meta  → `{"thread_id": "..."}` (always first)
  event: token → `{"text": "..."}` (zero or more)
  event: done  → `{"sources": [...], "context_token_estimate": N}` (last)
  event: error → `{"message": "..."}` (replaces done on failure)

Why a separate file: the streaming response goes through
`StreamingResponse` and `EventSource`-style framing — different
plumbing from the JSON envelope used by `/ask`. A regression in the
SSE framing (missing terminator, wrong event name, content-type
drift) wouldn't be caught by `test_assistant_router.py` at all.

Self-contained fixtures so test ordering / upstream reverts of the
neighbouring test_assistant_router.py file can't break this one.
The `FakeAsyncSession.execute()` default explicitly stubs
`.mappings().first()` and `.scalars().first()` to None — without
that, MagicMock auto-creation flows into `_safe_json_dumps` and
hits a Python 3.13 infinite loop. See `services.assistant._safe_json_dumps`
for the matching isinstance-only guard.
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


class _FakeAsyncSession:
    """Queued-result session — same shape as test_assistant_router's
    fake but with `.first()` / `.one_or_none()` stubs hardcoded so
    the AnyIO worker-thread hang in `_safe_json_dumps` can't fire.
    """

    def __init__(self) -> None:
        self._results: list[Any] = []
        self.added: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None: ...
    async def commit(self) -> None: ...
    async def close(self) -> None: ...
    async def refresh(self, _obj: Any) -> None: ...

    async def execute(self, *_a: Any, **_kw: Any) -> Any:
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.scalar_one.return_value = 0
        r.mappings.return_value.all.return_value = []
        r.mappings.return_value.first.return_value = None
        r.mappings.return_value.one_or_none.return_value = None
        r.scalars.return_value.all.return_value = []
        r.scalars.return_value.first.return_value = None
        r.scalars.return_value.one_or_none.return_value = None
        return r


@pytest.fixture
def fake_db() -> _FakeAsyncSession:
    return _FakeAsyncSession()


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

    async def _db_override() -> AsyncIterator[_FakeAsyncSession]:
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
    """Force the deterministic stub path so we don't try to hit the
    real Anthropic API. The streaming-with-LLM path is exercised
    elsewhere (and is already covered structurally by the same
    `_resolve_thread` / `_persist_exchange` helpers `ask()` uses)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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


def _seed_min_context(fake_db: _FakeAsyncSession, project) -> None:
    """Push only the project SELECT result. Subsequent SQL falls into
    the FakeAsyncSession default (empty mappings + 0 scalars + None
    firsts) — the streaming path doesn't depend on populated module
    rollups for any frame to fire."""
    proj_q = MagicMock()
    proj_q.scalar_one_or_none.return_value = project
    fake_db.push(proj_q)


# ---------- Frame parsing helper ----------


def _parse_sse(stream_text: str) -> list[dict[str, str]]:
    """Parse a `text/event-stream` body into a list of frames.

    Each frame is `{"event": <kind>, "data": <raw_json_string>}`.
    Frames are separated by `\\n\\n`; within a frame, `event:` and
    `data:` lines carry the kind + payload.

    Forgiving to leading/trailing whitespace because some SSE
    libraries add comment lines (`:` heartbeats) or extra blanks;
    we just split on `\\n\\n` and pick out the lines we care about.
    """
    frames: list[dict[str, str]] = []
    for raw in stream_text.split("\n\n"):
        if not raw.strip():
            continue
        frame: dict[str, str] = {}
        for line in raw.splitlines():
            if line.startswith("event:"):
                frame["event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                frame["data"] = line[len("data:") :].strip()
        if frame:
            frames.append(frame)
    return frames


# ---------- Tests ----------


async def test_ask_stream_emits_meta_token_done_in_order(client, fake_db):
    """Happy path: stub branch must emit exactly meta → token → done.

    Order matters: a client that receives `done` before `token` would
    finalise the answer as empty. A client that receives `token` before
    `meta` has no thread_id to attribute the message to. The contract
    is meta-first, then zero-or-more tokens, then done.
    """
    project = _project_row()
    _seed_min_context(fake_db, project)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask/stream",
        json={"question": "Status?"},
    )

    # The streaming endpoint returns 200 from the response-headers
    # phase regardless of in-stream errors — the framing is what
    # matters, not the status. (Cross-tenant 404 is signalled via an
    # `event: error` frame, NOT a 4xx; covered separately below.)
    assert res.status_code == 200
    frames = _parse_sse(res.text)
    assert [f["event"] for f in frames] == ["meta", "token", "done"]


async def test_ask_stream_meta_carries_thread_id(client, fake_db):
    """The first `event: meta` frame must include a stable thread_id
    string the client can echo on follow-up turns. Without it the
    client can't pass `thread_id` on subsequent `/ask` calls and
    every turn becomes a fresh thread."""
    import json

    project = _project_row()
    _seed_min_context(fake_db, project)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask/stream",
        json={"question": "Hi"},
    )
    frames = _parse_sse(res.text)
    meta = next(f for f in frames if f["event"] == "meta")
    payload = json.loads(meta["data"])
    # UUID format check — exactly 36 chars with the standard 8-4-4-4-12
    # hyphenation. A typo that emitted the bare thread object would
    # surface here.
    assert isinstance(payload["thread_id"], str)
    assert len(payload["thread_id"]) == 36
    assert payload["thread_id"].count("-") == 4


async def test_ask_stream_token_echoes_question_in_stub_mode(client, fake_db):
    """Stub branch must include the user's question in the `token`
    payload so a dev/test caller without an API key still sees
    "something happened." A regression that emitted an empty token
    would silently break the dev-loop UX."""
    import json

    project = _project_row()
    _seed_min_context(fake_db, project)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask/stream",
        json={"question": "What's blocking us this week?"},
    )
    frames = _parse_sse(res.text)
    token = next(f for f in frames if f["event"] == "token")
    payload = json.loads(token["data"])
    assert "What's blocking us this week?" in payload["text"]


async def test_ask_stream_done_carries_sources_and_token_estimate(client, fake_db):
    """The terminal `done` frame must surface `sources` (list) +
    `context_token_estimate` (int). Frontend uses the count to
    decide whether to truncate the rendered context preview; a
    missing field would crash the renderer."""
    import json

    project = _project_row()
    _seed_min_context(fake_db, project)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask/stream",
        json={"question": "x"},
    )
    frames = _parse_sse(res.text)
    done = next(f for f in frames if f["event"] == "done")
    payload = json.loads(done["data"])
    assert isinstance(payload.get("sources"), list)
    assert isinstance(payload.get("context_token_estimate"), int)
    # `>= 0` rather than `> 0` — a zero-context project (rare but
    # possible: brand-new project with nothing populated) is legal.
    assert payload["context_token_estimate"] >= 0


async def test_ask_stream_emits_error_frame_for_cross_tenant_project(client, fake_db):
    """Cross-tenant project IDs are signalled IN-BAND via an
    `event: error` frame, NOT a 4xx HTTP status. Once the SSE
    response headers are out, the status is locked at 200 — frontend
    `EventSource` can't react to a 404 mid-stream, so we use a
    distinguishable error frame instead.

    A regression that raised an HTTPException here would 500 the
    request and the client's EventSource would silently disconnect
    with no human-readable signal.
    """
    import json

    # No project row pushed → `build_project_context` returns empty →
    # `ask_stream` emits the error frame.
    proj_q = MagicMock()
    proj_q.scalar_one_or_none.return_value = None
    fake_db.push(proj_q)

    res = await client.post(
        f"/api/v1/assistant/projects/{uuid4()}/ask/stream",
        json={"question": "leak attempt"},
    )
    assert res.status_code == 200
    frames = _parse_sse(res.text)
    # Only one frame: the error. No meta, no token, no done.
    assert len(frames) == 1
    assert frames[0]["event"] == "error"
    payload = json.loads(frames[0]["data"])
    # The message MUST NOT distinguish "project doesn't exist" from
    # "project is in another org" — that's an info-leak primitive.
    # Both branches emit the same opaque string.
    assert "Project not found" in payload["message"]


async def test_ask_stream_response_headers_disable_proxy_buffering(client, fake_db):
    """Pin the headers that defeat reverse-proxy buffering:
       Cache-Control: no-cache
       X-Accel-Buffering: no   (nginx-specific, harmless elsewhere)

    Without these, an nginx in front of the API can buffer the
    entire stream + flush at the end — the user sees ~10s of "loading"
    instead of progressive token rendering. This test catches a
    regression that drops either header.
    """
    project = _project_row()
    _seed_min_context(fake_db, project)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask/stream",
        json={"question": "x"},
    )
    # `Cache-Control: no-cache` keeps intermediate caches from
    # collapsing the stream into a single 200 OK after the fact.
    assert "no-cache" in res.headers.get("cache-control", "").lower()
    # `X-Accel-Buffering: no` is the nginx ingress's documented opt-
    # out from response buffering. Lowercased because httpx
    # normalises header names.
    assert res.headers.get("x-accel-buffering") == "no"


async def test_ask_stream_content_type_is_text_event_stream(client, fake_db):
    """Pin `Content-Type: text/event-stream`. Browsers' EventSource
    refuses to parse a stream with a different content-type — a typo
    to `application/json` or `text/plain` would silently break every
    SSE consumer."""
    project = _project_row()
    _seed_min_context(fake_db, project)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask/stream",
        json={"question": "x"},
    )
    ctype = res.headers.get("content-type", "")
    # Allow optional `; charset=utf-8` suffix.
    assert ctype.startswith("text/event-stream"), f"unexpected content-type: {ctype!r}"


async def test_ask_stream_persists_exchange_for_replay(client, fake_db):
    """The streaming path must persist the exchange (thread + message
    rows) so a follow-up `GET /threads/{id}` returns the full
    conversation. A regression that skipped persistence in the stub
    branch would mean every refresh of the chat page shows an empty
    thread.

    We verify by asserting the fake session saw `add()` calls — the
    service uses `session.add(thread)` + `session.add(message)` for
    each turn.
    """
    project = _project_row()
    _seed_min_context(fake_db, project)

    res = await client.post(
        f"/api/v1/assistant/projects/{project.id}/ask/stream",
        json={"question": "persist me"},
    )
    assert res.status_code == 200
    # At least one row added — typically the AssistantThread + 2
    # AssistantMessage rows (user + assistant). The exact count
    # is downstream of `_persist_exchange`'s implementation; we just
    # care that persistence happened at all.
    assert len(fake_db.added) >= 1
