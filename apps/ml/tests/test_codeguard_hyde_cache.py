"""Unit tests for the TTL-cached HyDE expansion in `pipelines.codeguard`.

What this test contract guarantees:
  * A second call with the same `(question, language)` reuses the cached
    value — the LLM factory is invoked exactly once even though
    `_hyde_expand` is awaited twice.
  * Different questions don't share a cache entry.
  * Different languages don't share a cache entry (`(q, "vi")` vs
    `(q, "en")` are distinct keys).
  * A failed call (LLM raises) does NOT populate the cache; a retry
    invokes the LLM again.
  * `_hyde_clear_cache()` actually clears.

Why these matter: the cache is the single optimization in the pipeline
that materially affects unit-economics. A regression that silently
bypasses the cache (e.g. the key tuple changes shape, or the cache
gets cleared between calls by accident) doubles Anthropic spend on
HyDE without changing observable behaviour. These tests are the
canary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with an empty cache. Without this, cache state
    leaks across tests in arbitrary order — making failures hard to
    reproduce."""
    import pipelines.codeguard as cg

    cg._hyde_clear_cache()
    yield
    cg._hyde_clear_cache()


def _install_counted_llm(monkeypatch, responses: list[str]) -> tuple[FakeListChatModel, list[int]]:
    """Install a fake `_llm` factory that counts construction calls.

    Counting at the factory boundary rather than `.ainvoke()` is the
    right semantic here: `_hyde_expand` builds `chain = prompt | _llm()
    | …` only on a cache miss. If the cache hit short-circuits before
    the chain is built, `_llm` is never called — which is exactly what
    we want to assert. (Going via the Pydantic model directly is
    awkward because `FakeListChatModel` fields are managed.)

    Returns `(model, calls)` — `len(calls)` is the live counter.
    """
    import pipelines.codeguard as cg

    model = FakeListChatModel(responses=responses)
    calls: list[int] = []

    def _factory(temperature: float = 0.1) -> FakeListChatModel:
        calls.append(1)
        return model

    monkeypatch.setattr(cg, "_llm", _factory)
    return model, calls


async def test_second_call_with_same_key_skips_llm(monkeypatch):
    """The whole point of the cache: same (question, language) → 1 LLM call."""
    import pipelines.codeguard as cg

    _, calls = _install_counted_llm(monkeypatch, ["hypothetical regulation paragraph"] * 5)

    a = await cg._hyde_expand("Chiều rộng hành lang?", "vi")
    b = await cg._hyde_expand("Chiều rộng hành lang?", "vi")

    assert a == b == "hypothetical regulation paragraph"
    assert len(calls) == 1, (
        f"Expected exactly one LLM construction; got {len(calls)}. "
        "Cache key changed shape, or the cache is being cleared between calls."
    )


async def test_different_questions_get_separate_cache_entries(monkeypatch):
    """A cache that smashed all questions together would make HyDE useless
    by replaying the wrong expansion. Two questions → two LLM calls."""
    import pipelines.codeguard as cg

    _, calls = _install_counted_llm(monkeypatch, ["expansion-A", "expansion-B"])

    a = await cg._hyde_expand("Question one?", "vi")
    b = await cg._hyde_expand("Question two?", "vi")

    assert a == "expansion-A"
    assert b == "expansion-B"
    assert len(calls) == 2


async def test_different_languages_get_separate_cache_entries(monkeypatch):
    """Same question text in different languages MUST produce different
    expansions — the prompt explicitly bakes language into the system
    message. A cache key that ignored language would replay e.g. a
    Vietnamese expansion for an English question."""
    import pipelines.codeguard as cg

    _, calls = _install_counted_llm(monkeypatch, ["vi-expansion", "en-expansion"])

    vi = await cg._hyde_expand("Chiều rộng hành lang?", "vi")
    en = await cg._hyde_expand("Chiều rộng hành lang?", "en")

    assert vi == "vi-expansion"
    assert en == "en-expansion"
    assert len(calls) == 2

    # And both are independently cached — re-asking either doesn't
    # bump the counter.
    await cg._hyde_expand("Chiều rộng hành lang?", "vi")
    await cg._hyde_expand("Chiều rộng hành lang?", "en")
    assert len(calls) == 2


async def test_llm_failure_does_not_poison_the_cache(monkeypatch):
    """If the LLM raises, the cache entry MUST stay empty so a retry can
    actually retry. Caching an exception or a partial result would
    silently break the pipeline for that question for an hour.

    We simulate failure at the factory level — semantically equivalent to
    the LLM call failing (the exception propagates through `_hyde_expand`
    before any cache write), and avoids fighting Pydantic's
    immutable-instance attribute behaviour on `FakeListChatModel`.
    """
    import pipelines.codeguard as cg

    def _exploding_factory(temperature: float = 0.1):
        raise RuntimeError("Anthropic 503")

    monkeypatch.setattr(cg, "_llm", _exploding_factory)

    with pytest.raises(RuntimeError, match="Anthropic 503"):
        await cg._hyde_expand("Doomed question", "vi")

    # Swap to a working model and confirm the retry actually retries
    # (i.e. the cache wasn't populated with anything during the failure).
    _, recovery_calls = _install_counted_llm(monkeypatch, ["recovered expansion"])

    result = await cg._hyde_expand("Doomed question", "vi")
    assert result == "recovered expansion"
    assert len(recovery_calls) == 1, "Retry didn't actually invoke the LLM — cache was poisoned."


async def test_clear_cache_resets_state(monkeypatch):
    """The test helper does what it says: post-clear, the same key
    triggers a fresh LLM call."""
    import pipelines.codeguard as cg

    _, calls = _install_counted_llm(monkeypatch, ["first call", "second call"])

    await cg._hyde_expand("Same question?", "vi")
    await cg._hyde_expand("Same question?", "vi")  # cached
    assert len(calls) == 1

    cg._hyde_clear_cache()
    await cg._hyde_expand("Same question?", "vi")  # re-fetched
    assert len(calls) == 2
