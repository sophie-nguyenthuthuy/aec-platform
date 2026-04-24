"""CODEGUARD AI pipelines: RAG-based Q&A, auto-scan, permit checklist generation.

Architecture:
    Dense retrieval (pgvector) + sparse retrieval (Elasticsearch BM25)
    → Reciprocal Rank Fusion
    → Cross-encoder re-ranking (bge-reranker-v2-m3)
    → LLM generation with structured output (Anthropic Claude)
"""
from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_anthropic import ChatAnthropic
from langchain_openai import OpenAIEmbeddings
from langgraph.graph import StateGraph, END
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession
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


# ---------- Model / index clients ----------

_ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
_ES_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
_RERANKER_ENDPOINT = os.getenv("RERANKER_ENDPOINT")  # bge-reranker-v2-m3 service
_RRF_K = 60


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
    """Generate a hypothetical regulation excerpt to improve dense retrieval."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a Vietnamese building code expert. Given a question, "
                   "write a plausible regulation paragraph that would answer it. "
                   "Respond in the target language ({language}). Be specific and technical."),
        ("human", "{question}"),
    ])
    chain = prompt | _llm(temperature=0.3)
    result = await chain.ainvoke({"question": question, "language": language})
    return result.content if isinstance(result.content, str) else str(result.content)


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
        WHERE {' AND '.join(where_clauses)}
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
    except Exception:
        return []
    finally:
        await es.close()


def _reciprocal_rank_fusion(
    dense: list[dict[str, Any]],
    sparse: list[dict[str, Any]],
    k: int = _RRF_K,
) -> list[dict[str, Any]]:
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


async def _rerank(query_text: str, candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
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
        query_text = f"{state.question}\n{state.hyde_text}"
        dense, sparse = await _dense_search(
            db, query_text, state.categories, state.jurisdiction, state.top_k
        ), await _sparse_search(
            state.question, state.categories, state.jurisdiction, state.top_k
        )
        fused = _reciprocal_rank_fusion(dense, sparse)
        state.candidates = await _rerank(state.question, fused, state.top_k)
        return state

    async def node_generate(state: _QAState) -> _QAState:
        prompt = ChatPromptTemplate.from_messages([
            ("system", _QA_SYSTEM),
            ("human", _QA_USER),
        ])
        chain = prompt | _llm(temperature=0.1) | JsonOutputParser()
        raw = await chain.ainvoke({
            "language": state.language,
            "question": state.question,
            "context": _format_context(state.candidates),
        })

        citations: list[Citation] = []
        for cit in raw.get("citations", []):
            idx = cit.get("chunk_index")
            if idx is None or idx >= len(state.candidates):
                continue
            src = state.candidates[idx]
            citations.append(Citation(
                regulation_id=UUID(str(src["regulation_id"])),
                regulation=src.get("code_name", cit.get("regulation", "")),
                section=src.get("section_ref") or cit.get("section", ""),
                excerpt=cit.get("excerpt", (src.get("content") or "")[:300]),
                source_url=src.get("source_url"),
            ))

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
        question=question, language=lang, jurisdiction=jurisdiction,
        categories=categories, top_k=top_k,
    )
    final = await app.ainvoke(state)
    result = final["answer"] if isinstance(final, dict) else final.answer
    assert result is not None
    return result


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
        jurisdiction = parameters.location.get("province") or parameters.location.get("jurisdiction")

    param_summary = json.dumps(parameters.model_dump(exclude_none=True), ensure_ascii=False, indent=2)

    for category in target_categories:
        query = _category_probe(category, parameters)
        dense = await _dense_search(db, query, [category], jurisdiction, top_k=8)
        sparse = await _sparse_search(query, [category], jurisdiction, top_k=8)
        fused = _reciprocal_rank_fusion(dense, sparse)
        chunks = await _rerank(query, fused, top_k=6)
        if not chunks:
            continue

        for c in chunks:
            all_reg_ids.add(UUID(str(c["regulation_id"])))

        prompt = ChatPromptTemplate.from_messages([
            ("system", _SCAN_SYSTEM),
            ("human", _SCAN_USER),
        ])
        chain = prompt | _llm(temperature=0.0) | JsonOutputParser()
        try:
            raw = await chain.ainvoke({
                "category": category.value,
                "params": param_summary,
                "context": _format_context(chunks),
            })
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
                all_findings.append(Finding(
                    status=FindingStatus(f.get("status", "WARN")),
                    severity=Severity(f.get("severity", "minor")),
                    category=category,
                    title=f.get("title", ""),
                    description=f.get("description", ""),
                    resolution=f.get("resolution"),
                    citation=citation,
                ))
            except ValueError:
                continue

    return all_findings, list(all_reg_ids)


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
        if parameters else "(not provided)"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", _CHECKLIST_SYSTEM),
        ("human", "Jurisdiction: {jurisdiction}\nProject type: {project_type}\n\nParameters:\n{params}\n\nReturn JSON only."),
    ])
    chain = prompt | _llm(temperature=0.2) | JsonOutputParser()
    raw = await chain.ainvoke({
        "jurisdiction": jurisdiction,
        "project_type": project_type,
        "params": params_summary,
    })

    items: list[ChecklistItem] = []
    for i, item in enumerate(raw.get("items", [])):
        items.append(ChecklistItem(
            id=item.get("id") or f"item-{i}",
            title=item.get("title", ""),
            description=item.get("description"),
            regulation_ref=item.get("regulation_ref"),
            required=bool(item.get("required", True)),
            status="pending",
        ))
    return items
