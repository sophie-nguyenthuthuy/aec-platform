"""Tier 4: answer-quality eval against the seeded QCVN 06:2022/BXD fixture.

This is the test that catches prompt drift, model-version regressions, and
retrieval quality degradation — none of which the mechanical (Tier 1-3)
tests notice. It runs the *real* pipeline against *real* OpenAI embeddings
and *real* Anthropic generation, asserting that hand-curated questions
return citations pointing at the expected sections.

This costs money. Roughly 8 questions x (1 HyDE call + 1 generate call +
1 embedding) ≈ 25-40¢ per run depending on context length. Don't gate
this on per-commit CI — gate it on:
  * a manual `make eval-codeguard` target, or
  * a nightly scheduled job, or
  * a release-candidate quality gate.

Required environment:
    TEST_DATABASE_URL=postgresql+asyncpg://aec:aec@localhost:5437/aec
    OPENAI_API_KEY=...
    ANTHROPIC_API_KEY=...

Required prior state: the QCVN 06:2022/BXD fixture must be seeded in the
target database. Run `make seed-codeguard` once if it isn't.

What this test asserts (per pair):
  * Pipeline returns at least one citation.
  * The expected section_ref appears among the cited sections (not
    necessarily the only one — many questions are cross-cutting).
  * Confidence is non-trivial (>0.3) — proves the abstain path didn't
    fire when it shouldn't have.

What this test does NOT assert:
  * Exact answer wording (LLMs are nondeterministic).
  * Citation order.
  * No additional citations beyond the expected one.

A failure here means either:
  (a) retrieval is no longer surfacing the right chunk for a known query
      (prompt-engineer the HyDE template, tune RRF weights, verify
      embedding model version),
  (b) the LLM is no longer choosing to cite the relevant chunk (review
      the system prompt in `_QA_SYSTEM`),
  (c) the fixture wasn't seeded — re-run `make seed-codeguard`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# All three must be present — partial coverage produces misleading
# results. Better to skip cleanly with a single explanatory reason.
_MISSING = [
    name
    for name, val in [
        ("TEST_DATABASE_URL", TEST_DATABASE_URL),
        ("OPENAI_API_KEY", OPENAI_API_KEY),
        ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    ]
    if not val
]

pytestmark = pytest.mark.skipif(
    bool(_MISSING),
    reason=(
        f"Tier 4 quality eval skipped — missing env vars: {', '.join(_MISSING)}. "
        "This test runs the real LLM and costs money; gate on manual/nightly "
        "runs, not per-commit CI."
    ),
)

FIXTURE_CODE_NAME = "QCVN 06:2022/BXD"


# ---------- Q&A pairs ----------------------------------------------------

# Hand-curated questions and the section_ref each *should* be answered
# from. The fixture (apps/ml/fixtures/codeguard/qcvn_06_2022_excerpt.md)
# has 13 sections; we pick 8 that have unambiguous one-section answers.
# Cross-cutting questions ("evacuation in general?") are deliberately
# excluded — they make the citation assertion brittle.
QA_PAIRS: list[tuple[str, str, str]] = [
    # (question_id, question_text, expected_section_ref)
    (
        "corridor_width",
        "Chiều rộng tối thiểu của hành lang thoát nạn trong nhà chung cư là bao nhiêu?",
        "3.2.1",
    ),
    (
        "exit_count",
        "Số lượng lối thoát nạn tối thiểu trên mỗi tầng được quy định thế nào?",
        "3.1",
    ),
    (
        "fire_resistance",
        "Bậc chịu lửa của nhà được phân loại như thế nào?",
        "2.1",
    ),
    (
        "fire_compartment",
        "Khoang cháy có yêu cầu gì về diện tích và bậc chịu lửa?",
        "2.2",
    ),
    (
        "evacuation_distance",
        "Khoảng cách thoát nạn tối đa cho phép là bao nhiêu mét?",
        "3.3",
    ),
    (
        "fire_alarm",
        "Hệ thống báo cháy tự động yêu cầu lắp đặt ở đâu?",
        "4.1",
    ),
    (
        "smoke_extraction",
        "Hệ thống hút khói hành lang có yêu cầu gì?",
        "5.1",
    ),
    (
        "stair_pressurization",
        "Tạo áp buồng thang bộ yêu cầu gì?",
        "5.2",
    ),
]


# ---------- DB session ---------------------------------------------------


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _require_fixture_seeded(session):
    """Skip individual cases (rather than failing) if the fixture isn't in
    the target DB — keeps the failure message actionable instead of
    drowning in 8 confusing "no citations returned" errors."""
    row = await session.execute(
        text("SELECT id FROM regulations WHERE code_name = :code"),
        {"code": FIXTURE_CODE_NAME},
    )
    if row.scalar_one_or_none() is None:
        pytest.skip(
            f"Quality eval requires the {FIXTURE_CODE_NAME} fixture to be "
            "seeded. Run `make seed-codeguard` against TEST_DATABASE_URL."
        )


# ---------- The eval -----------------------------------------------------


@pytest.mark.parametrize(
    "question_id,question,expected_section",
    QA_PAIRS,
    ids=[p[0] for p in QA_PAIRS],
)
async def test_pipeline_cites_expected_section(session, question_id, question, expected_section):
    """For each curated Q&A pair, run the full pipeline and assert the
    expected section appears in the returned citations.

    Soft on answer wording, firm on citation grounding."""
    from pipelines.codeguard import answer_regulation_query
    from schemas.codeguard import RegulationCategory

    result = await answer_regulation_query(
        db=session,
        question=question,
        language="vi",
        # Constrain to fire_safety so our 8-question fixture isn't competing
        # with whatever else may be seeded in the dev DB. The QCVN fixture
        # is categorised as fire_safety per the make-seed target.
        categories=[RegulationCategory.fire_safety],
        jurisdiction=None,
        top_k=8,
    )

    assert result.confidence > 0.3, (
        f"[{question_id}] Pipeline returned low confidence "
        f"({result.confidence:.2f}) — likely the abstain path fired when "
        f"it shouldn't have. Question: {question!r}"
    )
    assert len(result.citations) >= 1, (
        f"[{question_id}] No citations returned. Either retrieval missed "
        f"or the LLM declined to cite. Answer: {result.answer[:200]!r}"
    )

    cited_sections = [c.section for c in result.citations]
    assert expected_section in cited_sections, (
        f"[{question_id}] Expected §{expected_section} in citations, got "
        f"{cited_sections}. Answer: {result.answer[:200]!r}\n"
        f"This is the diagnostic for retrieval drift — verify the chunk "
        f"with section_ref={expected_section!r} is in the DB and that "
        f"the embedding cosine ranking still surfaces it for this query."
    )


# ---------- Out-of-corpus abstain ----------------------------------------


async def test_pipeline_abstains_for_out_of_corpus_question(session):
    """Sanity check on the abstain path against real retrieval. The
    fixture is fire-safety only — a question about an entirely different
    domain (e.g. soil bearing capacity for foundations) should retrieve
    nothing in fire_safety category and trigger abstain.

    We constrain to fire_safety to force the abstain rather than depend
    on the question being globally absent — the dev DB may have other
    seeded regulations that incidentally surface."""
    from pipelines.codeguard import answer_regulation_query
    from schemas.codeguard import RegulationCategory

    result = await answer_regulation_query(
        db=session,
        question=(
            "Yêu cầu về sức chịu tải của nền đất đối với móng cọc khoan "
            "nhồi trong khu vực đất yếu là gì?"
        ),
        language="vi",
        # fire_safety only — the geotech question has no fire-safety match.
        categories=[RegulationCategory.fire_safety],
        jurisdiction=None,
        top_k=8,
    )

    # Either the abstain path fired (confidence==0, no citations) OR the
    # LLM admitted insufficient context (low confidence). Both are
    # acceptable; what's NOT acceptable is a confident-sounding answer
    # citing fire-safety sections for a foundations question.
    if result.confidence == 0 and not result.citations:
        # Abstain path — best case, the LLM was never called.
        assert "Không tìm thấy" in result.answer, (
            f"Confidence=0 with empty citations should be the canned "
            f"abstain message; got: {result.answer!r}"
        )
    else:
        # If the abstain path didn't fire (some category-incidental match
        # surfaced), at least confidence should be conservative and we
        # shouldn't see fire-safety section refs cited as if they
        # answered a foundations question.
        assert result.confidence < 0.5, (
            f"Pipeline returned high confidence ({result.confidence:.2f}) "
            f"for an out-of-corpus question — likely hallucination. "
            f"Answer: {result.answer[:200]!r}, citations: "
            f"{[c.section for c in result.citations]}"
        )
