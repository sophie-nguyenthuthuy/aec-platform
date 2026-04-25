"""End-to-end smoke test for the full CODEGUARD query pipeline.

`_dense_search` has its own integration test (test_codeguard_retrieval_integration)
and the router has unit tests that mock `answer_regulation_query` at the boundary.
This test fills the gap in between: it drives the full LangGraph pipeline
(`expand → retrieve → generate`) against a real Postgres, with the external
model calls (OpenAI embeddings, Anthropic HyDE + generation) stubbed so no API
keys or network are required.

What it proves (the contract nothing else asserts):
  * the question + HyDE text flow through `_dense_search` → `_rrf` → `_rerank`
    without tripping over the halfvec SQL;
  * `node_generate` feeds the retrieved chunks into the LLM prompt and parses
    the canned JSON response correctly;
  * `Citation` objects are shaped from the *retrieved chunks* (regulation_id,
    section_ref from Postgres), not blindly trusted from the LLM output —
    this is the property the grounding guard (next task) will harden further;
  * `related_questions` is clipped to 3, `confidence` is carried through.

Usage:
    TEST_DATABASE_URL=postgresql+asyncpg://aec:aec@localhost:5432/aec_test \\
      python -m pytest apps/ml/tests/test_codeguard_query_pipeline_integration.py -v

A failure here probably means either (a) the DB schema drifted (halfvec column
missing — run migration 0009) or (b) the pipeline's LLM/embedder factories
were renamed and this test's monkeypatch targets are stale.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# Same sys.path dance as the retrieval integration test — pipelines.codeguard
# imports from schemas.codeguard (which lives under apps/api).
_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — skipping live-Postgres query pipeline smoke test. "
        "Set it to a DB with codeguard migrations applied."
    ),
)

EMBED_DIM = 3072


def _axis_vec(i: int, magnitude: float = 1.0) -> list[float]:
    v = [0.0] * EMBED_DIM
    v[i] = magnitude
    return v


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_query_pipeline_end_to_end_with_stub_llm(session, monkeypatch):
    """Full pipeline with real retrieval + fake LLM.

    Stubs three things to avoid external calls:
      1. `_embedder()` → returns a vec aligned with our seeded chunk on axis 0.
      2. `_hyde_expand()` → returns "" (otherwise it would call Anthropic).
      3. `_llm()` → returns a FakeListChatModel that yields canned JSON; this
         plumbs through `prompt | llm | JsonOutputParser()` unchanged.

    Seeds one regulation with one chunk so retrieval is deterministic and the
    canned LLM response's `chunk_index=0` maps to a predictable Citation.
    """
    import pipelines.codeguard as cg
    from pipelines.codeguard import answer_regulation_query

    tag = uuid4().hex[:12]
    reg_code = f"TEST_QUERY_{tag}"
    reg_id = uuid4()

    # --- Seed ---------------------------------------------------------------
    await session.execute(
        text(
            """
            INSERT INTO regulations
                (id, country_code, jurisdiction, code_name, category, language)
            VALUES (:id, 'VN', 'national', :code, 'fire_safety', 'vi')
            """
        ),
        {"id": str(reg_id), "code": reg_code},
    )
    chunk_content = (
        "Chiều rộng thông thủy của hành lang thoát nạn trong nhà chung cư "
        "không được nhỏ hơn 1.4 m."
    )
    await session.execute(
        text(
            """
            INSERT INTO regulation_chunks
                (id, regulation_id, section_ref, content, embedding)
            VALUES (gen_random_uuid(), :rid, '3.2.1', :content, CAST(:vec AS vector))
            """
        ),
        {
            "rid": str(reg_id),
            "content": chunk_content,
            "vec": _vec_literal(_axis_vec(0)),
        },
    )
    await session.commit()

    # --- Stubs --------------------------------------------------------------
    class _FakeEmbedder:
        async def aembed_query(self, _q: str) -> list[float]:
            # Axis-0 match — guarantees the seeded chunk is cosine-nearest.
            return _axis_vec(0, magnitude=1.0)

    monkeypatch.setattr(cg, "_embedder", lambda: _FakeEmbedder())

    async def _no_hyde(_question: str, _language: str) -> str:
        return ""

    monkeypatch.setattr(cg, "_hyde_expand", _no_hyde)

    canned_json = json.dumps(
        {
            "answer": "Hành lang thoát nạn phải rộng tối thiểu 1.4 m.",
            "confidence": 0.88,
            "citations": [
                {
                    "chunk_index": 0,
                    "regulation": reg_code,
                    "section": "3.2.1",
                    # Genuine substring of the seeded chunk — exercises the
                    # `_ground_citations` happy path (LLM excerpt preserved
                    # because it faithfully appears in the source).
                    "excerpt": "không được nhỏ hơn 1.4 m",
                }
            ],
            # Pipeline clips to 3 — include 4 to prove the clip works.
            "related_questions": [
                "Chiều rộng cầu thang thoát nạn?",
                "Yêu cầu bậc chịu lửa?",
                "Khoảng cách thoát nạn tối đa?",
                "Số lối thoát nạn tối thiểu?",
            ],
        },
        ensure_ascii=False,
    )
    fake_model = FakeListChatModel(responses=[canned_json])
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.1: fake_model)

    # --- Run ----------------------------------------------------------------
    try:
        result = await answer_regulation_query(
            db=session,
            question="Chiều rộng hành lang thoát nạn tối thiểu?",
            language="vi",
            jurisdiction=None,
            categories=None,
            top_k=8,
        )

        # Answer + confidence carried through.
        assert result.answer.startswith("Hành lang"), result.answer
        assert result.confidence == pytest.approx(0.88)

        # Exactly one citation, shaped from the retrieved chunk (not the LLM).
        assert len(result.citations) == 1, result.citations
        cit = result.citations[0]
        # regulation_id must come from the DB row, not the LLM's free-form
        # "regulation" string — this is the grounding invariant.
        assert cit.regulation_id == reg_id
        assert cit.regulation == reg_code  # code_name from the joined row
        assert cit.section == "3.2.1"
        # Excerpt came from the LLM AND was preserved because it's a faithful
        # substring of the seeded chunk (grounding guard happy path).
        assert cit.excerpt == "không được nhỏ hơn 1.4 m"

        # Related-questions clipping.
        assert len(result.related_questions) == 3

    finally:
        await session.execute(
            text("DELETE FROM regulations WHERE id = :id"),
            {"id": str(reg_id)},
        )
        await session.commit()
