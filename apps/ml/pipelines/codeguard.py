"""CODEGUARD AI pipelines: RAG-based Q&A, auto-scan, permit checklist generation.

Architecture:
    Dense retrieval (pgvector) + sparse retrieval (Elasticsearch BM25)
    → Reciprocal Rank Fusion
    → Cross-encoder re-ranking (bge-reranker-v2-m3)
    → LLM generation with structured output (Anthropic Claude)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from uuid import UUID

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import OpenAIEmbeddings
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field
from schemas.codeguard import (
    ChecklistItem,
    Citation,
    Finding,
    FindingStatus,
    ProjectParameters,
    QueryResponse,
    RegulationCategory,
    Severity,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------- Model / index clients ----------

_ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
_ES_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
_RERANKER_ENDPOINT = os.getenv("RERANKER_ENDPOINT")  # bge-reranker-v2-m3 service
_RRF_K = 60

# HyDE expansion is the most-skippable LLM call in the pipeline: it
# transforms `question` into a hypothetical regulation paragraph used
# for dense retrieval, but the same question always wants the same
# expansion. Cache aggressively so repeat questions in an active
# session skip the Anthropic round-trip entirely. ~500-800ms saved
# per cache hit, which is exactly the gap users see between clicking
# "Gửi" and the first streamed token.
#
# In-memory + per-process; multi-worker production gets N independent
# caches. A shared Redis cache is a worthwhile follow-up but adds an
# infra dep we don't currently need for dev/staging.
import cachetools  # noqa: E402

_HYDE_CACHE_MAX = int(os.getenv("CODEGUARD_HYDE_CACHE_MAX", "10000"))
_HYDE_CACHE_TTL = int(os.getenv("CODEGUARD_HYDE_CACHE_TTL_SEC", "3600"))
_hyde_cache: cachetools.TTLCache = cachetools.TTLCache(
    maxsize=_HYDE_CACHE_MAX,
    ttl=_HYDE_CACHE_TTL,
)


def _llm(temperature: float = 0.1) -> ChatAnthropic:
    return ChatAnthropic(model=_ANTHROPIC_MODEL, temperature=temperature, max_tokens=4096)


def _embedder() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=_EMBED_MODEL)


# ---------- Language detection & HyDE expansion ----------


def _detect_language(text_in: str) -> str:
    # Lightweight heuristic; replace with fasttext lid.176 in production.
    vietnamese_markers = "ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ"
    return "vi" if any(c in text_in.lower() for c in vietnamese_markers) else "en"


async def _hyde_expand(question: str, language: str) -> str:
    """Generate a hypothetical regulation excerpt to improve dense retrieval.

    TTL-cached on `(question, language)`. Cache hits skip the Anthropic
    call entirely and return immediately — same prompt, same model,
    same answer in 99% of cases, so the worst the cache does is replay
    a slightly stale generation. Misses populate the cache *only* on
    success; a raised exception leaves the cache unchanged so retries
    can proceed normally.

    Defaults: 10000 entries, 1h TTL. Override via env:
      * `CODEGUARD_HYDE_CACHE_MAX`     — max entries (LRU eviction past)
      * `CODEGUARD_HYDE_CACHE_TTL_SEC` — TTL in seconds
    """
    key = (question, language)
    cached = _hyde_cache.get(key)
    if cached is not None:
        return cached

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a Vietnamese building code expert. Given a question, "
                "write a plausible regulation paragraph that would answer it. "
                "Respond in the target language ({language}). Be specific and technical.",
            ),
            ("human", "{question}"),
        ]
    )
    chain = prompt | _llm(temperature=0.3)
    result = await chain.ainvoke({"question": question, "language": language})
    text_value = result.content if isinstance(result.content, str) else str(result.content)
    # Only store on success — a thrown exception above bypasses this.
    _hyde_cache[key] = text_value
    return text_value


def _hyde_clear_cache() -> None:
    """Test helper: drop all cached HyDE entries.

    Production code should never need this. Tests use it between cases
    to keep state isolated when monkeypatching the LLM factory.
    """
    _hyde_cache.clear()


# ---------- Retrieval ----------


async def _dense_search(
    db: AsyncSession,
    query_text: str,
    categories: list[RegulationCategory] | None,
    jurisdiction: str | None,
    top_k: int,
) -> list[dict[str, Any]]:
    embedding = await _embedder().aembed_query(query_text)
    vec_literal = "[" + ",".join(f"{x:.7f}" for x in embedding) + "]"

    where_clauses = ["1=1"]
    params: dict[str, Any] = {"vec": vec_literal, "limit": top_k * 3}
    if categories:
        where_clauses.append("r.category = ANY(:categories)")
        params["categories"] = [c.value for c in categories]
    if jurisdiction:
        where_clauses.append("r.jurisdiction = :jurisdiction")
        params["jurisdiction"] = jurisdiction

    # Query the halfvec-generated column so the HNSW index
    # `ix_regulation_chunks_embedding_half_hnsw` (see migration
    # 0009_codeguard_hnsw) is picked up — full vector(3072) scans are
    # untenable once the corpus crosses a few thousand chunks.
    sql = text(f"""
        SELECT c.id, c.regulation_id, c.section_ref, c.content,
               r.code_name, r.source_url,
               1 - (c.embedding_half <=> CAST(:vec AS halfvec)) AS score
        FROM regulation_chunks c
        JOIN regulations r ON r.id = c.regulation_id
        WHERE {" AND ".join(where_clauses)}
        ORDER BY c.embedding_half <=> CAST(:vec AS halfvec)
        LIMIT :limit
    """)
    rows = (await db.execute(sql, params)).mappings().all()
    return [dict(r) for r in rows]


async def _sparse_search(
    query_text: str,
    categories: list[RegulationCategory] | None,
    jurisdiction: str | None,
    top_k: int,
) -> list[dict[str, Any]]:
    """BM25 via Elasticsearch. Returns [] if ES is unreachable (graceful degradation)."""
    try:
        from elasticsearch import AsyncElasticsearch
    except ImportError:
        # Package not installed at all — this is a deployment-config issue,
        # not a transient outage. Log once at DEBUG; bumping to WARNING
        # would fire on every query in environments (e.g. CI, local dev)
        # that intentionally run dense-only.
        logger.debug("codeguard: elasticsearch package not installed, sparse search disabled")
        return []

    es = AsyncElasticsearch(_ES_URL)
    try:
        must: list[dict[str, Any]] = [{"match": {"content": query_text}}]
        filters: list[dict[str, Any]] = []
        if categories:
            filters.append({"terms": {"category": [c.value for c in categories]}})
        if jurisdiction:
            filters.append({"term": {"jurisdiction": jurisdiction}})

        res = await es.search(
            index="regulation_chunks",
            size=top_k * 3,
            query={"bool": {"must": must, "filter": filters}},
        )
        hits = res.get("hits", {}).get("hits", [])
        return [
            {
                "id": h["_id"],
                "regulation_id": h["_source"].get("regulation_id"),
                "section_ref": h["_source"].get("section_ref"),
                "content": h["_source"].get("content"),
                "code_name": h["_source"].get("code_name"),
                "source_url": h["_source"].get("source_url"),
                "score": h["_score"],
            }
            for h in hits
        ]
    except Exception as exc:
        # Silent-return is graceful degradation (the pipeline falls back to
        # dense-only), but silence in prod masks real ES outages. Log once
        # per failed query at WARNING — noisy enough to show up in alerts,
        # not so noisy it drowns the log if ES is down for an hour.
        logger.warning(
            "codeguard: BM25/Elasticsearch query failed, falling back to dense-only: %s", exc
        )
        return []
    finally:
        await es.close()


def _reciprocal_rank_fusion(
    dense: list[dict[str, Any]],
    sparse: list[dict[str, Any]],
    k: int = _RRF_K,
) -> list[dict[str, Any]]:
    """Combine two ranked lists via Reciprocal Rank Fusion.

    RRF score per doc = Σ 1 / (k + rank_in_list). `k=60` is the original
    Cormack/Clark constant — larger `k` dampens the contribution of top
    ranks, smaller `k` lets a single list dominate. 60 is the sweet spot
    most RAG systems use and what we inherit from the module defaults.

    Missing-from-one-list is the common case (dense-only or sparse-only
    hit); those docs get the score from the list they're in.
    """
    scores: dict[str, float] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for rank, item in enumerate(dense):
        key = str(item["id"])
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        payloads[key] = item
    for rank, item in enumerate(sparse):
        key = str(item["id"])
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        payloads.setdefault(key, item)
    fused = sorted(payloads.values(), key=lambda it: scores[str(it["id"])], reverse=True)
    return fused


async def _hybrid_search(
    db: AsyncSession,
    query_text: str,
    categories: list[RegulationCategory] | None,
    jurisdiction: str | None,
    top_k: int,
    sparse_query: str | None = None,
) -> list[dict[str, Any]]:
    """Run dense + sparse retrieval concurrently and fuse via RRF.

    Why a facade: `node_retrieve` (Q&A) and `auto_scan_project` both ran
    dense → sparse → RRF inline, doing the two retrievals sequentially.
    Since they hit different stores (pgvector vs Elasticsearch) there's no
    reason to serialise them — `asyncio.gather` roughly halves retrieval
    latency on a cache miss.

    `sparse_query` defaults to `query_text` but can be narrower. The Q&A
    pipeline passes a HyDE-expanded prose blob for dense retrieval (good:
    adds semantic surface area) but should feed only the raw question to
    BM25 (HyDE prose dilutes term signal for keyword match).

    If Elasticsearch is unavailable, `_sparse_search` returns `[]` and this
    function effectively becomes dense-only — the graceful-degradation path
    is fully covered by `_reciprocal_rank_fusion([...], [])` returning the
    dense list unchanged (one score term per doc, in dense rank order).
    """
    dense, sparse = await asyncio.gather(
        _dense_search(db, query_text, categories, jurisdiction, top_k),
        _sparse_search(sparse_query or query_text, categories, jurisdiction, top_k),
    )
    return _reciprocal_rank_fusion(dense, sparse)


async def _rerank(
    query_text: str, candidates: list[dict[str, Any]], top_k: int
) -> list[dict[str, Any]]:
    """Cross-encoder re-ranking. Falls back to input order if reranker unavailable."""
    if not _RERANKER_ENDPOINT or not candidates:
        return candidates[:top_k]
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                _RERANKER_ENDPOINT,
                json={"query": query_text, "documents": [c["content"] for c in candidates]},
            )
            res.raise_for_status()
            order = res.json()["ranked_indices"]
            return [candidates[i] for i in order[:top_k]]
    except Exception:
        return candidates[:top_k]


# ---------- Q&A pipeline (LangGraph) ----------


class _QAState(BaseModel):
    question: str
    language: str = "vi"
    jurisdiction: str | None = None
    categories: list[RegulationCategory] | None = None
    top_k: int = 8
    hyde_text: str = ""
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    answer: QueryResponse | None = None


_QA_SYSTEM = """You are CODEGUARD, an expert on Vietnamese building codes and zoning regulations.

Rules:
- Answer strictly from the provided context chunks.
- Every factual claim MUST cite a specific chunk via its regulation code and section.
- If the context is insufficient, say so and set confidence low.
- Respond in the user's language: {language}.

Output MUST be valid JSON matching:
{{
  "answer": string,
  "confidence": number (0.0-1.0),
  "citations": [{{ "chunk_index": int, "regulation": string, "section": string, "excerpt": string }}],
  "related_questions": [string, string, string]
}}
"""

_QA_USER = """Question: {question}

Context chunks:
{context}

Return JSON only."""


def _format_context(chunks: list[dict[str, Any]]) -> str:
    lines = []
    for i, c in enumerate(chunks):
        lines.append(
            f"[{i}] {c.get('code_name', '?')} — Section {c.get('section_ref', '?')}\n"
            f"{c.get('content', '')}"
        )
    return "\n\n".join(lines)


# Localised abstain messages for when retrieval returns zero candidates.
# These are the *only* strings users see when the corpus has no relevant
# material — the alternative is letting the LLM hallucinate a plausible-
# sounding regulation, which is the worst failure mode for a compliance
# tool. Keep them short, unambiguous, and in the user's requested language.
_ABSTAIN_MESSAGES = {
    "vi": "Không tìm thấy quy định liên quan trong cơ sở tri thức CODEGUARD.",
    "en": "No relevant regulations were found in the CODEGUARD knowledge base for this question.",
}


def _abstain_response(language: str) -> QueryResponse:
    """Build the canonical zero-retrieval response.

    Called when `node_retrieve` returns an empty candidate list — either the
    corpus is empty, the filters (category/jurisdiction) matched nothing, or
    the question is about a domain we haven't ingested yet. Skipping the LLM
    call entirely is the correctness win: an empty context + a Claude prompt
    reliably produces a confident-sounding fabrication, which we must never
    ship to the UI for a compliance tool.

    `confidence=0.0` is semantically load-bearing: downstream UI can switch
    to a different rendering ("we don't have data for this") on that signal.
    """
    msg = _ABSTAIN_MESSAGES.get(language, _ABSTAIN_MESSAGES["en"])
    return QueryResponse(
        answer=msg,
        confidence=0.0,
        citations=[],
        related_questions=[],
    )


def _norm_text(s: str) -> str:
    """Whitespace-collapsed, lower-cased form for substring equality checks."""
    return " ".join(s.lower().split())


def _ground_citations(
    raw_citations: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[Citation]:
    """Shape LLM-reported citations into verified `Citation` objects.

    The #1 failure mode for RAG compliance tools is the LLM inventing
    authoritative-looking section refs or quotes that don't exist in the
    source. This function is the single choke point that prevents that:

      * `chunk_index` must be a non-negative int within `candidates`. Any
        other type (None, str, float, negative, out-of-range) is dropped
        with a WARNING log — silent drops make this class of bug very hard
        to diagnose in production.
      * `regulation_id`, `regulation` (code_name), `section` (section_ref),
        and `source_url` come exclusively from the retrieved DB row. The
        LLM's only influence on provenance is *which* chunk to cite via
        `chunk_index`; it cannot fabricate a code name or section.
      * `excerpt` accepts the LLM's phrase IFF it's a faithful (whitespace-
        collapsed, case-folded) substring of the chunk content. This keeps
        the UX benefit of a focused highlight while guaranteeing the quoted
        text actually appears in the source. If the excerpt is missing or
        not a substring, we fall back to the first 300 chars of the chunk.

    Returned citations are safe to render as authoritative without further
    validation downstream.
    """
    grounded: list[Citation] = []
    for raw in raw_citations or []:
        idx = raw.get("chunk_index")
        # Reject `bool` explicitly — Python's `isinstance(True, int)` is True
        # but `candidates[True]` indexing a chunk list is never intended.
        if not isinstance(idx, int) or isinstance(idx, bool):
            logger.warning("codeguard: dropping citation with non-int chunk_index=%r", idx)
            continue
        if idx < 0 or idx >= len(candidates):
            logger.warning(
                "codeguard: dropping citation with out-of-range chunk_index=%d "
                "(have %d candidates)",
                idx,
                len(candidates),
            )
            continue

        src = candidates[idx]
        try:
            regulation_id = UUID(str(src["regulation_id"]))
        except (KeyError, ValueError) as exc:
            logger.warning(
                "codeguard: dropping citation — source row has no valid regulation_id: %s",
                exc,
            )
            continue

        src_content = src.get("content") or ""
        raw_excerpt = raw.get("excerpt")
        if (
            isinstance(raw_excerpt, str)
            and raw_excerpt.strip()
            and _norm_text(raw_excerpt) in _norm_text(src_content)
        ):
            excerpt = raw_excerpt
        else:
            if isinstance(raw_excerpt, str) and raw_excerpt.strip():
                logger.warning(
                    "codeguard: replacing ungrounded excerpt for chunk_index=%d "
                    "(LLM quote not found in source chunk)",
                    idx,
                )
            excerpt = src_content[:300]

        grounded.append(
            Citation(
                regulation_id=regulation_id,
                regulation=src.get("code_name") or "",
                section=src.get("section_ref") or "",
                excerpt=excerpt,
                source_url=src.get("source_url"),
            )
        )
    return grounded


async def answer_regulation_query(
    db: AsyncSession,
    question: str,
    language: str | None,
    jurisdiction: str | None,
    categories: list[RegulationCategory] | None,
    top_k: int,
) -> QueryResponse:
    lang = language or _detect_language(question)

    async def node_expand(state: _QAState) -> _QAState:
        state.hyde_text = await _hyde_expand(state.question, state.language)
        return state

    async def node_retrieve(state: _QAState) -> _QAState:
        # Dense query includes HyDE expansion for semantic surface area;
        # sparse gets the raw question (HyDE prose would dilute BM25 terms).
        # `_hybrid_search` runs both concurrently and fuses via RRF.
        query_text = f"{state.question}\n{state.hyde_text}"
        fused = await _hybrid_search(
            db,
            query_text,
            categories=state.categories,
            jurisdiction=state.jurisdiction,
            top_k=state.top_k,
            sparse_query=state.question,
        )
        state.candidates = await _rerank(state.question, fused, state.top_k)
        return state

    async def node_generate(state: _QAState) -> _QAState:
        # Zero-retrieval abstain: if hybrid search + re-rank found nothing
        # we refuse to invoke the LLM. An empty `context` field in the
        # prompt reliably coaxes Claude into fabricating a citation-shaped
        # hallucination — the worst failure mode for a compliance tool.
        # Short-circuit with the canned abstain response instead; this also
        # saves ~2 API calls and ~1s of latency per out-of-corpus query.
        if not state.candidates:
            logger.info(
                "codeguard: zero retrieval candidates for question=%r lang=%s — "
                "returning abstain response (LLM skipped)",
                state.question[:80],
                state.language,
            )
            state.answer = _abstain_response(state.language)
            return state

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _QA_SYSTEM),
                ("human", _QA_USER),
            ]
        )
        chain = prompt | _llm(temperature=0.1) | JsonOutputParser()
        raw = await chain.ainvoke(
            {
                "language": state.language,
                "question": state.question,
                "context": _format_context(state.candidates),
            }
        )

        # Citations pass through _ground_citations — the single choke point
        # that rejects hallucinated section refs and excerpts (see its docstring).
        citations = _ground_citations(raw.get("citations", []) or [], state.candidates)

        state.answer = QueryResponse(
            answer=raw.get("answer", ""),
            confidence=float(raw.get("confidence", 0.5)),
            citations=citations,
            related_questions=raw.get("related_questions", [])[:3],
        )
        return state

    graph = StateGraph(_QAState)
    graph.add_node("expand", node_expand)
    graph.add_node("retrieve", node_retrieve)
    graph.add_node("generate", node_generate)
    graph.set_entry_point("expand")
    graph.add_edge("expand", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    app = graph.compile()

    state = _QAState(
        question=question,
        language=lang,
        jurisdiction=jurisdiction,
        categories=categories,
        top_k=top_k,
    )
    final = await app.ainvoke(state)
    result = final["answer"] if isinstance(final, dict) else final.answer
    assert result is not None
    return result


# ---------- Streaming Q&A ------------------------------------------------

# Event tuple shape: (event_name, payload). Defined as `tuple[str, Any]`
# so the SSE adapter in the route layer can pattern-match on the name
# without importing this module's types.
StreamEvent = tuple[str, Any]


async def answer_regulation_query_stream(
    db: AsyncSession,
    question: str,
    language: str | None,
    jurisdiction: str | None,
    categories: list[RegulationCategory] | None,
    top_k: int,
):
    """Streaming variant of `answer_regulation_query`.

    Yields a sequence of `(event_name, payload)` tuples:
      ("token", str)            — incremental answer-text deltas as the LLM
                                  generates. Concatenating all deltas gives
                                  the final `answer` string.
      ("done", QueryResponse)   — terminal event with the fully-grounded
                                  response. Always emitted exactly once on
                                  the success path (including abstain).
      ("error", str)            — terminal event on pipeline failure. The
                                  message is intended for UX surface; it
                                  does NOT include a stack trace.

    Architecture note: we deliberately do NOT plumb streaming through the
    LangGraph state machine used by `answer_regulation_query`. The
    expand/retrieve nodes have nothing meaningful to stream (they're a
    single HyDE call + a SQL query), and integrating astream() through a
    StateGraph adds significant complexity without payoff. Instead this
    function reimplements the same three phases procedurally so the
    generation phase can use `chain.astream()` directly.

    The retrieval + abstain semantics are kept identical to the
    non-streaming path: same `_hybrid_search`, same `_rerank`, same
    `_ground_citations`, same `_abstain_response`. If you change those,
    both paths get the change for free.
    """
    lang = language or _detect_language(question)

    try:
        # Phase 1 — HyDE + retrieval. Not streamed (single HyDE call +
        # one DB query); streaming wouldn't help latency here.
        hyde_text = await _hyde_expand(question, lang)
        query_text = f"{question}\n{hyde_text}"
        fused = await _hybrid_search(
            db,
            query_text,
            categories=categories,
            jurisdiction=jurisdiction,
            top_k=top_k,
            sparse_query=question,
        )
        candidates = await _rerank(question, fused, top_k)

        # Same zero-retrieval guard as `node_generate`. We emit only the
        # `done` event — there are no tokens to stream because the LLM
        # is never invoked. Frontend should render the abstain card the
        # moment it receives `done` with confidence=0 + empty citations.
        if not candidates:
            logger.info(
                "codeguard: streaming query — zero retrieval candidates "
                "for question=%r lang=%s — emitting abstain",
                question[:80],
                lang,
            )
            yield ("done", _abstain_response(lang))
            return

        # Phase 2 — stream generation. JsonOutputParser.astream() yields
        # successive partial dicts as the JSON is parsed; the `answer`
        # field grows monotonically (single string field; no key swaps),
        # so a simple prefix-delta is sufficient.
        prompt = ChatPromptTemplate.from_messages([("system", _QA_SYSTEM), ("human", _QA_USER)])
        chain = prompt | _llm(temperature=0.1) | JsonOutputParser()

        prev_answer = ""
        last_partial: dict[str, Any] | None = None
        async for partial in chain.astream(
            {
                "language": lang,
                "question": question,
                "context": _format_context(candidates),
            }
        ):
            if not isinstance(partial, dict):
                continue
            last_partial = partial
            cur = partial.get("answer", "")
            if not isinstance(cur, str) or cur == prev_answer:
                continue
            # Emit only the delta. In normal LLM streaming `cur` always
            # extends `prev_answer`, but defend against a parser
            # regenerating the prefix by falling back to the full string
            # when the prefix invariant is broken.
            if cur.startswith(prev_answer):
                delta = cur[len(prev_answer) :]
            else:
                delta = cur
            prev_answer = cur
            if delta:
                yield ("token", delta)

        if last_partial is None:
            yield ("error", "LLM produced no output")
            return

        # Phase 3 — ground citations + emit final response. Same pipeline
        # as the non-streaming path; the grounding guard is the single
        # choke point against hallucinated section refs (see §5.1 of
        # docs/codeguard.md).
        citations = _ground_citations(last_partial.get("citations", []) or [], candidates)
        response = QueryResponse(
            answer=last_partial.get("answer", "") or "",
            confidence=float(last_partial.get("confidence", 0.5)),
            citations=citations,
            related_questions=(last_partial.get("related_questions", []) or [])[:3],
        )
        yield ("done", response)
    except Exception as exc:  # pragma: no cover — defensive catch-all
        logger.exception("codeguard: streaming query failed")
        yield ("error", str(exc))


# ---------- Auto-scan ----------

_SCAN_SYSTEM = """You are CODEGUARD, auditing a project against Vietnamese building codes.

Given project parameters and relevant regulation excerpts for ONE category,
produce findings. Each finding has:
  - status: FAIL | WARN | PASS
  - severity: critical | major | minor
  - title: short Vietnamese/English summary
  - description: plain-language explanation of what the code requires vs what the project has
  - resolution: concrete fix (null if PASS)
  - citation_chunk_index: integer index into the provided chunks

Be conservative: use WARN when information is insufficient; FAIL only for clear violations.

Return JSON: {{"findings": [...]}}
"""

_SCAN_USER = """Category: {category}
Project parameters:
{params}

Regulation context:
{context}

Return JSON only."""


_CATEGORY_DEFAULTS = [
    RegulationCategory.fire_safety,
    RegulationCategory.accessibility,
    RegulationCategory.structure,
    RegulationCategory.zoning,
    RegulationCategory.energy,
]


async def auto_scan_project(
    db: AsyncSession,
    parameters: ProjectParameters,
    categories: list[RegulationCategory] | None,
) -> tuple[list[Finding], list[UUID]]:
    target_categories = categories or _CATEGORY_DEFAULTS
    all_findings: list[Finding] = []
    all_reg_ids: set[UUID] = set()

    jurisdiction = None
    if parameters.location:
        jurisdiction = parameters.location.get("province") or parameters.location.get(
            "jurisdiction"
        )

    param_summary = json.dumps(
        parameters.model_dump(exclude_none=True), ensure_ascii=False, indent=2
    )

    for category in target_categories:
        query = _category_probe(category, parameters)
        # Same hybrid facade as the Q&A pipeline — concurrent dense + sparse
        # with graceful dense-only fallback. No HyDE here since the probe
        # query is already engineered for keyword precision.
        fused = await _hybrid_search(
            db,
            query,
            categories=[category],
            jurisdiction=jurisdiction,
            top_k=8,
        )
        chunks = await _rerank(query, fused, top_k=6)
        if not chunks:
            continue

        for c in chunks:
            all_reg_ids.add(UUID(str(c["regulation_id"])))

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _SCAN_SYSTEM),
                ("human", _SCAN_USER),
            ]
        )
        chain = prompt | _llm(temperature=0.0) | JsonOutputParser()
        try:
            raw = await chain.ainvoke(
                {
                    "category": category.value,
                    "params": param_summary,
                    "context": _format_context(chunks),
                }
            )
        except Exception:
            continue

        for f in raw.get("findings", []):
            idx = f.get("citation_chunk_index")
            citation: Citation | None = None
            if isinstance(idx, int) and 0 <= idx < len(chunks):
                src = chunks[idx]
                citation = Citation(
                    regulation_id=UUID(str(src["regulation_id"])),
                    regulation=src.get("code_name", ""),
                    section=src.get("section_ref") or "",
                    excerpt=(src.get("content") or "")[:300],
                    source_url=src.get("source_url"),
                )
            try:
                all_findings.append(
                    Finding(
                        status=FindingStatus(f.get("status", "WARN")),
                        severity=Severity(f.get("severity", "minor")),
                        category=category,
                        title=f.get("title", ""),
                        description=f.get("description", ""),
                        resolution=f.get("resolution"),
                        citation=citation,
                    )
                )
            except ValueError:
                continue

    return all_findings, list(all_reg_ids)


async def auto_scan_project_stream(
    db: AsyncSession,
    parameters: ProjectParameters,
    categories: list[RegulationCategory] | None,
):
    """Streaming variant of `auto_scan_project`.

    Yields a sequence of `(event_name, payload)` tuples:
      ("category_start", RegulationCategory)
          Emitted just before each category's retrieval + LLM call begin.
          Lets the UI render a placeholder ("Đang quét fire_safety...")
          before any latency is incurred.

      ("category_done", {"category": RegulationCategory,
                          "findings": list[Finding],
                          "reg_ids": list[UUID]})
          Emitted once a category's findings are fully grounded and
          ready to render. `findings` may be empty if the LLM returned
          nothing (or retrieval was empty); the UI should still render
          a "no issues found for X" advisory rather than skipping the
          category silently.

      ("error", str)
          Terminal — emitted only on a hard failure that aborts the
          whole scan. Per-category LLM exceptions are swallowed
          (matching the non-streaming path) and the category just
          yields zero findings.

    The terminal event is left to the caller (route layer) — this
    helper does NOT emit a final `("done", ...)` because the route
    needs to persist the ComplianceCheck row and compute aggregate
    counts before sending the SSE `done` frame to the client.

    Sharing semantics with `auto_scan_project`: same `_hybrid_search`,
    same `_rerank`, same Citation construction (which already grounds
    citations from the DB row, not the LLM). Anything you change in
    those flows lands in both paths.
    """
    target_categories = categories or _CATEGORY_DEFAULTS

    jurisdiction = None
    if parameters.location:
        jurisdiction = parameters.location.get("province") or parameters.location.get(
            "jurisdiction"
        )

    param_summary = json.dumps(
        parameters.model_dump(exclude_none=True), ensure_ascii=False, indent=2
    )

    try:
        for category in target_categories:
            yield ("category_start", category)

            query = _category_probe(category, parameters)
            fused = await _hybrid_search(
                db,
                query,
                categories=[category],
                jurisdiction=jurisdiction,
                top_k=8,
            )
            chunks = await _rerank(query, fused, top_k=6)
            if not chunks:
                # No retrieval → no findings, but emit the `done` event
                # so the UI can render the empty advisory rather than
                # showing the category as still in-flight.
                yield (
                    "category_done",
                    {"category": category, "findings": [], "reg_ids": []},
                )
                continue

            reg_ids: list[UUID] = [UUID(str(c["regulation_id"])) for c in chunks]

            prompt = ChatPromptTemplate.from_messages(
                [("system", _SCAN_SYSTEM), ("human", _SCAN_USER)]
            )
            chain = prompt | _llm(temperature=0.0) | JsonOutputParser()
            try:
                raw = await chain.ainvoke(
                    {
                        "category": category.value,
                        "params": param_summary,
                        "context": _format_context(chunks),
                    }
                )
            except Exception as exc:
                # Same per-category swallow as the non-streaming path —
                # one bad category shouldn't kill the whole scan.
                logger.warning(
                    "codeguard: scan stream — LLM call for category=%s failed: %s",
                    category.value,
                    exc,
                )
                yield (
                    "category_done",
                    {"category": category, "findings": [], "reg_ids": reg_ids},
                )
                continue

            findings: list[Finding] = []
            for f in raw.get("findings", []) or []:
                idx = f.get("citation_chunk_index")
                citation: Citation | None = None
                if isinstance(idx, int) and 0 <= idx < len(chunks):
                    src = chunks[idx]
                    citation = Citation(
                        regulation_id=UUID(str(src["regulation_id"])),
                        regulation=src.get("code_name", ""),
                        section=src.get("section_ref") or "",
                        excerpt=(src.get("content") or "")[:300],
                        source_url=src.get("source_url"),
                    )
                try:
                    findings.append(
                        Finding(
                            status=FindingStatus(f.get("status", "WARN")),
                            severity=Severity(f.get("severity", "minor")),
                            category=category,
                            title=f.get("title", ""),
                            description=f.get("description", ""),
                            resolution=f.get("resolution"),
                            citation=citation,
                        )
                    )
                except ValueError:
                    # Malformed enum value — skip the finding rather
                    # than dropping the rest of the category.
                    continue

            yield (
                "category_done",
                {"category": category, "findings": findings, "reg_ids": reg_ids},
            )
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("codeguard: scan stream aborted")
        yield ("error", str(exc))


def _category_probe(category: RegulationCategory, p: ProjectParameters) -> str:
    """Build a retrieval query that surfaces the most relevant chunks for a category."""
    base = f"{p.project_type} {p.use_class or ''}"
    if category == RegulationCategory.fire_safety:
        return f"fire safety requirements {base} floors={p.floors_above} height={p.max_height_m}m evacuation exits compartmentation"
    if category == RegulationCategory.accessibility:
        return f"accessible design {base} ramps elevators disabled access WC QCVN 10"
    if category == RegulationCategory.structure:
        return f"structural requirements {base} earthquake seismic zone floors={p.floors_above}"
    if category == RegulationCategory.zoning:
        return f"zoning setback coverage FAR {base} plot ratio land use"
    if category == RegulationCategory.energy:
        return f"energy efficiency envelope insulation glazing {base} QCVN 09"
    return base


# ---------- Permit checklist generation ----------

_CHECKLIST_SYSTEM = """You are CODEGUARD generating a construction permit checklist for Vietnam.

Given jurisdiction, project type, and (optionally) project parameters, return a
JSON array of checklist items the applicant must prepare. Each item:
  {{
    "id": "slug-like-id",
    "title": "Vietnamese title",
    "description": "what to prepare",
    "regulation_ref": "QCVN 06:2022 Section X" or null,
    "required": true/false
  }}

Cover: site documents, design drawings, structural calculations, fire-safety approval,
environmental impact (if applicable), utility connection approvals, legal land-use
documents, stakeholder approvals.

Return JSON only: {{"items": [...]}}
"""


async def generate_permit_checklist(
    db: AsyncSession,
    jurisdiction: str,
    project_type: str,
    parameters: ProjectParameters | None,
) -> list[ChecklistItem]:
    params_summary = (
        json.dumps(parameters.model_dump(exclude_none=True), ensure_ascii=False, indent=2)
        if parameters
        else "(not provided)"
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _CHECKLIST_SYSTEM),
            (
                "human",
                "Jurisdiction: {jurisdiction}\nProject type: {project_type}\n\nParameters:\n{params}\n\nReturn JSON only.",
            ),
        ]
    )
    chain = prompt | _llm(temperature=0.2) | JsonOutputParser()
    raw = await chain.ainvoke(
        {
            "jurisdiction": jurisdiction,
            "project_type": project_type,
            "params": params_summary,
        }
    )

    items: list[ChecklistItem] = []
    for i, item in enumerate(raw.get("items", [])):
        items.append(
            ChecklistItem(
                id=item.get("id") or f"item-{i}",
                title=item.get("title", ""),
                description=item.get("description"),
                regulation_ref=item.get("regulation_ref"),
                required=bool(item.get("required", True)),
                status="pending",
            )
        )
    return items
