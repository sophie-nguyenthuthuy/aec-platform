"""End-to-end integration test for the codeguard dense-retrieval path.

`FakeAsyncSession` can't exercise pgvector SQL, so we only know the halfvec
column + HNSW index in migration 0009 actually work by running against a
real Postgres with pgvector >= 0.7.0. This test is therefore gated on
TEST_DATABASE_URL — skipped by default in local/CI runs without it.

Usage:
    # One-time: apply migrations to the test DB
    DATABASE_URL=postgresql+asyncpg://aec:aec@localhost:5432/aec_test \\
      alembic -c apps/api/alembic.ini upgrade head

    # Then run the test:
    TEST_DATABASE_URL=postgresql+asyncpg://aec:aec@localhost:5432/aec_test \\
      python -m pytest apps/ml/tests/test_codeguard_retrieval_integration.py -v

What it proves:
  * `regulation_chunks.embedding_half` exists and is populated automatically
    from `embedding` (the GENERATED ALWAYS AS column from 0009).
  * `halfvec_cosine_ops` + `<=>` operator resolve (halfvec type installed).
  * `_dense_search` returns chunks ordered by cosine similarity to the query.

A failure here — especially a `column "embedding_half" does not exist` or
`operator does not exist: halfvec <=> halfvec` — means the 0009 migration
didn't apply or pgvector is too old (needs 0.7.0+).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# Make both `pipelines.codeguard` (apps/ml) and `schemas.codeguard` (apps/api)
# importable when pytest is invoked from the repo root without the full
# docker-compose PYTHONPATH set. `pipelines.codeguard` imports from schemas.
_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — skipping live-Postgres integration test. "
        "Set it to a DB with codeguard migrations applied (see module docstring)."
    ),
)

EMBED_DIM = 3072


def _axis_vec(i: int, magnitude: float = 1.0) -> list[float]:
    """Return a 3072-dim vector with `magnitude` at index i, zeros elsewhere."""
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


async def test_dense_search_orders_chunks_by_cosine_similarity(session, monkeypatch):
    """Seed 3 chunks with orthogonal axis-aligned embeddings, issue a query
    tilted toward axis 0, and assert the retrieval returns axis-0 first.

    This is the simplest non-trivial assertion that:
      1. the halfvec column is generated correctly from the written vector,
      2. the `<=>` cosine operator works on halfvec,
      3. the `_dense_search` SQL and ORDER BY clause are syntactically valid.
    """
    import pipelines.codeguard as cg
    from pipelines.codeguard import _dense_search

    # Unique per-run code_name so parallel runs don't step on each other.
    tag = uuid4().hex[:12]
    reg_code = f"TEST_HNSW_{tag}"
    reg_id = uuid4()

    await session.execute(
        text(
            """
            INSERT INTO regulations (id, country_code, jurisdiction, code_name, language)
            VALUES (:id, 'VN', 'national', :code, 'vi')
            """
        ),
        {"id": str(reg_id), "code": reg_code},
    )

    chunk_specs = [
        ("axis-0", _axis_vec(0)),  # expected nearest to the mocked query
        ("axis-1", _axis_vec(1)),
        ("axis-2", _axis_vec(2)),
    ]
    for section_ref, vec in chunk_specs:
        await session.execute(
            text(
                """
                INSERT INTO regulation_chunks
                    (id, regulation_id, section_ref, content, embedding)
                VALUES
                    (gen_random_uuid(), :reg_id, :ref, :content, CAST(:vec AS vector))
                """
            ),
            {
                "reg_id": str(reg_id),
                "ref": section_ref,
                "content": f"content-for-{section_ref}",
                "vec": _vec_literal(vec),
            },
        )
    await session.commit()

    # Mock the OpenAI embedder — no API calls during integration tests. Query
    # vector is strongly axis-0 with a small axis-1 component, so cosine
    # ordering must be: axis-0 > axis-1 > axis-2 (axis-2 fully orthogonal).
    class _FakeEmbedder:
        async def aembed_query(self, _q: str) -> list[float]:
            v = _axis_vec(0, magnitude=0.9)
            v[1] = 0.1
            return v

    monkeypatch.setattr(cg, "_embedder", lambda: _FakeEmbedder())

    try:
        results = await _dense_search(
            session,
            query_text="irrelevant — embedder is mocked",
            categories=None,
            jurisdiction=None,
            top_k=20,  # generous so other regulations in the DB don't crowd ours out
        )

        # Filter to our seeded regulation — a real dev DB may have other regs
        # (seeded via `make seed-codeguard`) competing for the top slots.
        ours = [r for r in results if r["code_name"] == reg_code]
        assert len(ours) == 3, (
            f"expected all 3 seeded chunks back, got {len(ours)}; "
            f"seen: {[r['section_ref'] for r in ours]}"
        )

        # Nearest first, then monotonically decreasing scores.
        refs_in_order = [r["section_ref"] for r in ours]
        assert refs_in_order == ["axis-0", "axis-1", "axis-2"], (
            f"expected cosine ordering axis-0 > axis-1 > axis-2, got {refs_in_order}"
        )
        assert ours[0]["score"] > ours[1]["score"] > ours[2]["score"], (
            f"scores not monotonically decreasing: {[r['score'] for r in ours]}"
        )
        # Sanity: nearest chunk score should be near 1.0 (cosine of parallel vecs).
        assert ours[0]["score"] > 0.9, f"axis-0 score too low: {ours[0]['score']}"

    finally:
        # Teardown — DELETE cascades into regulation_chunks via ON DELETE CASCADE.
        await session.execute(
            text("DELETE FROM regulations WHERE id = :id"),
            {"id": str(reg_id)},
        )
        await session.commit()
