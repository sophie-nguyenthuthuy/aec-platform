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

class _GeminiEmbeddings:
    """Minimal Embeddings client for `gemini-embedding-001`.

    Why not LangChain's `GoogleGenerativeAIEmbeddings`?
      The 2.0.4 pin we ship doesn't expose `output_dimensionality`, and
      `gemini-embedding-001` (the replacement for the retired
      `text-embedding-004`) defaults to 3072-dim — incompatible with
      our pgvector(768) columns. This thin wrapper calls
      `google.generativeai.embed_content` directly so we can pass the
      `output_dimensionality=768` kwarg through to Google's REST API.

      Surface matches the LangChain `Embeddings` protocol
      (`embed_documents`, `embed_query`) so callers don't have to know
      which client is underneath. The pgvector + retrieval code paths
      (drawbridge, codeguard, bidradar) call only these two methods.
    """

    def __init__(self, *, model: str, api_key: str, output_dim: int = 768,
                 task_type: str = "retrieval_document") -> None:
        # Lazy-import the SDK so module load doesn't fail in tests that
        # never call the embedding path.
        import google.generativeai as genai  # type: ignore[import-not-found]

        genai.configure(api_key=api_key)
        self._genai = genai
        self._model = model
        self._dim = output_dim
        self._task_type = task_type

    def _embed(self, text: str, task_type: str) -> list[float]:
        # `embed_content` returns {"embedding": [...3072 or 768 floats...]}
        # when `output_dimensionality` is forwarded as a kwarg.
        result = self._genai.embed_content(
            model=self._model,
            content=text,
            task_type=task_type,
            output_dimensionality=self._dim,
        )
        return list(result["embedding"])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Sequential — the free-tier free-RPM is generous, and batching
        # via embed_contents (plural) needs SDK >=0.8.5 which we don't
        # pin. ~50ms per call so a 50-doc ingest takes ~2.5s.
        return [self._embed(t, self._task_type) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text, "retrieval_query")

    # Async variants — LangChain retrievers / vectorstores call these
    # when the surrounding code path is async (codeguard pipeline,
    # drawbridge Q&A, assistant retrieval). google-generativeai SDK
    # doesn't expose async embed_content directly, so we run the sync
    # call in a thread to keep the event loop unblocked.
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        import asyncio
        return await asyncio.to_thread(self.embed_documents, texts)

    async def aembed_query(self, text: str) -> list[float]:
        import asyncio
        return await asyncio.to_thread(self.embed_query, text)


def embeddings() -> Any:
    """
    Return an Embeddings client for the active provider.

    `models/gemini-embedding-001` is the active free-tier Gemini model
    (replacing `text-embedding-004` retired by Google May 2026). We force
    768-dim output via `output_dimensionality` so existing pgvector(768)
    columns (migration `0041_gemini_embedding_dim`) accept the vector
    without a schema change.
    """
    from core.config import get_settings  # type: ignore[import-not-found]

    settings = get_settings()
    return _GeminiEmbeddings(
        model=settings.gemini_embedding_model,
        api_key=settings.google_api_key,
        output_dim=768,
        task_type="retrieval_document",
    )
