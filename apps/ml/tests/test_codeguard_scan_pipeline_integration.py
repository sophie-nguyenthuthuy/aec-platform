"""End-to-end integration test for `auto_scan_project` against real Postgres.

The Q&A pipeline already has an E2E smoke test
(`test_codeguard_query_pipeline_integration`). `auto_scan_project` is the
other half of the LLM surface in CODEGUARD — invoked by `POST /scan` — and
until now only had router-level mock tests. This fills the gap.

What it proves (that nothing else does):
  * The per-category retrieval loop flows through `_hybrid_search` without
    tripping on the category filter against the halfvec SQL.
  * `_category_probe` produces a query that gets embedded + returned by
    the stubbed embedder without crashing.
  * `Finding` objects are parsed correctly from the canned scan JSON,
    including `status`/`severity` enum coercion and graceful skip on
    malformed entries.
  * The inline `Citation` construction in `auto_scan` uses the DB row
    (regulation_id, code_name, section_ref from the JOIN) rather than
    LLM-supplied strings — same grounding invariant as `_ground_citations`
    guards in the Q&A path.
  * The returned `(findings, reg_ids)` tuple carries the right regulation
    UUID so `POST /scan` can persist `regulations_referenced`.

Usage: same as the sibling integration tests — requires TEST_DATABASE_URL.

    TEST_DATABASE_URL=postgresql+asyncpg://aec:aec@localhost:5437/aec \\
      python -m pytest apps/ml/tests/test_codeguard_scan_pipeline_integration.py -v
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


_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set — skipping live-Postgres scan pipeline test.",
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


async def test_auto_scan_returns_grounded_findings_with_citations(session, monkeypatch):
    """Single-category happy path: seed one fire_safety regulation + chunk,
    stub the LLM to return a canned findings list, assert we get back
    Finding objects with Citations grounded in the DB row."""
    from schemas.codeguard import FindingStatus, ProjectParameters, RegulationCategory, Severity
    import pipelines.codeguard as cg
    from pipelines.codeguard import auto_scan_project

    tag = uuid4().hex[:12]
    reg_code = f"TEST_SCAN_{tag}"
    reg_id = uuid4()

    # Seed regulation with matching category — _hybrid_search filters by
    # `category = ANY(:categories)` via the r.category = ANY pattern, so
    # the category must match or the chunk won't come back.
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
        "Nhà chung cư từ 5 tầng trở lên phải có ít nhất 2 lối thoát nạn "
        "trên mỗi tầng. Chiều rộng hành lang thoát nạn không nhỏ hơn 1.4 m."
    )
    await session.execute(
        text(
            """
            INSERT INTO regulation_chunks
                (id, regulation_id, section_ref, content, embedding)
            VALUES (gen_random_uuid(), :rid, '3.1', :content, CAST(:vec AS vector))
            """
        ),
        {
            "rid": str(reg_id),
            "content": chunk_content,
            "vec": _vec_literal(_axis_vec(0)),
        },
    )
    await session.commit()

    # --- Stubs ---
    class _FakeEmbedder:
        async def aembed_query(self, _q: str) -> list[float]:
            return _axis_vec(0, magnitude=1.0)

    monkeypatch.setattr(cg, "_embedder", lambda: _FakeEmbedder())

    # Canned scan response: one FAIL (project has only 1 exit, code requires 2)
    # and one PASS (corridor width is above the 1.4 m minimum). Both cite
    # chunk_index=0 — the only retrieved chunk.
    canned = json.dumps(
        {
            "findings": [
                {
                    "status": "FAIL",
                    "severity": "critical",
                    "title": "Số lối thoát nạn dưới yêu cầu",
                    "description": (
                        "Dự án 6 tầng chỉ có 1 lối thoát nạn, thấp hơn yêu cầu tối thiểu 2 lối."
                    ),
                    "resolution": "Bổ sung thêm ít nhất 1 lối thoát nạn phù hợp.",
                    "citation_chunk_index": 0,
                },
                {
                    "status": "PASS",
                    "severity": "minor",
                    "title": "Chiều rộng hành lang đạt yêu cầu",
                    "description": "Hành lang 1.6 m > yêu cầu tối thiểu 1.4 m.",
                    "resolution": None,
                    "citation_chunk_index": 0,
                },
                # Malformed entry — invalid status enum. The pipeline should
                # skip it without aborting the whole scan.
                {
                    "status": "MAYBE",
                    "severity": "minor",
                    "title": "Ignored",
                    "description": "Bad status — should be dropped.",
                    "citation_chunk_index": 0,
                },
            ]
        },
        ensure_ascii=False,
    )
    # One category → one LLM call → one response in the list.
    fake_model = FakeListChatModel(responses=[canned])
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.0: fake_model)

    parameters = ProjectParameters(
        project_type="residential",
        use_class="apartment",
        floors_above=6,
        max_height_m=21.0,
        occupancy=120,
        location={"province": "national"},  # match seeded jurisdiction
    )

    try:
        findings, reg_ids = await auto_scan_project(
            db=session,
            parameters=parameters,
            categories=[RegulationCategory.fire_safety],
        )

        # Two valid findings, one dropped (malformed status).
        assert len(findings) == 2, f"expected 2 valid findings, got {findings}"

        fail = next(f for f in findings if f.status == FindingStatus.fail)
        assert fail.severity == Severity.critical
        assert fail.category == RegulationCategory.fire_safety
        assert fail.title.startswith("Số lối thoát nạn")
        assert fail.resolution is not None

        # Citation grounded in the DB row — not LLM-supplied strings.
        assert fail.citation is not None
        assert fail.citation.regulation_id == reg_id
        assert fail.citation.regulation == reg_code  # code_name from JOIN
        assert fail.citation.section == "3.1"          # section_ref from DB
        # Excerpt is chunk content prefix (auto_scan doesn't trust LLM
        # excerpts; it uses `src.get("content")[:300]` directly).
        assert fail.citation.excerpt.startswith("Nhà chung cư"), fail.citation.excerpt

        # regulations_referenced surfaces the seeded UUID so `POST /scan`
        # can persist it on the ComplianceCheck row.
        assert reg_id in reg_ids

    finally:
        await session.execute(
            text("DELETE FROM regulations WHERE id = :id"),
            {"id": str(reg_id)},
        )
        await session.commit()


async def test_auto_scan_skips_categories_with_no_retrieval(session, monkeypatch):
    """If a category has no matching chunks (e.g. we seeded fire_safety but
    the scan also probes accessibility), the scan should silently skip that
    category rather than sending the LLM an empty context or aborting."""
    from schemas.codeguard import ProjectParameters, RegulationCategory
    import pipelines.codeguard as cg
    from pipelines.codeguard import auto_scan_project

    tag = uuid4().hex[:12]
    reg_code = f"TEST_SCAN_SKIP_{tag}"
    reg_id = uuid4()

    # Seed ONLY fire_safety — accessibility has nothing.
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
    await session.execute(
        text(
            """
            INSERT INTO regulation_chunks
                (id, regulation_id, section_ref, content, embedding)
            VALUES (gen_random_uuid(), :rid, '1.1', 'irrelevant text', CAST(:vec AS vector))
            """
        ),
        {"rid": str(reg_id), "vec": _vec_literal(_axis_vec(0))},
    )
    await session.commit()

    class _FakeEmbedder:
        async def aembed_query(self, _q: str) -> list[float]:
            return _axis_vec(0, magnitude=1.0)

    monkeypatch.setattr(cg, "_embedder", lambda: _FakeEmbedder())

    # fire_safety will retrieve → LLM called once with empty findings list.
    # accessibility retrieves nothing → LLM should NOT be called for it.
    # We load ONE response into the fake model; if the pipeline called _llm
    # twice the second call would hang waiting for a second response.
    canned_empty = json.dumps({"findings": []})
    fake_model = FakeListChatModel(responses=[canned_empty])
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.0: fake_model)

    try:
        findings, reg_ids = await auto_scan_project(
            db=session,
            parameters=ProjectParameters(project_type="residential", location={"province": "national"}),
            categories=[RegulationCategory.fire_safety, RegulationCategory.accessibility],
        )
        # fire_safety returned empty findings list; accessibility was skipped.
        assert findings == []
        # fire_safety chunk still contributed to reg_ids (it was retrieved,
        # just no findings emitted).
        assert reg_id in reg_ids
    finally:
        await session.execute(
            text("DELETE FROM regulations WHERE id = :id"),
            {"id": str(reg_id)},
        )
        await session.commit()
