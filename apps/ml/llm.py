"""
Single-source-of-truth for LLM + embedding clients used across the ml pipelines.

Every pipeline went through `ChatAnthropic(...)` / `ChatOpenAI(...)` /
`OpenAIEmbeddings(...)` / `ChatGoogleGenerativeAI(...)` directly before this
file existed — switching providers meant editing 13 files. Now they all go
through `chat_model()` / `chat_model_vision()` / `embeddings()` here, and
switching providers is a one-file change.

Current provider: **self-hosted OSS via OpenAI-compatible endpoint**
  * Chat        — `qwen2.5:32b-instruct` (Apache-2.0, strong VN + tool/JSON use)
  * Vision      — `qwen2.5vl:7b` (Apache-2.0, multimodal)
  * Embeddings  — `nomic-embed-text` (Apache-2.0, 768-dim — matches pgvector(768))

Why OSS / self-hosted:
  * Data sovereignty — AEC projects involve commercially sensitive design files,
    BOQs, tender intel, and procurement records. Nothing leaves the operator's
    infrastructure.
  * Vietnam reach — no geo-restrictions on Anthropic/OpenAI billing, no Google
    AI Studio quotas.
  * Cost — single GPU box (or even a beefy CPU node with Ollama) replaces the
    per-token bill across every pipeline.

Default endpoint is Ollama at `http://localhost:11434/v1`. For production GPU
deployments, point `LLM_BASE_URL` at a vLLM, SGLang, or LiteLLM gateway — same
OpenAI-compatible surface, no code change.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# `AEC_PIPELINE_DEV_STUB=1` short-circuits every pipeline's _llm() /
# _embedder() to a local stub so smoke tests and integration tests
# don't need real model access. Each pipeline still owns its own
# stub class (the shape is task-specific), so this module only
# exposes the env flag — pipelines branch on it themselves.
PIPELINE_DEV_STUB = os.environ.get("AEC_PIPELINE_DEV_STUB") == "1"

# Embedding dimensionality. `nomic-embed-text` is 768-dim native and matches
# the existing pgvector(768) columns (migration `0041_gemini_embedding_dim`),
# so no schema change is needed when migrating off Gemini.
# Pipeline stubs read this constant so a future provider switch only edits one
# number; if you switch to bge-m3 (1024) or bge-large (1024), bump this and
# add a migration to widen the vector column.
EMBEDDING_DIM = 768


# ---------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------

def chat_model(
    *,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    model: str | None = None,
) -> Any:
    """
    Return a LangChain chat model bound to the configured OSS LLM endpoint.

    Pipelines used to call `ChatAnthropic(...)` / `ChatOpenAI(...)` /
    `ChatGoogleGenerativeAI(...)` directly; all are now a one-line call to this
    factory.

    `model` override is rarely needed; defaults to `settings.llm_chat_model`.
    Use it when a pipeline genuinely needs a different model for cost/quality
    reasons (e.g. an expensive ranker call wants qwen2.5:72b while the
    surrounding pipeline runs on qwen2.5:7b).
    """
    # Lazy import so `apps.ml.llm` stays importable in environments without
    # the langchain-openai extras (typecheck-only sandboxes, dev stub mode).
    from langchain_openai import ChatOpenAI

    from core.config import get_settings  # type: ignore[import-not-found]

    settings = get_settings()

    return ChatOpenAI(
        model=model or settings.llm_chat_model,
        base_url=settings.llm_base_url,
        # OpenAI SDK requires a non-empty key; Ollama ignores it. For vLLM
        # behind an auth proxy set `LLM_API_KEY` in env.
        api_key=settings.llm_api_key or "ollama",
        temperature=temperature,
        max_tokens=max_tokens,
        # Keep the surface deterministic for downstream JsonOutputParser users.
        model_kwargs={"response_format": {"type": "json_object"}} if False else {},
    )


def chat_model_vision(
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> Any:
    """
    Chat model configured for multimodal (image + text) input.

    Uses `settings.llm_vision_model` (default `qwen2.5vl:7b`). LLaVA-Next or
    InternVL also work — anything Ollama / vLLM serves with multimodal support
    via the OpenAI Chat API image-url payload shape.
    """
    from langchain_openai import ChatOpenAI

    from core.config import get_settings  # type: ignore[import-not-found]

    settings = get_settings()
    return ChatOpenAI(
        model=settings.llm_vision_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "ollama",
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------

def embeddings() -> Any:
    """
    Return an Embeddings client bound to the configured OSS embedding model.

    Default: `nomic-embed-text` (768-dim, Apache-2.0). Output dim matches the
    existing pgvector(768) columns. For better Vietnamese retrieval quality at
    the cost of a migration, switch to `bge-m3` (1024-dim) — set
    `LLM_EMBEDDING_MODEL=bge-m3`, bump `EMBEDDING_DIM` to 1024 above, and add
    an alembic migration widening the vector columns.

    The Ollama OpenAI-compatible endpoint exposes
    `POST /v1/embeddings` (model + input → {data: [{embedding: [...]}]}),
    which `langchain_openai.OpenAIEmbeddings` consumes natively when given a
    custom `base_url`.
    """
    from langchain_openai import OpenAIEmbeddings

    from core.config import get_settings  # type: ignore[import-not-found]

    settings = get_settings()
    return OpenAIEmbeddings(
        model=settings.llm_embedding_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "ollama",
        # Disable the openai SDK's automatic dimension/encoding detection so
        # Ollama (which doesn't echo `dimensions` back) doesn't trip it.
        check_embedding_ctx_length=False,
    )
