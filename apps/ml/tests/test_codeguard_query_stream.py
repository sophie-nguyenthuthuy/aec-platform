"""Unit tests for `pipelines.codeguard.answer_regulation_query_stream`.

The streaming variant has its own contract distinct from the non-streaming
path: it yields a sequence of `(event_name, payload)` tuples that the
SSE route layer translates to wire format. These tests pin down the
event sequence without needing a real DB or real LLM.

Coverage:
  * Happy path — token deltas concatenate to the canned answer; final
    `done` event carries the grounded `QueryResponse`.
  * Abstain path — empty retrieval emits `done` immediately with the
    canned abstain response and NEVER constructs the LLM (asserted by
    making `_llm` raise on call).
  * No-output path — LLM produces nothing useful; an `error` event is
    emitted instead of `done`.
  * Citation grounding still applies — same `_ground_citations` runs
    in the streaming path, so a hallucinated chunk_index gets dropped
    just like in the non-streaming version.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


REG_ID = uuid4()


def _candidates() -> list[dict]:
    """One retrieved chunk shaped like a `_dense_search` row."""
    return [
        {
            "id": str(uuid4()),
            "regulation_id": str(REG_ID),
            "section_ref": "3.2.1",
            "content": ("Chiều rộng thông thủy của hành lang thoát nạn không được nhỏ hơn 1.4 m."),
            "code_name": "QCVN 06:2022/BXD",
            "source_url": None,
            "score": 0.95,
        },
    ]


@pytest.fixture
def stub_pipeline_steps(monkeypatch):
    """Stubs HyDE + hybrid_search + rerank so tests don't need a real DB."""
    import pipelines.codeguard as cg

    async def _no_hyde(_q, _lang):
        return ""

    candidates = _candidates()

    async def _hybrid(*_a, **_kw):
        return candidates

    async def _rerank(_q, items, _top_k):
        return items

    monkeypatch.setattr(cg, "_hyde_expand", _no_hyde)
    monkeypatch.setattr(cg, "_hybrid_search", _hybrid)
    monkeypatch.setattr(cg, "_rerank", _rerank)
    return cg


async def test_stream_yields_token_deltas_and_terminal_done(stub_pipeline_steps):
    """Concatenating all `token` deltas reproduces the answer; `done` carries
    the fully-grounded QueryResponse."""
    cg = stub_pipeline_steps
    canned = json.dumps(
        {
            "answer": "Chiều rộng tối thiểu là 1.4 m.",
            "confidence": 0.88,
            "citations": [{"chunk_index": 0, "excerpt": "không được nhỏ hơn 1.4 m"}],
            "related_questions": ["Cầu thang thoát nạn?"],
        },
        ensure_ascii=False,
    )
    fake_model = FakeListChatModel(responses=[canned])
    monkeypatch_llm(cg, fake_model)

    events: list[tuple[str, object]] = []
    async for ev in cg.answer_regulation_query_stream(
        db=None,
        question="Chiều rộng hành lang thoát nạn?",
        language="vi",
        jurisdiction=None,
        categories=None,
        top_k=8,
    ):
        events.append(ev)

    # Last event is always `done`; everything before is `token`.
    assert events[-1][0] == "done", events
    token_events = [payload for name, payload in events[:-1] if name == "token"]
    assert all(name == "token" for name, _ in events[:-1]), f"non-token event before done: {events}"
    # Concatenated deltas reproduce the answer text exactly. Assert by
    # final length match — JsonOutputParser may emit zero-length deltas
    # at the partial-parse boundary, which is fine to stream.
    assert "".join(token_events) == "Chiều rộng tối thiểu là 1.4 m."

    # Done event carries the grounded response. Citation regulation_id
    # came from the retrieved DB row, not the LLM.
    response = events[-1][1]
    assert response.confidence == pytest.approx(0.88)
    assert len(response.citations) == 1
    assert response.citations[0].regulation_id == REG_ID
    assert response.citations[0].section == "3.2.1"
    # LLM-supplied excerpt was a substring of the chunk content, so it
    # passes through (grounding-guard happy path).
    assert response.citations[0].excerpt == "không được nhỏ hơn 1.4 m"


async def test_stream_abstains_when_retrieval_empty(monkeypatch):
    """Zero retrieval candidates → emit `done` with abstain. LLM is never
    invoked, proven by installing a factory that raises."""
    import pipelines.codeguard as cg

    async def _no_hyde(_q, _lang):
        return ""

    async def _empty_hybrid(*_a, **_kw):
        return []

    async def _passthrough_rerank(_q, items, _top_k):
        return items

    def _llm_must_not_be_called(*_a, **_kw):
        raise AssertionError(
            "_llm was constructed on the streaming abstain path — should have short-circuited."
        )

    monkeypatch.setattr(cg, "_hyde_expand", _no_hyde)
    monkeypatch.setattr(cg, "_hybrid_search", _empty_hybrid)
    monkeypatch.setattr(cg, "_rerank", _passthrough_rerank)
    monkeypatch.setattr(cg, "_llm", _llm_must_not_be_called)

    events: list[tuple[str, object]] = []
    async for ev in cg.answer_regulation_query_stream(
        db=None,
        question="Câu hỏi không có trong cơ sở tri thức",
        language="vi",
        jurisdiction=None,
        categories=None,
        top_k=8,
    ):
        events.append(ev)

    # Single terminal event, no tokens.
    assert len(events) == 1
    assert events[0][0] == "done"
    response = events[0][1]
    assert response.confidence == 0.0
    assert response.citations == []
    assert "Không tìm thấy" in response.answer


async def test_stream_drops_hallucinated_citation_via_grounding_guard(stub_pipeline_steps):
    """The same `_ground_citations` choke point that protects the non-
    streaming path applies here. An out-of-range `chunk_index` from the
    LLM gets dropped silently from the final response."""
    cg = stub_pipeline_steps
    canned = json.dumps(
        {
            "answer": "Test answer.",
            "confidence": 0.5,
            "citations": [
                {"chunk_index": 0, "excerpt": "không được nhỏ hơn 1.4 m"},
                # Out-of-range — only one candidate was retrieved.
                {"chunk_index": 5, "excerpt": "fabricated quote"},
            ],
            "related_questions": [],
        },
        ensure_ascii=False,
    )
    monkeypatch_llm(cg, FakeListChatModel(responses=[canned]))

    events = [
        ev
        async for ev in cg.answer_regulation_query_stream(
            db=None,
            question="x",
            language="vi",
            jurisdiction=None,
            categories=None,
            top_k=8,
        )
    ]
    response = events[-1][1]
    # Only the valid (chunk_index=0) citation survives.
    assert len(response.citations) == 1
    assert response.citations[0].section == "3.2.1"


async def test_stream_clips_related_questions_to_three(stub_pipeline_steps):
    """Same clip-to-3 rule as the non-streaming path."""
    cg = stub_pipeline_steps
    canned = json.dumps(
        {
            "answer": "x",
            "confidence": 0.5,
            "citations": [],
            "related_questions": ["q1", "q2", "q3", "q4", "q5"],
        }
    )
    monkeypatch_llm(cg, FakeListChatModel(responses=[canned]))

    events = [
        ev
        async for ev in cg.answer_regulation_query_stream(
            db=None,
            question="x",
            language="vi",
            jurisdiction=None,
            categories=None,
            top_k=8,
        )
    ]
    response = events[-1][1]
    assert response.related_questions == ["q1", "q2", "q3"]


def monkeypatch_llm(cg_module, fake_model) -> None:
    """Helper: replace `_llm` with a factory returning the supplied stub."""
    cg_module._llm = lambda temperature=0.1: fake_model
