"""
Single-source-of-truth for LLM + embedding clients used across the
ml pipelines. Every pipeline went through `ChatAnthropic(...)` /
`ChatOpenAI(...)` / `OpenAIEmbeddings(...)` directly before this file
existed — switching providers meant editing 13 files. Now they all go
through `chat_model()` / `chat_model_vision()` / `embeddings()` here,
and switching providers is a one-file change.

Current provider: **Google Gemini** (via langchain-google-genai).
  * Chat        — `gemini-1.5-flash` (free tier, fast, multimodal)
  * Vision      — same model; Gemini Flash is natively multimodal
  * Embeddings  — `text-embedding-004` (768-dim, free tier)

Why Gemini: the deploy target is free-tier Vercel + Supabase + Upstash,
and Vietnam is geo-restricted out of Anthropic + OpenAI billing. Google
AI Studio works from Vietnam, offers a meaningful free tier, and
covers both chat and embedding needs from a single API key.

Provider switching: every pipeline imports from this module. To swap
back to Anthropic + OpenAI (or to anything else), edit the three
factory functions below and the corresponding `langchain-*` package
in `apps/api/requirements.txt`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# `AEC_PIPELINE_DEV_STUB=1` short-circuits every pipeline's _llm() /
# _embedder() to a local stub so smoke tests and integration tests
# don't need real API credentials. Each pipeline still owns its own
# stub class (the shape is task-specific), so this module only
# exposes the env flag — pipelines branch on it themselves.
PIPELINE_DEV_STUB = os.environ.get("AEC_PIPELINE_DEV_STUB") == "1"

# Embedding dimensionality. Anthropic/OpenAI deploys used
# `text-embedding-3-large` at 3072 dims; Gemini's
# `text-embedding-004` is fixed at 768. Every pgvector column is now
# `vector(768)` (see migration `0041_gemini_embedding_dim`). Pipeline
# stubs read this constant so a future provider switch only edits one
# number.
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
    Return a LangChain chat model configured for the active provider.

    Pipelines used to call `ChatAnthropic(model=, temperature=,
    max_tokens=)` or `ChatOpenAI(model=, api_key=, temperature=,
    max_tokens=)` directly; both are now one-line swaps to this
    function.

    `model` override is rarely needed; defaults to the settings-bound
    `gemini_chat_model`. Use it when a pipeline genuinely needs a
    different model for cost/quality reasons (e.g. an expensive ranker
    call wants gemini-1.5-pro while the surrounding pipeline runs on
    gemini-1.5-flash).
    """
    # Import inside the function so `apps.ml.llm` stays importable in
    # environments that haven't installed the langchain google extras
    # (e.g. typecheck-only sandboxes, dev stub mode).
    from langchain_google_genai import ChatGoogleGenerativeAI

    from core.config import get_settings  # type: ignore[import-not-found]

    settings = get_settings()

    return ChatGoogleGenerativeAI(
        model=model or settings.gemini_chat_model,
        google_api_key=settings.google_api_key,
        temperature=temperature,
        max_output_tokens=max_tokens,
        # Disable Gemini's "safety" auto-rewriting — we want the raw
        # model output. Construction-code Q&A occasionally trips the
        # safety filter on innocuous words ("blast", "fire", "rupture")
        # and Gemini will return an empty response with a flag. The
        # platform's own moderation + the citation requirement is the
        # real guardrail.
        safety_settings=None,
        # Gemini's structured-output mode is fragile; let pipelines do
        # their own JSON parsing via `JsonOutputParser`.
    )


def chat_model_vision(
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> Any:
    """
    Chat model configured for multimodal (image + text) input. Gemini
    Flash 1.5 handles both natively, so this is the same call as
    `chat_model()` today — kept as a separate function so pipelines
    that need vision are explicit about their requirement, and so a
    future provider that splits text/vision (e.g. switching to a model
    family where the vision model is different) only edits one place.
    """
    return chat_model(temperature=temperature, max_tokens=max_tokens)


# ---------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------

def embeddings() -> Any:
    """
    Return a LangChain embeddings client for the active provider.

    `text-embedding-004` is the current free-tier Gemini embedding
    model. It outputs 768-dim vectors; downstream pgvector columns are
    sized accordingly (see migration `0041_gemini_embedding_dim` for
    the resize from the historical OpenAI 3072 dim).
    """
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    from core.config import get_settings  # type: ignore[import-not-found]

    settings = get_settings()

    # `output_dimensionality=768` forces gemini-embedding-001 (default
    # 3072-dim) to truncate to 768 so pgvector(768) columns accept it
    # without a schema change. Discovered May 2026 when Google retired
    # `text-embedding-004`. The 768-dim output is mean-pooled and L2-
    # renormalized server-side, so retrieval quality is preserved.
    return GoogleGenerativeAIEmbeddings(
        model=settings.gemini_embedding_model,
        google_api_key=settings.google_api_key,
        # `task_type` improves embedding quality for retrieval. Gemini's
        # embedding model can be tuned for the downstream task; we use
        # `retrieval_document` for ingest and let the retrieval-side
        # encoder pick `retrieval_query`. LangChain's default is
        # `retrieval_document` which is what we want at index time.
        task_type="retrieval_document",
        output_dimensionality=768,
    )
