"""RFI AI pipeline — embedding upserts, similarity search, and grounded
auto-draft responses.

Two LLM-flavoured operations:

  1. **Embed & similarity** — embed `subject + description` of an RFI to a
     3072-dim vector, persist via raw SQL into `rfi_embeddings`, and find
     similar past RFIs using pgvector's cosine `<=>` operator. The same
     embedding endpoint feeds both writes (when an RFI is created or
     edited) and reads (when a designer opens an RFI and asks "have we
     seen this before?").

  2. **Grounded draft response** — RAG over the project's drawing/spec
     chunks (drawbridge.document_chunks). Top-k chunks are retrieved by
     cosine similarity to the RFI text, then handed to Claude with a
     prompt that requires every clause in the response to cite a
     chunk_id. The router persists the draft + citations.

Both paths are defensively graceful: missing API keys → deterministic
fallback so the rest of the system keeps working in tests/dev.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

_ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# pgvector schema in this project is 3072 (matches OpenAI text-embedding-3-large
# truncated to 3072, or Anthropic's voyage-large at 3072).
_EMBEDDING_DIM = 3072
_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-large")
_DRAFT_MODEL_VERSION = f"rfi-draft/v1@{_ANTHROPIC_MODEL}"


# =============================================================================
# Embedding
# =============================================================================


def _format_rfi_for_embedding(subject: str, description: str | None) -> str:
    """Concatenate the human-relevant text. Subject first so it dominates."""
    parts = [subject.strip()]
    if description:
        parts.append(description.strip())
    return "\n\n".join(parts)


async def embed_text(text: str) -> list[float]:
    """Return a 3072-dim embedding for `text`.

    Wraps OpenAI's `text-embedding-3-large` with a 3072-dim output cap.
    On any failure (missing key, network), returns a deterministic
    zero-padded fallback so callers don't have to handle None.
    """
    if not text.strip():
        return [0.0] * _EMBEDDING_DIM
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.info("rfi.embed: openai not installed; using zero fallback")
        return [0.0] * _EMBEDDING_DIM

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return [0.0] * _EMBEDDING_DIM

    client = AsyncOpenAI(api_key=api_key)
    try:
        resp = await client.embeddings.create(
            model="text-embedding-3-large",
            input=text,
            dimensions=_EMBEDDING_DIM,
        )
    except Exception as exc:  # pragma: no cover — network errors
        logger.warning("rfi.embed: embedding call failed: %s", exc)
        return [0.0] * _EMBEDDING_DIM
    return list(resp.data[0].embedding)


async def upsert_rfi_embedding(
    session: Any,
    *,
    organization_id: UUID,
    rfi_id: UUID,
    subject: str,
    description: str | None,
) -> str:
    """Compute the embedding for an RFI and write it via raw SQL.

    Returns the model_version that was used, so the caller can record it
    on the RFI for cache-busting.
    """
    from sqlalchemy import text

    vector = await embed_text(_format_rfi_for_embedding(subject, description))
    vector_lit = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
    await session.execute(
        text(
            """
            INSERT INTO rfi_embeddings (organization_id, rfi_id, model_version, embedding)
            VALUES (:org, :rfi_id, :mv, CAST(:vec AS vector))
            ON CONFLICT (rfi_id) DO UPDATE
              SET embedding = EXCLUDED.embedding,
                  model_version = EXCLUDED.model_version,
                  created_at = NOW()
            """
        ),
        {
            "org": str(organization_id),
            "rfi_id": str(rfi_id),
            "mv": _EMBEDDING_MODEL,
            "vec": vector_lit,
        },
    )
    return _EMBEDDING_MODEL


async def find_similar_rfis(
    session: Any,
    *,
    rfi_id: UUID,
    limit: int = 5,
    max_distance: float = 0.5,
) -> list[dict[str, Any]]:
    """Find RFIs whose embedding is close to the source RFI's, excluding self.

    Returns rows shaped for the SimilarRfi schema: rfi_id / number / subject
    / status / distance / created_at.
    """
    from sqlalchemy import text

    # Compare via the `halfvec` generated column so the HNSW index is hit.
    # The full-precision `embedding` column is kept for re-embedding /
    # recomputation when the model_version changes.
    rows = (
        await session.execute(
            text(
                """
                WITH source AS (
                    SELECT embedding_half FROM rfi_embeddings WHERE rfi_id = :id
                )
                SELECT
                    r.id AS rfi_id,
                    r.number,
                    r.subject,
                    r.status,
                    e.embedding_half <=> source.embedding_half AS distance,
                    r.created_at
                FROM rfi_embeddings e
                CROSS JOIN source
                JOIN rfis r ON r.id = e.rfi_id
                WHERE r.id <> :id
                  AND (e.embedding_half <=> source.embedding_half) <= :max_distance
                ORDER BY distance ASC
                LIMIT :limit
                """
            ),
            {"id": str(rfi_id), "limit": limit, "max_distance": max_distance},
        )
    ).all()

    return [
        {
            "rfi_id": r._mapping["rfi_id"],
            "number": r._mapping["number"],
            "subject": r._mapping["subject"],
            "status": r._mapping["status"],
            "distance": float(r._mapping["distance"]),
            "created_at": r._mapping["created_at"],
        }
        for r in rows
    ]


# =============================================================================
# Grounded draft response
# =============================================================================


async def _retrieve_grounding_chunks(
    session: Any,
    *,
    project_id: UUID | None,
    query_text: str,
    k: int,
) -> list[dict[str, Any]]:
    """Top-k drawing/spec chunks for the RFI, by cosine similarity."""
    from sqlalchemy import text

    if not project_id:
        return []

    vector = await embed_text(query_text)
    if all(v == 0.0 for v in vector):
        # No embedding service available — return a few recent chunks as a
        # weak fallback so the UI can still show something.
        rows = (
            await session.execute(
                text(
                    """
                    SELECT c.id AS chunk_id, c.document_id, c.page_number,
                           c.content, d.drawing_number, d.discipline
                    FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.project_id = :pid AND c.content IS NOT NULL
                    ORDER BY c.page_number NULLS LAST
                    LIMIT :k
                    """
                ),
                {"pid": str(project_id), "k": k},
            )
        ).all()
    else:
        vector_lit = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
        rows = (
            await session.execute(
                text(
                    """
                    SELECT c.id AS chunk_id, c.document_id, c.page_number,
                           c.content, d.drawing_number, d.discipline,
                           c.embedding <=> CAST(:vec AS vector) AS distance
                    FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.project_id = :pid AND c.content IS NOT NULL
                    ORDER BY distance ASC
                    LIMIT :k
                    """
                ),
                {"pid": str(project_id), "vec": vector_lit, "k": k},
            )
        ).all()

    out = []
    for r in rows:
        m = r._mapping
        out.append(
            {
                "chunk_id": m["chunk_id"],
                "document_id": m["document_id"],
                "page_number": m.get("page_number"),
                "snippet": (m.get("content") or "")[:600],
                "drawing_number": m.get("drawing_number"),
                "discipline": m.get("discipline"),
            }
        )
    return out


_DRAFT_PROMPT_SYSTEM = """\
You are a construction design coordinator drafting a response to a contractor
RFI. Be concise, technical, and specific. Every concrete claim in your
response MUST cite at least one source chunk by its chunk_id.

Return ONLY JSON matching this schema:

{{
  "draft_text": "<2-6 sentences. Inline cite by writing [chunk:<short-id>] after each claim>",
  "citations": [
    {{
      "chunk_id": "<exact UUID from input>",
      "document_id": "<exact UUID from input>",
      "page_number": <integer or null>,
      "snippet": "<<=200-char excerpt from chunk content that supports the claim>",
      "drawing_number": "<optional>",
      "discipline": "<optional>"
    }}
  ]
}}

If the retrieved context is insufficient, say so plainly in `draft_text` with
no citations. NEVER fabricate a chunk_id.
"""


async def draft_rfi_response(
    session: Any,
    *,
    rfi: dict[str, Any],
    retrieval_k: int = 6,
) -> dict[str, Any]:
    """RAG over the project's drawings/specs, return a draft + citations."""
    query = _format_rfi_for_embedding(rfi.get("subject", ""), rfi.get("description"))
    chunks = await _retrieve_grounding_chunks(
        session,
        project_id=rfi.get("project_id"),
        query_text=query,
        k=retrieval_k,
    )

    if not chunks:
        return {
            "draft_text": (
                "Không tìm thấy bản vẽ/spec liên quan trong project. "
                "Vui lòng cung cấp thêm tài liệu hoặc trả lời thủ công."
            ),
            "citations": [],
            "model_version": _DRAFT_MODEL_VERSION,
        }

    # Best-effort LLM call.
    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError:
        return _heuristic_draft(rfi, chunks)

    if not os.getenv("ANTHROPIC_API_KEY"):
        return _heuristic_draft(rfi, chunks)

    chunk_payload = [
        {
            "chunk_id": str(c["chunk_id"]),
            "document_id": str(c["document_id"]),
            "page_number": c.get("page_number"),
            "snippet": c["snippet"],
            "drawing_number": c.get("drawing_number"),
            "discipline": c.get("discipline"),
        }
        for c in chunks
    ]
    payload = json.dumps(
        {
            "rfi": {"subject": rfi.get("subject"), "description": rfi.get("description")},
            "chunks": chunk_payload,
        },
        ensure_ascii=False,
    )
    prompt = ChatPromptTemplate.from_messages(
        [("system", _DRAFT_PROMPT_SYSTEM), ("human", "{payload}")]
    )
    llm = ChatAnthropic(model=_ANTHROPIC_MODEL, temperature=0.1, max_tokens=1024)
    chain = prompt | llm | JsonOutputParser()
    try:
        out = await chain.ainvoke({"payload": payload})
    except Exception as exc:  # pragma: no cover — network/parse errors
        logger.warning("rfi.draft: LLM call failed: %s", exc)
        return _heuristic_draft(rfi, chunks)

    valid_ids = {str(c["chunk_id"]) for c in chunks}
    cleaned: list[dict[str, Any]] = []
    for cit in out.get("citations") or []:
        cid = str(cit.get("chunk_id", "") or "")
        if cid not in valid_ids:
            continue  # hallucination guardrail
        cleaned.append(
            {
                "chunk_id": cid,
                "document_id": str(cit.get("document_id", "") or ""),
                "page_number": cit.get("page_number"),
                "snippet": str(cit.get("snippet", "") or "")[:200],
                "drawing_number": cit.get("drawing_number"),
                "discipline": cit.get("discipline"),
            }
        )
    return {
        "draft_text": str(out.get("draft_text", "") or ""),
        "citations": cleaned,
        "model_version": _DRAFT_MODEL_VERSION,
    }


def _heuristic_draft(rfi: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """No-LLM fallback: stitch together the top chunks as a draft so the
    user sees *something* and can edit. Preserves citation structure."""
    if not chunks:
        return {
            "draft_text": "Không có dữ liệu để soạn thảo phản hồi.",
            "citations": [],
            "model_version": _DRAFT_MODEL_VERSION + "+fallback",
        }
    citations = [
        {
            "chunk_id": str(c["chunk_id"]),
            "document_id": str(c["document_id"]),
            "page_number": c.get("page_number"),
            "snippet": c["snippet"][:200],
            "drawing_number": c.get("drawing_number"),
            "discipline": c.get("discipline"),
        }
        for c in chunks[:3]
    ]

    def _ref_label(c: dict[str, Any]) -> str:
        head = c.get("drawing_number") or str(c["document_id"])
        page = c.get("page_number")
        return f"{head} p.{page}" if page else head

    refs = ", ".join(_ref_label(c) for c in chunks[:3])
    draft = (
        f"Tham khảo tài liệu liên quan: {refs}. "
        "(Nháp tự động — vui lòng kiểm tra và chỉnh sửa trước khi gửi.)"
    )
    return {
        "draft_text": draft,
        "citations": citations,
        "model_version": _DRAFT_MODEL_VERSION + "+fallback",
    }


__all__ = [
    "draft_rfi_response",
    "embed_text",
    "find_similar_rfis",
    "upsert_rfi_embedding",
]
