"""Tests for the effective-date filter in `_dense_search`.

Two layers of coverage:

  * Tier 1 (always runs) — assert the SQL produced by `_dense_search`
    contains the effective_date / expiry_date WHERE clause and binds
    `as_of` to the date the caller passed (or today, when omitted).
    Stubs the embedder + `db.execute` so no DB or OpenAI is needed.

  * Tier 3 (gated on `TEST_DATABASE_URL`) — seeds two regulations, one
    with `effective_date='2024-01-01'` and one with `effective_date=
    '2022-01-01'`, then queries with `as_of_date=2023-06-01` and
    asserts only the 2022 regulation's chunk is returned. This is the
    correctness contract the round was built around: a 2022-era
    project's audit must not hit a 2024 revision.

Why these matter: the SQL change is invisible to every other test
in the suite — none of them exercise the filter clause directly, and
the existing integration test seeds regs with no effective_date at all
(NULL effective_date is treated as "always in effect"). Without these
two tests the regression surface for `as_of_date` is the eval harness,
which is gated on real LLM keys and doesn't run on PRs.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


EMBED_DIM = 3072


def _axis_vec(i: int, magnitude: float = 1.0) -> list[float]:
    """3072-dim vector with `magnitude` at position i, zero elsewhere."""
    v = [0.0] * EMBED_DIM
    v[i] = magnitude
    return v


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


# ---------- Tier 1: SQL clause shape -------------------------------------


class _FakeEmbedder:
    async def aembed_query(self, _q: str) -> list[float]:
        return _axis_vec(0)


def _capture_sql_db():
    """Build a `db` stub that records `(sql_text, params)` from each
    `db.execute(...)` call. `_dense_search` issues exactly one SELECT,
    so `captured.calls[0]` is the one we assert against.
    """
    captured = MagicMock()
    captured.calls = []

    async def _execute(stmt, params=None):
        # `stmt` is a SQLAlchemy `TextClause`; `.text` is the raw SQL
        # the function built. Stash both for the assertion below.
        captured.calls.append((str(stmt), params or {}))
        result = MagicMock()
        result.mappings.return_value.all.return_value = []
        return result

    captured.execute = AsyncMock(side_effect=_execute)
    return captured


async def test_dense_search_includes_effective_date_filter(monkeypatch):
    """The WHERE clause must restrict to regulations in effect on the
    bound `as_of` date — `effective_date IS NULL OR effective_date <=
    :as_of` AND `expiry_date IS NULL OR expiry_date > :as_of`. Both
    halves are load-bearing: the NULL branches keep legacy rows
    (without dates) visible, the comparison branches enforce the
    actual filter.
    """
    import pipelines.codeguard as cg

    monkeypatch.setattr(cg, "_embedder", lambda: _FakeEmbedder())
    db = _capture_sql_db()

    await cg._dense_search(
        db=db,
        query_text="irrelevant — embedder mocked",
        categories=None,
        jurisdiction=None,
        top_k=8,
        as_of_date=date(2023, 6, 1),
    )

    assert len(db.calls) == 1, "expected exactly one SQL execute call"
    sql, params = db.calls[0]

    # The full date filter must appear in the SQL — both effective
    # and expiry halves, both NULL-tolerant, both pinned to `:as_of`.
    assert "effective_date" in sql
    assert "expiry_date" in sql
    assert ":as_of" in sql
    # The bound parameter is the date we passed in.
    assert params["as_of"] == date(2023, 6, 1)


async def test_dense_search_defaults_as_of_to_today_when_unset(monkeypatch):
    """Calling without `as_of_date` (the default for the public route
    when the client doesn't send one) defaults to today. Pin the
    contract — a regression that defaulted to `None` and removed the
    filter clause would silently re-introduce the correctness gap
    this work was meant to close.
    """
    import pipelines.codeguard as cg

    monkeypatch.setattr(cg, "_embedder", lambda: _FakeEmbedder())
    db = _capture_sql_db()

    await cg._dense_search(
        db=db,
        query_text="any query",
        categories=None,
        jurisdiction=None,
        top_k=8,
    )

    sql, params = db.calls[0]
    assert "effective_date" in sql
    assert ":as_of" in sql
    # Default is today's date (the function calls `date.today()` when
    # `as_of_date` is None). We don't assert the exact date because
    # midnight crossings would flake the test; assert it's a `date`
    # instance and is today or yesterday at the latest.
    bound = params["as_of"]
    assert isinstance(bound, date)
    today = date.today()
    assert bound == today or (today - bound).days <= 1


async def test_dense_search_passes_as_of_date_through_hybrid_search(monkeypatch):
    """`_hybrid_search` must forward `as_of_date` to its `_dense_search`
    arm — a regression that drops the kwarg there silently undoes the
    filter at the route layer (where `_hybrid_search` is the actual
    entrypoint, not `_dense_search` directly).
    """
    import pipelines.codeguard as cg

    captured: dict = {}

    async def _stub_dense(*args, **kwargs):
        captured["as_of_date"] = kwargs.get("as_of_date")
        return []

    async def _stub_sparse(*_args, **_kwargs):
        return []

    monkeypatch.setattr(cg, "_dense_search", _stub_dense)
    monkeypatch.setattr(cg, "_sparse_search", _stub_sparse)

    target = date(2022, 7, 15)
    await cg._hybrid_search(
        db=None,
        query_text="q",
        categories=None,
        jurisdiction=None,
        top_k=5,
        as_of_date=target,
    )

    assert captured["as_of_date"] == target


# ---------- Tier 3: real-DB filter behaviour -----------------------------


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — skipping live-Postgres effective-date test. "
        "Set it to a DB with codeguard migrations applied."
    ),
)
async def test_dense_search_excludes_future_effective_date(session, monkeypatch):
    """Seed two regulations: an "old" one effective 2022-01-01 and a
    "new" one effective 2024-01-01. Query with `as_of_date=2023-06-01`
    and assert only the 2022 reg's chunk surfaces.

    This is the contract a real compliance audit depends on: a project
    filed in 2023 must not be evaluated against rules that didn't yet
    apply. Without the filter, both regs would come back ordered by
    cosine similarity and the LLM would happily cite the 2024 revision
    as authoritative — a real correctness bug for compliance work.
    """
    import pipelines.codeguard as cg
    from pipelines.codeguard import _dense_search

    tag = uuid4().hex[:12]
    old_id, new_id = uuid4(), uuid4()
    old_code = f"TEST_OLD_{tag}"
    new_code = f"TEST_NEW_{tag}"

    # The two regs share an axis-0 embedding so cosine similarity to
    # the mocked query vector is identical — the filter is the ONLY
    # reason one is included and the other excluded. If the filter
    # silently broke, both would come back and the assertion below
    # would fail with the "unexpected new code in results" message.
    await session.execute(
        text(
            """
            INSERT INTO regulations
                (id, country_code, jurisdiction, code_name, language, effective_date)
            VALUES
                (:old_id, 'VN', 'national', :old_code, 'vi', '2022-01-01'),
                (:new_id, 'VN', 'national', :new_code, 'vi', '2024-01-01')
            """
        ),
        {
            "old_id": str(old_id),
            "new_id": str(new_id),
            "old_code": old_code,
            "new_code": new_code,
        },
    )
    for reg_id, ref in [(old_id, "old-1.1"), (new_id, "new-1.1")]:
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
                "ref": ref,
                "content": f"content for {ref}",
                "vec": _vec_literal(_axis_vec(0)),
            },
        )
    await session.commit()

    monkeypatch.setattr(cg, "_embedder", lambda: _FakeEmbedder())

    try:
        # Query as of 2023-06-01 — old reg in effect, new reg not yet.
        results = await _dense_search(
            session,
            query_text="irrelevant",
            categories=None,
            jurisdiction=None,
            top_k=50,  # generous so other regs in dev DB don't crowd these out
            as_of_date=date(2023, 6, 1),
        )
        codes = {r["code_name"] for r in results}
        assert old_code in codes, (
            "old regulation (effective 2022-01-01) missing from results "
            "queried as_of 2023-06-01 — filter is rejecting valid rows"
        )
        assert new_code not in codes, (
            f"new regulation (effective 2024-01-01) leaked into results "
            f"queried as_of 2023-06-01 — filter is missing or broken; "
            f"got codes: {sorted(codes)}"
        )

        # Sanity check: querying without `as_of_date` (defaults to today,
        # which is past 2024-01-01) MUST surface the new reg. This proves
        # the filter is working in both directions, not just unconditionally
        # excluding the new one.
        results_today = await _dense_search(
            session,
            query_text="irrelevant",
            categories=None,
            jurisdiction=None,
            top_k=50,
        )
        codes_today = {r["code_name"] for r in results_today}
        assert new_code in codes_today, (
            f"new regulation absent from default-as_of query — filter "
            f"is too aggressive; got codes: {sorted(codes_today)}"
        )

    finally:
        # ON DELETE CASCADE on regulation_chunks → tearing down the
        # regulations rows clears the chunks too.
        await session.execute(
            text("DELETE FROM regulations WHERE id IN (:old_id, :new_id)"),
            {"old_id": str(old_id), "new_id": str(new_id)},
        )
        await session.commit()
