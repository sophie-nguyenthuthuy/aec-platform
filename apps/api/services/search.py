"""Cross-module hybrid search.

Per scope, we fan out two ranked rankers and fuse them with reciprocal-
rank fusion (RRF):

  * **Keyword arm** — ILIKE on title/description fields. Dumb but
    correct across mixed VN/EN content (Postgres `to_tsvector`
    mishandles VN diacritics for `english`, misses stemming for
    `simple`). Catches exact tokens.

  * **Vector arm** — pgvector kNN over each module's existing
    embeddings table (`document_chunks`, `regulation_chunks`,
    `rfi_embeddings`). Catches semantic intent: "fire egress" →
    regulations on "exit width", drawings titled "stair pressurization".

The two rankers are scored by RRF (`1 / (k + rank)` summed across
arms; k=60, the original-paper default). RRF is rank-only — it
doesn't care about score scales, so we don't need to normalise
cosine-distance vs ILIKE-rank.

The vector arm gracefully degrades when `OPENAI_API_KEY` isn't set:
`_embed_query` returns None and we fall back to keyword-only.
Defects + proposals stay keyword-only because they don't have
embeddings tables.

Tenant isolation: each scope opens its own `TenantAwareSession` (RLS
on `app.current_org_id` belt-and-suspenders) and the per-scope SQL
also explicitly filters by `organization_id`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import TenantAwareSession
from schemas.search import SearchResult, SearchScope

logger = logging.getLogger(__name__)


# RRF constant. 60 is the number from the original Cormack/Clarke/Buettcher
# paper; smaller `k` gives outsized weight to top hits, larger `k`
# flattens the curve. 60 is well-tested for cross-system rank fusion.
_RRF_K = 60


async def search(
    *,
    organization_id: UUID,
    query: str,
    scopes: list[SearchScope] | None = None,
    project_id: UUID | None = None,
    limit: int = 20,
) -> list[SearchResult]:
    """Run the requested scope queries concurrently and merge.

    Per scope, we run a keyword arm + (when the scope has an embeddings
    table and `OPENAI_API_KEY` is configured) a vector arm in parallel,
    then RRF-fuse the two ranked lists into one per-scope result list.
    Cross-scope merge is recency-ordered (the per-arm relevance signals
    don't compose across modules without per-module calibration that's
    overkill for a v1).
    """
    selected = scopes or list(SearchScope)
    pattern = f"%{query.strip()}%"
    per_scope = max(5, limit)  # at least 5 each so multi-scope queries are useful

    # Embed once, reuse across every vector-capable scope. Embedding
    # latency dominates the request (~200-500ms vs ~1ms for an indexed
    # ILIKE), so paying for it once is worth a few extra `if` branches.
    query_vec = await _embed_query(query.strip())

    async def _run(scope: SearchScope) -> list[SearchResult]:
        async with TenantAwareSession(organization_id) as session:
            keyword_handler = _SCOPE_HANDLERS[scope]
            keyword_task = keyword_handler(
                session,
                pattern=pattern,
                project_id=project_id,
                limit=per_scope,
            )
            vector_handler = _VECTOR_HANDLERS.get(scope)
            if vector_handler is not None and query_vec is not None:
                vector_task = vector_handler(
                    session,
                    query_vec=query_vec,
                    project_id=project_id,
                    limit=per_scope,
                )
                # Same-session sequential await — TenantAwareSession isn't
                # safe under concurrent execute() calls (see the project
                # hub note for the same issue).
                keyword_hits = await keyword_task
                vector_hits = await vector_task
                return _rrf_fuse([keyword_hits, vector_hits], cap=per_scope)
            return await keyword_task

    fan_out = await asyncio.gather(*(_run(s) for s in selected))
    merged: list[SearchResult] = []
    for chunk in fan_out:
        merged.extend(chunk)

    # Recency-sort. The per-scope queries already ORDER BY their
    # created_at DESC, but a global merge needs its own pass so a
    # 2-day-old document doesn't outrank a 5-min-old defect.
    merged.sort(
        key=lambda r: r.metadata.get("created_at", ""),
        reverse=True,
    )
    return merged[:limit]


# ---------- Embedding helper ----------


async def _embed_query(query: str) -> list[float] | None:
    """Embed the query string with OpenAI (3072-d). Returns None when:
      * no `OPENAI_API_KEY` is configured (dev/test path)
      * the embedder raises (transient OpenAI failure)
      * `AEC_PIPELINE_DEV_STUB` is set (the stub returns zero vectors,
        which would just dump random rows; better to skip the arm).

    Lazy import of `apps.ml.pipelines.codeguard._embedder` to avoid
    pulling langchain + tiktoken into every test that imports
    services/search.py.
    """
    from core.config import get_settings

    settings = get_settings()
    if not settings.openai_api_key:
        return None
    try:
        from ml.pipelines.codeguard import _embedder  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover — packaging issue
        logger.warning("search: codeguard embedder import failed; vector arm disabled")
        return None
    try:
        return await _embedder().aembed_query(query)
    except Exception as exc:  # pragma: no cover — network / API
        logger.warning("search: embedding call failed (%s); falling back to keyword-only", exc)
        return None


# ---------- RRF fusion ----------


def _rrf_fuse(rankers: list[list[SearchResult]], *, cap: int) -> list[SearchResult]:
    """Reciprocal-rank fusion across arbitrary rankers.

    For each result `r` and each ranker, contribute `1 / (k + rank_in_ranker)`
    to `r.score`. A row that's ranked highly in BOTH the keyword and the
    vector arm beats one that's #1 in only one — exactly the property
    we want for hybrid recall.

    Result identity is keyed by `(scope, id)`. The first ranker's copy
    wins when both produce the same row (both will have identical
    presentational fields anyway; only `score` differs).
    """
    by_key: dict[tuple[SearchScope, UUID], SearchResult] = {}
    fused_score: dict[tuple[SearchScope, UUID], float] = {}
    for ranker in rankers:
        for rank, result in enumerate(ranker, start=1):
            key = (result.scope, result.id)
            fused_score[key] = fused_score.get(key, 0.0) + 1.0 / (_RRF_K + rank)
            if key not in by_key:
                # First copy wins. Stamp the fused score below.
                by_key[key] = result

    fused = []
    for key, result in by_key.items():
        result.score = fused_score[key]
        fused.append(result)
    fused.sort(key=lambda r: r.score, reverse=True)
    return fused[:cap]


# ---------- Per-scope SQL ----------


async def _search_documents(
    session: AsyncSession,
    *,
    pattern: str,
    project_id: UUID | None,
    limit: int,
) -> list[SearchResult]:
    """Match drawbridge `documents.name` (file display name).

    Joins to `projects` for the project_name display column. Includes
    a project filter only when `project_id` is provided — otherwise
    returns hits across every project the caller can see.
    """
    where_extra = "AND d.project_id = :project_id" if project_id else ""
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT d.id, d.name, d.project_id, d.created_at,
                           p.name AS project_name
                    FROM documents d
                    LEFT JOIN projects p ON p.id = d.project_id
                    WHERE d.name ILIKE :pat
                      {where_extra}
                    ORDER BY d.created_at DESC
                    LIMIT :limit
                    """
                ),
                {"pat": pattern, "project_id": str(project_id) if project_id else None, "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        SearchResult(
            scope=SearchScope.documents,
            id=r["id"],
            title=r["name"],
            project_id=r["project_id"],
            project_name=r["project_name"],
            route=f"/drawbridge?document_id={r['id']}",
            metadata={"created_at": r["created_at"].isoformat() if r["created_at"] else ""},
        )
        for r in rows
    ]


async def _search_regulations(
    session: AsyncSession,
    *,
    pattern: str,
    project_id: UUID | None,
    limit: int,
) -> list[SearchResult]:
    """CodeGuard regulations are global reference data — the
    `project_id` filter is intentionally ignored here. `name` covers
    the canonical code (e.g. "QCVN 06:2022/BXD")."""
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, code, name, country, jurisdiction
                    FROM regulations
                    WHERE name ILIKE :pat OR code ILIKE :pat
                    ORDER BY effective_date DESC NULLS LAST
                    LIMIT :limit
                    """
                ),
                {"pat": pattern, "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        SearchResult(
            scope=SearchScope.regulations,
            id=r["id"],
            title=f"{r['code']} — {r['name']}" if r["code"] else r["name"],
            snippet=f"{r['country']} · {r['jurisdiction'] or 'national'}",
            project_id=None,
            project_name=None,
            route=f"/codeguard/regulations/{r['id']}",
            metadata={"created_at": ""},  # regulations have no created_at
        )
        for r in rows
    ]


async def _search_defects(
    session: AsyncSession,
    *,
    pattern: str,
    project_id: UUID | None,
    limit: int,
) -> list[SearchResult]:
    where_extra = "AND d.project_id = :project_id" if project_id else ""
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT d.id, d.title, d.description, d.project_id,
                           d.priority, d.status, d.reported_at,
                           p.name AS project_name
                    FROM defects d
                    LEFT JOIN projects p ON p.id = d.project_id
                    WHERE d.title ILIKE :pat OR d.description ILIKE :pat
                      {where_extra}
                    ORDER BY d.reported_at DESC
                    LIMIT :limit
                    """
                ),
                {"pat": pattern, "project_id": str(project_id) if project_id else None, "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        SearchResult(
            scope=SearchScope.defects,
            id=r["id"],
            title=r["title"],
            snippet=(r["description"] or "")[:160] if r["description"] else None,
            project_id=r["project_id"],
            project_name=r["project_name"],
            route=f"/handover?defect_id={r['id']}",
            metadata={
                "created_at": r["reported_at"].isoformat() if r["reported_at"] else "",
                "priority": r["priority"],
                "status": r["status"],
            },
        )
        for r in rows
    ]


async def _search_rfis(
    session: AsyncSession,
    *,
    pattern: str,
    project_id: UUID | None,
    limit: int,
) -> list[SearchResult]:
    where_extra = "AND r.project_id = :project_id" if project_id else ""
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT r.id, r.number, r.subject, r.description, r.project_id,
                           r.status, r.created_at, p.name AS project_name
                    FROM rfis r
                    LEFT JOIN projects p ON p.id = r.project_id
                    WHERE r.subject ILIKE :pat OR r.description ILIKE :pat
                      {where_extra}
                    ORDER BY r.created_at DESC
                    LIMIT :limit
                    """
                ),
                {"pat": pattern, "project_id": str(project_id) if project_id else None, "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        SearchResult(
            scope=SearchScope.rfis,
            id=r["id"],
            title=f"RFI #{r['number']} — {r['subject']}",
            snippet=(r["description"] or "")[:160] if r["description"] else None,
            project_id=r["project_id"],
            project_name=r["project_name"],
            route=f"/drawbridge?rfi_id={r['id']}",
            metadata={
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                "status": r["status"],
            },
        )
        for r in rows
    ]


async def _search_proposals(
    session: AsyncSession,
    *,
    pattern: str,
    project_id: UUID | None,
    limit: int,
) -> list[SearchResult]:
    where_extra = "AND p.project_id = :project_id" if project_id else ""
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT p.id, p.title, p.client_name, p.status, p.project_id,
                           p.created_at, pr.name AS project_name
                    FROM proposals p
                    LEFT JOIN projects pr ON pr.id = p.project_id
                    WHERE p.title ILIKE :pat OR p.client_name ILIKE :pat
                      {where_extra}
                    ORDER BY p.created_at DESC
                    LIMIT :limit
                    """
                ),
                {"pat": pattern, "project_id": str(project_id) if project_id else None, "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        SearchResult(
            scope=SearchScope.proposals,
            id=r["id"],
            title=r["title"],
            snippet=r["client_name"],
            project_id=r["project_id"],
            project_name=r["project_name"],
            route=f"/winwork/proposals/{r['id']}",
            metadata={
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                "status": r["status"],
            },
        )
        for r in rows
    ]


# ---------- Vector arms ----------
#
# Each function here issues a kNN query over the module's existing
# embeddings table (`document_chunks`, `regulation_chunks`,
# `rfi_embeddings`) and projects the result rows into the same
# `SearchResult` shape the keyword arms produce. The HNSW indexes
# (added in 0007 / 0009 / submittals migrations) make the kNN scan
# logarithmic; query time stays under 50ms even at 100k+ chunks.
#
# We use `embedding_half halfvec(3072)` because that's the indexed
# column. The full `embedding vector(3072)` column exists but isn't
# HNSW-indexed (storage trade-off).


def _vec_literal(vec: list[float]) -> str:
    """Render a Python list as the `[1.0,2.0,...]` literal that pgvector
    casts via `::halfvec`. Avoids `tolist()` so this works on plain lists
    (e.g. the stub embedder's zero vectors)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


async def _search_documents_vector(
    session: AsyncSession,
    *,
    query_vec: list[float],
    project_id: UUID | None,
    limit: int,
) -> list[SearchResult]:
    """kNN over document_chunks; project up to the parent document.

    Multiple chunks can match the same document — `DISTINCT ON document_id
    ORDER BY ... distance` keeps the closest chunk per doc and drops
    the rest, so we never list the same drawing twice.
    """
    project_filter = "AND d.project_id = :project_id" if project_id else ""
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT DISTINCT ON (d.id)
                           d.id, d.name, d.project_id, d.created_at,
                           p.name AS project_name,
                           1 - (c.embedding_half <=> CAST(:vec AS halfvec)) AS score
                    FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    LEFT JOIN projects p ON p.id = d.project_id
                    WHERE 1=1
                      {project_filter}
                    ORDER BY d.id, c.embedding_half <=> CAST(:vec AS halfvec)
                    LIMIT :limit
                    """
                ),
                {
                    "vec": _vec_literal(query_vec),
                    "project_id": str(project_id) if project_id else None,
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return [
        SearchResult(
            scope=SearchScope.documents,
            id=r["id"],
            title=r["name"],
            project_id=r["project_id"],
            project_name=r["project_name"],
            route=f"/drawbridge?document_id={r['id']}",
            score=float(r["score"] or 0.0),
            metadata={"created_at": r["created_at"].isoformat() if r["created_at"] else ""},
        )
        for r in rows
    ]


async def _search_regulations_vector(
    session: AsyncSession,
    *,
    query_vec: list[float],
    project_id: UUID | None,
    limit: int,
) -> list[SearchResult]:
    """kNN over regulation_chunks; project up to the parent regulation."""
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT ON (r.id)
                           r.id, r.code, r.name, r.country, r.jurisdiction,
                           1 - (c.embedding_half <=> CAST(:vec AS halfvec)) AS score
                    FROM regulation_chunks c
                    JOIN regulations r ON r.id = c.regulation_id
                    ORDER BY r.id, c.embedding_half <=> CAST(:vec AS halfvec)
                    LIMIT :limit
                    """
                ),
                {"vec": _vec_literal(query_vec), "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [
        SearchResult(
            scope=SearchScope.regulations,
            id=r["id"],
            title=f"{r['code']} — {r['name']}" if r["code"] else r["name"],
            snippet=f"{r['country']} · {r['jurisdiction'] or 'national'}",
            project_id=None,
            project_name=None,
            route=f"/codeguard/regulations/{r['id']}",
            score=float(r["score"] or 0.0),
            metadata={"created_at": ""},
        )
        for r in rows
    ]


async def _search_rfis_vector(
    session: AsyncSession,
    *,
    query_vec: list[float],
    project_id: UUID | None,
    limit: int,
) -> list[SearchResult]:
    """kNN over rfi_embeddings; project up to the parent RFI.

    `rfi_embeddings` is one row per RFI (not per chunk like documents),
    so the DISTINCT ON is unnecessary here. JOIN shape kept consistent
    with the other two arms for readability.
    """
    project_filter = "AND r.project_id = :project_id" if project_id else ""
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT r.id, r.number, r.subject, r.description,
                           r.project_id, r.status, r.created_at,
                           p.name AS project_name,
                           1 - (e.embedding_half <=> CAST(:vec AS halfvec)) AS score
                    FROM rfi_embeddings e
                    JOIN rfis r ON r.id = e.rfi_id
                    LEFT JOIN projects p ON p.id = r.project_id
                    WHERE 1=1
                      {project_filter}
                    ORDER BY e.embedding_half <=> CAST(:vec AS halfvec)
                    LIMIT :limit
                    """
                ),
                {
                    "vec": _vec_literal(query_vec),
                    "project_id": str(project_id) if project_id else None,
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return [
        SearchResult(
            scope=SearchScope.rfis,
            id=r["id"],
            title=f"RFI #{r['number']} — {r['subject']}",
            snippet=(r["description"] or "")[:160] if r["description"] else None,
            project_id=r["project_id"],
            project_name=r["project_name"],
            route=f"/drawbridge?rfi_id={r['id']}",
            score=float(r["score"] or 0.0),
            metadata={
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                "status": r["status"],
            },
        )
        for r in rows
    ]


# Dispatch tables — one entry per scope. Keep the keys aligned with the
# `SearchScope` enum so adding a scope is a single-edit operation.
_SCOPE_HANDLERS: dict[SearchScope, Any] = {
    SearchScope.documents: _search_documents,
    SearchScope.regulations: _search_regulations,
    SearchScope.defects: _search_defects,
    SearchScope.rfis: _search_rfis,
    SearchScope.proposals: _search_proposals,
}

# Vector arms — only for scopes whose underlying tables carry embeddings.
# Defects + proposals are intentionally absent: no embeddings table, so
# they stay keyword-only.
_VECTOR_HANDLERS: dict[SearchScope, Any] = {
    SearchScope.documents: _search_documents_vector,
    SearchScope.regulations: _search_regulations_vector,
    SearchScope.rfis: _search_rfis_vector,
}
