"""Integration test for `estimate_from_brief` with OpenAI mocked.

Runs the real LangGraph + SQLAlchemy pipeline against a live Postgres
(same env var as the RLS tests, `COSTPULSE_RLS_DB_URL`), but stubs the
OpenAI network call. Proves end-to-end that:

  * the brief_generator's prompt path is traversed,
  * JSON from the LLM is parsed into `elements`,
  * `price_lookup_node` resolves material_prices from the DB,
  * `_assemble_and_persist` writes an Estimate + hierarchical BoqItems,
  * the returned `AiEstimateResult` shape + totals + contingency match.

Only the LLM is mocked — DB writes, reads, waste factors, and section
grouping all run real code. Skipped when the DB URL isn't set.

    export COSTPULSE_RLS_DB_URL=postgresql+asyncpg://aec:aec@localhost:55432/aec
    pytest apps/api/tests/test_costpulse_pipeline_openai.py -v
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Importing models.core + models.costpulse registers Organization/User/Project/File
# tables in the shared SQLAlchemy metadata so the FK from `estimates.organization_id`
# to `organizations.id` can be resolved at flush time. Without this, you get
# `NoReferencedTableError: could not find table 'organizations'`.
import models.core  # noqa: F401
import models.costpulse  # noqa: F401

_DB_URL = os.environ.get("COSTPULSE_RLS_DB_URL")

pytestmark = [
    pytest.mark.asyncio,
    # Gated by `--integration` (see apps/api/tests/conftest.py).
    pytest.mark.integration,
    pytest.mark.skipif(
        _DB_URL is None,
        reason="COSTPULSE_RLS_DB_URL not set — integration test requires a live DB",
    ),
]


# ---------- Fake LLM ----------


class _FakeAIMessage:
    """Minimal stand-in for langchain AIMessage — the pipeline only reads `.content`."""

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Captures calls + returns a preset JSON payload."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[list] = []

    async def ainvoke(self, messages, *_a, **_k):
        self.calls.append(messages)
        return _FakeAIMessage(json.dumps(self._payload))


# ---------- Fixtures ----------


@pytest.fixture
async def engine():
    assert _DB_URL is not None
    eng = create_async_engine(_DB_URL, future=True)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s


@pytest.fixture
async def org_and_user(session: AsyncSession):
    """Provision an org + user so the Estimate FK constraints hold."""
    org_id = uuid4()
    user_id = uuid4()
    await session.execute(
        text("INSERT INTO organizations (id, name, slug) VALUES (:id, :n, :s)"),
        {"id": str(org_id), "n": "Integration Org", "s": f"int-{org_id}"},
    )
    await session.execute(
        text("INSERT INTO users (id, email) VALUES (:id, :e)"),
        {"id": str(user_id), "e": f"int-{user_id}@test.local"},
    )
    await session.commit()

    yield org_id, user_id

    # Clean up in FK order. The pipeline creates estimates + boq_items under this org.
    await session.execute(
        text("DELETE FROM boq_items WHERE estimate_id IN (SELECT id FROM estimates WHERE organization_id = :o)"),
        {"o": str(org_id)},
    )
    await session.execute(text("DELETE FROM estimates WHERE organization_id = :o"), {"o": str(org_id)})
    await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": str(user_id)})
    await session.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": str(org_id)})
    await session.commit()


@pytest.fixture
async def seeded_prices(session: AsyncSession):
    """Two material prices so `price_lookup_node` can resolve the LLM-generated codes.

    We use distinct codes (`INT_CONC_C30`, `INT_REBAR_CB500`) to avoid colliding
    with the real seed data, then have the mocked LLM emit those same codes.
    """
    import datetime as _dt

    # Use upserts so a previously-crashed test run doesn't poison subsequent runs.
    today = _dt.date.today()
    upsert = text(
        "INSERT INTO material_prices "
        "(id, material_code, name, category, unit, price_vnd, province, source, effective_date) "
        "VALUES (:i, :c, :n, :cat, :u, :p, :pr, :s, :d) "
        "ON CONFLICT (material_code, province, effective_date) DO UPDATE "
        "SET price_vnd = EXCLUDED.price_vnd RETURNING id"
    )
    p1 = (
        await session.execute(
            upsert,
            {
                "i": str(uuid4()),
                "c": "INT_CONC_C30",
                "n": "Concrete C30 (integration)",
                "cat": "concrete",
                "u": "m3",
                "p": 2_000_000,
                "pr": "Hanoi",
                "s": "government",
                "d": today,
            },
        )
    ).scalar_one()
    p2 = (
        await session.execute(
            upsert,
            {
                "i": str(uuid4()),
                "c": "INT_REBAR_CB500",
                "n": "Rebar CB500 (integration)",
                "cat": "steel",
                "u": "kg",
                "p": 20_000,
                "pr": "Hanoi",
                "s": "government",
                "d": today,
            },
        )
    ).scalar_one()
    await session.commit()

    yield {"concrete": p1, "rebar": p2}

    await session.execute(
        text("DELETE FROM material_prices WHERE material_code LIKE 'INT_%'"),
    )
    await session.commit()


# ---------- Tests ----------


async def test_estimate_from_brief_end_to_end_with_mocked_llm(monkeypatch, session, org_and_user, seeded_prices):
    """Full graph: LLM (mocked) → price lookup (real) → persist (real)."""
    from apps.ml.pipelines import costpulse as pipeline

    from schemas.costpulse import (
        EstimateConfidence,
        EstimateFromBriefRequest,
        EstimateMethod,
    )

    org_id, user_id = org_and_user

    fake_llm = _FakeLLM(
        {
            "elements": [
                {
                    "section_code": "04",
                    "description": "Concrete C30 slab",
                    "material_code": "INT_CONC_C30",
                    "category": "concrete",
                    "quantity": 100.0,
                    "unit": "m3",
                },
                {
                    "section_code": "04",
                    "description": "Rebar CB500 for slab",
                    "material_code": "INT_REBAR_CB500",
                    "category": "steel",
                    "quantity": 5000.0,
                    "unit": "kg",
                },
            ]
        }
    )
    monkeypatch.setattr(pipeline, "_text_llm", lambda: fake_llm)

    payload = EstimateFromBriefRequest(
        name="Integration Test Estimate",
        project_type="residential",
        area_sqm=200.0,
        floors=3,
        province="Hanoi",
        quality_tier="standard",
        structure_type="reinforced_concrete",
        notes="Integration test — do not use in prod",
    )

    result = await pipeline.estimate_from_brief(
        db=session,
        organization_id=org_id,
        created_by=user_id,
        payload=payload,
    )

    # ---- LLM interaction ----
    assert len(fake_llm.calls) == 1, "expected a single LLM roundtrip"
    prompt_msgs = fake_llm.calls[0]
    assert any("residential" in str(m.content) for m in prompt_msgs), "project_type should appear in the user prompt"
    assert any("200" in str(m.content) for m in prompt_msgs), "area_sqm should appear in the user prompt"

    # ---- Result shape ----
    assert result.estimate_id is not None
    assert result.confidence == EstimateConfidence.rough_order
    assert result.total_vnd > 0, "non-zero total expected from priced elements"
    assert result.missing_price_codes == [], "both codes were seeded"
    assert not result.warnings, f"unexpected warnings: {result.warnings}"

    # ---- Expected totals (waste + contingency) ----
    # concrete: 100 m3 * 1.03 waste * 2_000_000 = 206_000_000
    # steel:    5000 kg * 1.05 waste * 20_000   = 105_000_000
    # subtotal = 311_000_000, contingency 10% = 31_100_000, grand = 342_100_000
    expected_total = Decimal("342100000")
    assert result.total_vnd == int(expected_total), f"expected {expected_total}, got {result.total_vnd}"

    # ---- DB state: Estimate row ----
    row = (
        (
            await session.execute(
                text(
                    "SELECT name, method, confidence, total_vnd, organization_id, created_by "
                    "FROM estimates WHERE id = :id"
                ),
                {"id": str(result.estimate_id)},
            )
        )
        .mappings()
        .first()
    )
    assert row is not None, "estimate row must be persisted"
    assert row["name"] == "Integration Test Estimate"
    assert row["method"] == EstimateMethod.ai_generated.value
    assert row["confidence"] == EstimateConfidence.rough_order.value
    assert row["total_vnd"] == int(expected_total)
    assert str(row["organization_id"]) == str(org_id)
    assert str(row["created_by"]) == str(user_id)

    # ---- DB state: BoqItem rows ----
    boq_rows = (
        (
            await session.execute(
                text(
                    "SELECT code, description, material_code, quantity, unit_price_vnd, total_price_vnd "
                    "FROM boq_items WHERE estimate_id = :id ORDER BY sort_order"
                ),
                {"id": str(result.estimate_id)},
            )
        )
        .mappings()
        .all()
    )

    # 8 section parents (BOQ_SECTIONS) + 2 children under section 04 + 1 contingency row = 11
    assert len(boq_rows) == 11, f"expected 11 rows, got {len(boq_rows)}"

    # The two priced rows must be under section 04
    concrete_row = next(r for r in boq_rows if r["material_code"] == "INT_CONC_C30")
    rebar_row = next(r for r in boq_rows if r["material_code"] == "INT_REBAR_CB500")
    assert concrete_row["code"].startswith("04.")
    assert rebar_row["code"].startswith("04.")
    # 103 m3 after 1.03 waste * 2_000_000 unit price = 206_000_000
    assert Decimal(concrete_row["total_price_vnd"]) == Decimal("206000000")
    # 5250 kg after 1.05 waste * 20_000 unit price = 105_000_000
    assert Decimal(rebar_row["total_price_vnd"]) == Decimal("105000000")

    # Contingency row is a flat 'lot'
    contingency_row = next(r for r in boq_rows if r["code"] == "09")
    assert Decimal(contingency_row["total_price_vnd"]) == Decimal("31100000")


async def test_estimate_from_brief_handles_bad_llm_output(monkeypatch, session, org_and_user):
    """LLM returning garbage → pipeline still produces a (zero-total) estimate."""
    from apps.ml.pipelines import costpulse as pipeline

    from schemas.costpulse import EstimateFromBriefRequest

    org_id, user_id = org_and_user

    class _BadLLM:
        async def ainvoke(self, _msgs, *_a, **_k):
            return _FakeAIMessage("not json at all — model hallucinated")

    monkeypatch.setattr(pipeline, "_text_llm", lambda: _BadLLM())

    result = await pipeline.estimate_from_brief(
        db=session,
        organization_id=org_id,
        created_by=user_id,
        payload=EstimateFromBriefRequest(
            name="Bad LLM Estimate",
            project_type="residential",
            area_sqm=100.0,
            floors=2,
            province="Hanoi",
        ),
    )

    # No elements ⇒ no priced rows ⇒ zero total (just the section scaffold + 0% contingency)
    assert result.total_vnd == 0
    # Only the 8 section headers + the contingency row should be present
    boq_count = (
        await session.execute(
            text("SELECT COUNT(*) FROM boq_items WHERE estimate_id = :id"),
            {"id": str(result.estimate_id)},
        )
    ).scalar_one()
    assert boq_count == 9


async def test_estimate_from_brief_flags_missing_prices(monkeypatch, session, org_and_user):
    """When the LLM emits a code we don't have priced, `missing_price_codes` reflects it."""
    from apps.ml.pipelines import costpulse as pipeline

    from schemas.costpulse import EstimateFromBriefRequest

    org_id, user_id = org_and_user

    fake_llm = _FakeLLM(
        {
            "elements": [
                {
                    "section_code": "06",
                    "description": "Exotic unobtanium finish",
                    "material_code": "INT_UNOBTAINIUM",
                    "category": "finishing",
                    "quantity": 42.0,
                    "unit": "m2",
                },
            ]
        }
    )
    monkeypatch.setattr(pipeline, "_text_llm", lambda: fake_llm)

    result = await pipeline.estimate_from_brief(
        db=session,
        organization_id=org_id,
        created_by=user_id,
        payload=EstimateFromBriefRequest(
            name="Missing-Price Estimate",
            project_type="residential",
            area_sqm=80.0,
            floors=1,
            province="Hanoi",
        ),
    )

    assert "INT_UNOBTAINIUM" in result.missing_price_codes
    assert result.total_vnd == 0
    assert any("missing price" in w.lower() for w in result.warnings)
