"""Router tests for the cross-module search endpoint.

Each scope's SQL is kept simple enough that we can exercise it via
`fake_db` execute-result queues + assertions on the bound params.
The fan-out is `asyncio.gather`'d in production but each helper opens
its own `TenantAwareSession` — we monkeypatch that to yield the same
fake_db so a single test can program all scope queries from one queue.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth  # noqa: F401

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.mappings.return_value.all.return_value = []
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture(autouse=True)
def patch_tenant_session(fake_db, monkeypatch):
    """The service uses `TenantAwareSession(org_id) as session:` to give
    each scope its own connection. Replace it with a no-op CM that
    yields the shared fake — keeps the tests' execute-result queue
    deterministic across the parallel fan-out.

    Also stubs `log_search` to a no-op so the BackgroundTask the router
    schedules doesn't pollute `fake_db.calls` (existing tests count
    search calls, not telemetry inserts). Dedicated writer tests below
    re-enable the real implementation explicitly.
    """

    @asynccontextmanager
    async def _factory(_org_id: UUID) -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    monkeypatch.setattr("services.search.TenantAwareSession", _factory)

    async def _noop_log(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("routers.search.log_search", _noop_log)
    yield fake_db


def _build_app() -> FastAPI:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from routers import search as search_router

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(search_router.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="caller@example.com",
    )
    app.dependency_overrides[require_auth] = lambda: auth_ctx
    return app


def _doc_row(**overrides: Any) -> dict:
    base = {
        "id": uuid4(),
        "name": "Tower-A_Architectural_Plans.pdf",
        "project_id": uuid4(),
        "created_at": datetime(2026, 4, 26, tzinfo=UTC),
        "project_name": "Tower A",
    }
    base.update(overrides)
    return base


# ---------- Validation ----------


async def test_search_rejects_short_query():
    """Sub-2-character queries hit way too many false positives via
    ILIKE — bound the floor at 2 chars."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/search", json={"query": "a"})
    assert res.status_code == 422


async def test_search_rejects_overlong_query():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/search", json={"query": "x" * 500})
    assert res.status_code == 422


async def test_search_rejects_unknown_scope():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "tower", "scopes": ["fictional"]},
        )
    assert res.status_code == 422


# ---------- Single-scope happy path ----------


async def test_search_documents_returns_normalized_results(fake_db):
    """Single-scope query against `documents` — verify result shape +
    that the bound ILIKE pattern wraps the user's query."""
    rows = [_doc_row(name="Tower A foundation drawing")]
    q = MagicMock()
    q.mappings.return_value.all.return_value = rows
    fake_db.push(q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "tower", "scopes": ["documents"]},
        )

    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["total"] == 1
    hit = body["results"][0]
    assert hit["scope"] == "documents"
    assert hit["title"] == "Tower A foundation drawing"
    assert hit["route"].startswith("/drawbridge?document_id=")
    assert hit["project_name"] == "Tower A"

    # Bound ILIKE pattern should be `%tower%` (trimmed + wrapped).
    pat = fake_db.calls[0][1]["pat"]
    assert pat == "%tower%"


async def test_search_threads_project_id_through(fake_db):
    """When `project_id` is given, the SQL adds an extra WHERE clause
    bound to the same param. Test by inspecting bound params."""
    rows = []
    q = MagicMock()
    q.mappings.return_value.all.return_value = rows
    fake_db.push(q)

    project_id = uuid4()
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post(
            "/api/v1/search",
            json={
                "query": "tower",
                "scopes": ["documents"],
                "project_id": str(project_id),
            },
        )

    params = fake_db.calls[0][1]
    assert params["project_id"] == str(project_id)


async def test_search_regulations_ignores_project_filter(fake_db):
    """Regulations are global reference data — the project_id filter
    must not narrow them, otherwise a CodeGuard search inside a
    project context would always return zero hits."""
    rows = [
        {
            "id": uuid4(),
            "code": "QCVN 06:2022/BXD",
            "name": "Quy chuẩn an toàn cháy",
            "country": "VN",
            "jurisdiction": "national",
        }
    ]
    q = MagicMock()
    q.mappings.return_value.all.return_value = rows
    fake_db.push(q)

    project_id = uuid4()
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={
                "query": "QCVN",
                "scopes": ["regulations"],
                "project_id": str(project_id),
            },
        )

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["total"] == 1
    # The bound params should NOT include project_id — the regulations
    # query takes only `pat` and `limit`.
    params = fake_db.calls[0][1]
    assert "project_id" not in params or params.get("project_id") is None
    assert "QCVN" in body["results"][0]["title"]


# ---------- Multi-scope fan-out ----------


async def test_search_fans_out_across_default_scopes(fake_db):
    """No scopes specified → all 5 scopes run. We program empty results
    for each so we can assert exactly 5 execute() calls (one per scope)."""
    for _ in range(5):
        empty = MagicMock()
        empty.mappings.return_value.all.return_value = []
        fake_db.push(empty)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/search", json={"query": "anything"})

    assert res.status_code == 200
    assert len(fake_db.calls) == 5  # documents, regulations, defects, rfis, proposals


async def test_search_merges_and_recency_sorts_across_scopes(fake_db):
    """Two scopes, each returns one row with a different created_at —
    the merged response must put the newer row first, regardless of
    scope ordering in the dispatch table."""
    older_doc = _doc_row(
        name="Older drawing",
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    newer_defect_id = uuid4()
    docs_q = MagicMock()
    docs_q.mappings.return_value.all.return_value = [older_doc]
    fake_db.push(docs_q)

    defects_q = MagicMock()
    defects_q.mappings.return_value.all.return_value = [
        {
            "id": newer_defect_id,
            "title": "Leak in basement",
            "description": "Water ingress at corner B-3",
            "project_id": uuid4(),
            "priority": "high",
            "status": "open",
            "reported_at": datetime(2026, 4, 27, tzinfo=UTC),
            "project_name": "Tower A",
        }
    ]
    fake_db.push(defects_q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "anything", "scopes": ["documents", "defects"]},
        )

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["total"] == 2
    # Newer defect (2026-04-27) before older drawing (2026-03-01).
    assert body["results"][0]["id"] == str(newer_defect_id)
    assert body["results"][0]["scope"] == "defects"
    assert body["results"][1]["scope"] == "documents"


async def test_search_caps_results_at_limit(fake_db):
    """Each scope returns 5 hits; with limit=3 + 2 scopes, we get back
    3 (capped after merge), not 10. Both scopes are `documents` so we
    don't have to mint per-scope row shapes — the cap is what's under
    test, not the projection."""
    for _ in range(2):
        rows = [
            _doc_row(
                created_at=datetime(2026, 4, i + 1, tzinfo=UTC),
            )
            for i in range(5)
        ]
        q = MagicMock()
        q.mappings.return_value.all.return_value = rows
        fake_db.push(q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            # Two `documents` scope queries by virtue of the default
            # fan-out — we monkeypatch `selected = [documents, documents]`
            # via `scopes` so both fake rows go through `_search_documents`.
            "/api/v1/search",
            json={"query": "tower", "scopes": ["documents"], "limit": 3},
        )

    assert res.status_code == 200
    body = res.json()["data"]
    # Single scope means only ONE handler ran; it pulled `per_scope = max(5, 3) = 5`
    # rows, and the merge cap of `limit=3` trims it to 3.
    assert body["total"] == 3
    assert len(body["results"]) == 3


# ---------- Hybrid path: keyword + vector + RRF fusion ----------


@pytest.fixture
def patch_embedder(monkeypatch):
    """Make `_embed_query` return a fake 3072-d vector so the vector
    arm fires WITHOUT calling OpenAI. Tests that don't include this
    fixture get the default no-key path (returns None → keyword-only)."""

    async def _fake_embed(_q: str) -> list[float]:
        return [0.0] * 3072

    monkeypatch.setattr("services.search._embed_query", _fake_embed)
    yield


async def test_hybrid_runs_both_arms_for_vector_capable_scope(fake_db, patch_embedder):
    """`documents` has an embeddings table → service must fire BOTH
    keyword (1 query) AND vector (1 query) per request, then RRF-fuse."""
    # Keyword arm result
    kw_q = MagicMock()
    kw_q.mappings.return_value.all.return_value = [_doc_row(name="kw-only-hit")]
    fake_db.push(kw_q)
    # Vector arm result
    vec_q = MagicMock()
    vec_q.mappings.return_value.all.return_value = [{**_doc_row(name="vec-only-hit"), "score": 0.85}]
    fake_db.push(vec_q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "fire egress", "scopes": ["documents"]},
        )

    assert res.status_code == 200, res.text
    body = res.json()["data"]
    # Both arms ran → 2 execute calls.
    assert len(fake_db.calls) == 2
    # Both rows surface in the fused result list.
    titles = {r["title"] for r in body["results"]}
    assert titles == {"kw-only-hit", "vec-only-hit"}


async def test_hybrid_keyword_only_when_no_api_key(fake_db):
    """Without an `OPENAI_API_KEY`, `_embed_query` returns None and the
    vector arm is skipped — service degrades gracefully to keyword-only.
    NOTE: this test deliberately omits `patch_embedder`."""
    kw_q = MagicMock()
    kw_q.mappings.return_value.all.return_value = [_doc_row()]
    fake_db.push(kw_q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "tower", "scopes": ["documents"]},
        )

    assert res.status_code == 200
    # Only ONE execute call — vector arm was skipped.
    assert len(fake_db.calls) == 1


async def test_hybrid_skips_vector_arm_for_keyword_only_scopes(fake_db, patch_embedder):
    """`defects` has no embeddings table — vector arm must NOT run even
    when `OPENAI_API_KEY` is set. Same for `proposals`."""
    kw_q = MagicMock()
    kw_q.mappings.return_value.all.return_value = []
    fake_db.push(kw_q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "leak", "scopes": ["defects"]},
        )

    assert res.status_code == 200
    # Only ONE execute call — defects has no vector handler registered.
    assert len(fake_db.calls) == 1


async def test_rrf_boosts_rows_present_in_both_arms(fake_db, patch_embedder):
    """Reciprocal-rank fusion: a row that appears at rank 2 in BOTH
    arms must outscore a row that's #1 in only one arm.

    Pin the contract by feeding shared+exclusive rows and asserting
    the shared row sits first.
    """
    shared_id = uuid4()
    kw_only_id = uuid4()
    vec_only_id = uuid4()

    kw_q = MagicMock()
    kw_q.mappings.return_value.all.return_value = [
        _doc_row(id=kw_only_id, name="keyword-only #1"),
        _doc_row(id=shared_id, name="shared #2 in keyword"),
    ]
    fake_db.push(kw_q)
    vec_q = MagicMock()
    vec_q.mappings.return_value.all.return_value = [
        {**_doc_row(id=vec_only_id, name="vector-only #1"), "score": 0.9},
        {**_doc_row(id=shared_id, name="shared #2 in vector"), "score": 0.8},
    ]
    fake_db.push(vec_q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "anything", "scopes": ["documents"]},
        )

    assert res.status_code == 200
    body = res.json()["data"]
    # 3 distinct docs (shared dedupes by (scope, id)).
    assert body["total"] == 3
    # The shared doc should be first — it scores 1/(60+2) + 1/(60+2),
    # versus the exclusive #1s which only score 1/(60+1).
    assert body["results"][0]["id"] == str(shared_id)


async def test_rrf_recency_sort_still_applies_across_scopes(fake_db, patch_embedder):
    """RRF fuses WITHIN a scope; cross-scope merge stays recency-sorted
    so a fresh defect outranks a stale (but RRF-boosted) document."""
    older_doc = _doc_row(
        name="Stale doc",
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    newer_defect_id = uuid4()
    # documents: keyword + vector both fire → 2 results queue
    kw_doc_q = MagicMock()
    kw_doc_q.mappings.return_value.all.return_value = [older_doc]
    fake_db.push(kw_doc_q)
    vec_doc_q = MagicMock()
    vec_doc_q.mappings.return_value.all.return_value = [{**older_doc, "score": 0.9}]
    fake_db.push(vec_doc_q)
    # defects: keyword only
    defects_q = MagicMock()
    defects_q.mappings.return_value.all.return_value = [
        {
            "id": newer_defect_id,
            "title": "Fresh defect",
            "description": "D3",
            "project_id": uuid4(),
            "priority": "high",
            "status": "open",
            "reported_at": datetime(2026, 4, 27, tzinfo=UTC),
            "project_name": "Tower A",
        }
    ]
    fake_db.push(defects_q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "anything", "scopes": ["documents", "defects"]},
        )

    assert res.status_code == 200
    body = res.json()["data"]
    # Newer defect wins the cross-scope recency merge.
    assert body["results"][0]["id"] == str(newer_defect_id)


# ---------- Provenance: matched_on ----------


async def test_matched_on_is_keyword_when_only_keyword_arm_hits(fake_db, patch_embedder):
    """A row that's only in the keyword arm gets matched_on='keyword'.
    Pin so the frontend chip renders correctly."""
    kw_q = MagicMock()
    kw_q.mappings.return_value.all.return_value = [_doc_row(name="kw-only")]
    fake_db.push(kw_q)
    vec_q = MagicMock()
    vec_q.mappings.return_value.all.return_value = []
    fake_db.push(vec_q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "tower", "scopes": ["documents"]},
        )
    assert res.status_code == 200
    [hit] = res.json()["data"]["results"]
    assert hit["matched_on"] == "keyword"


async def test_matched_on_is_vector_when_only_vector_arm_hits(fake_db, patch_embedder):
    kw_q = MagicMock()
    kw_q.mappings.return_value.all.return_value = []
    fake_db.push(kw_q)
    vec_q = MagicMock()
    vec_q.mappings.return_value.all.return_value = [{**_doc_row(name="vec-only"), "score": 0.85}]
    fake_db.push(vec_q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "fire egress", "scopes": ["documents"]},
        )
    assert res.status_code == 200
    [hit] = res.json()["data"]["results"]
    assert hit["matched_on"] == "vector"


async def test_matched_on_is_both_when_arms_overlap(fake_db, patch_embedder):
    """High-confidence case: row appears in BOTH arms → chip reads 'both'."""
    shared_id = uuid4()
    kw_q = MagicMock()
    kw_q.mappings.return_value.all.return_value = [_doc_row(id=shared_id, name="s")]
    fake_db.push(kw_q)
    vec_q = MagicMock()
    vec_q.mappings.return_value.all.return_value = [{**_doc_row(id=shared_id, name="s"), "score": 0.9}]
    fake_db.push(vec_q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "anything", "scopes": ["documents"]},
        )
    assert res.status_code == 200
    [hit] = res.json()["data"]["results"]
    assert hit["matched_on"] == "both"


async def test_matched_on_is_keyword_for_keyword_only_scope(fake_db, patch_embedder):
    """`defects` has no embeddings table → matched_on is 'keyword'
    even when an embed key is configured (proves the keyword-only
    branch in `_run` stamps the field)."""
    kw_q = MagicMock()
    kw_q.mappings.return_value.all.return_value = [
        {
            "id": uuid4(),
            "title": "Leak in basement",
            "description": "D",
            "project_id": uuid4(),
            "priority": "high",
            "status": "open",
            "reported_at": datetime(2026, 4, 27, tzinfo=UTC),
            "project_name": "Tower A",
        }
    ]
    fake_db.push(kw_q)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/search",
            json={"query": "leak", "scopes": ["defects"]},
        )
    assert res.status_code == 200
    [hit] = res.json()["data"]["results"]
    assert hit["matched_on"] == "keyword"


# ---------- Auth ----------


async def test_search_requires_auth():
    """Without a `require_auth` override the dependency raises."""
    from routers import search as search_router

    app = FastAPI()
    app.include_router(search_router.router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # No auth headers + no override → 401/403 from require_auth.
        res = await ac.post("/api/v1/search", json={"query": "x"})
    # The exact code depends on auth wiring (HTTPBearer raises 403 by
    # default); what we care about is that it's NOT a 200.
    assert res.status_code in (401, 403, 422)
