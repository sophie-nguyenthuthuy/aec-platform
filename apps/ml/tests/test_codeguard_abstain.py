"""Tests for the zero-retrieval abstain path in the CODEGUARD query pipeline.

Why this matters: if `_hybrid_search` returns [] (question outside the
corpus, filters match nothing), invoking the LLM with an empty `context`
field reliably produces a confident-sounding hallucination — the worst
failure mode for a compliance tool. The abstain path short-circuits before
the LLM call, returning a canned "no relevant regulations" message with
confidence=0.0 and no citations.

Two layers of coverage:
  1. `_abstain_response(language)` in isolation — shape + localisation.
  2. End-to-end: stub retrieval to return [], assert `_llm` is NEVER called
     and the output is the canned abstain. This is the guarantee that
     matters in prod — not a LangChain-wiring test, a "we don't burn tokens
     AND we don't hallucinate when we have nothing to say" test.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------- _abstain_response ---------------------------------------------


def test_abstain_response_vietnamese():
    from pipelines.codeguard import _abstain_response

    r = _abstain_response("vi")
    assert "Không tìm thấy" in r.answer
    assert r.confidence == 0.0
    assert r.citations == []
    assert r.related_questions == []


def test_abstain_response_english():
    from pipelines.codeguard import _abstain_response

    r = _abstain_response("en")
    assert "No relevant regulations" in r.answer
    assert r.confidence == 0.0


def test_abstain_response_unknown_language_falls_back_to_english():
    """If a new language slips through (pydantic Literal should prevent it
    upstream, but defend in depth), we default to English rather than
    blowing up or returning an empty string."""
    from pipelines.codeguard import _abstain_response

    r = _abstain_response("fr")
    assert r.answer  # not empty
    assert "No relevant regulations" in r.answer


# ---------- End-to-end: LLM must NOT be called on empty retrieval --------


async def test_pipeline_abstains_without_calling_llm_when_retrieval_empty(monkeypatch):
    """The load-bearing contract: empty retrieval → no LLM call, no tokens
    burned, no hallucinated answer.

    We stub `_hybrid_search` to return [], then install an `_llm` factory
    that raises `AssertionError` if it's ever constructed. If the abstain
    path works the LLM factory is never called. HyDE is stubbed too — it
    has its own LLM call we don't want to trip.
    """
    import pipelines.codeguard as cg
    from pipelines.codeguard import answer_regulation_query

    async def _no_hyde(_q, _lang):
        return ""

    monkeypatch.setattr(cg, "_hyde_expand", _no_hyde)

    async def _empty_hybrid(*_args, **_kwargs):
        return []

    monkeypatch.setattr(cg, "_hybrid_search", _empty_hybrid)

    def _llm_must_not_be_called(*_a, **_kw):
        raise AssertionError(
            "_llm was constructed on the zero-retrieval path — "
            "the abstain guard should have short-circuited before this."
        )

    monkeypatch.setattr(cg, "_llm", _llm_must_not_be_called)

    result = await answer_regulation_query(
        db=None,  # not touched — retrieval is stubbed
        question="Chiều rộng hành lang thoát nạn tối thiểu?",
        language="vi",
        jurisdiction=None,
        categories=None,
        top_k=8,
    )

    # Canned abstain — Vietnamese matches the request language.
    assert "Không tìm thấy" in result.answer
    assert result.confidence == 0.0
    assert result.citations == []
    assert result.related_questions == []


async def test_pipeline_abstain_respects_language_parameter(monkeypatch):
    """`language='en'` → English abstain, not Vietnamese default."""
    import pipelines.codeguard as cg
    from pipelines.codeguard import answer_regulation_query

    async def _no_hyde(_q, _lang):
        return ""

    async def _empty_hybrid(*_args, **_kwargs):
        return []

    def _llm_must_not_be_called(*_a, **_kw):
        raise AssertionError("_llm should not be constructed on abstain path")

    monkeypatch.setattr(cg, "_hyde_expand", _no_hyde)
    monkeypatch.setattr(cg, "_hybrid_search", _empty_hybrid)
    monkeypatch.setattr(cg, "_llm", _llm_must_not_be_called)

    result = await answer_regulation_query(
        db=None,
        question="What is the minimum corridor width for evacuation routes?",
        language="en",
        jurisdiction=None,
        categories=None,
        top_k=8,
    )
    assert "No relevant regulations" in result.answer
    assert result.confidence == 0.0


async def test_pipeline_language_autodetected_when_none(monkeypatch):
    """`language=None` → autodetect from question. Vietnamese diacritics
    in the question → Vietnamese abstain."""
    import pipelines.codeguard as cg
    from pipelines.codeguard import answer_regulation_query

    async def _no_hyde(_q, _lang):
        return ""

    async def _empty_hybrid(*_args, **_kwargs):
        return []

    def _llm_must_not_be_called(*_a, **_kw):
        raise AssertionError("_llm should not be constructed on abstain path")

    monkeypatch.setattr(cg, "_hyde_expand", _no_hyde)
    monkeypatch.setattr(cg, "_hybrid_search", _empty_hybrid)
    monkeypatch.setattr(cg, "_llm", _llm_must_not_be_called)

    # Question has Vietnamese diacritics → _detect_language returns "vi".
    result = await answer_regulation_query(
        db=None,
        question="Chiều rộng hành lang thoát nạn tối thiểu?",
        language=None,
        jurisdiction=None,
        categories=None,
        top_k=8,
    )
    assert "Không tìm thấy" in result.answer
