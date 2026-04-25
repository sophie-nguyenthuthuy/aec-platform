"""Integration test for `services.price_scrapers.writer.write_prices`.

Exercises the real upsert SQL against a live Postgres. Skipped unless
`COSTPULSE_RLS_DB_URL` is set (same pattern as the RLS + OpenAI tests).
Writer uses the module-level `SessionFactory`, so we need `DATABASE_URL`
pointed at the same dev DB when running this file:

    DATABASE_URL="postgresql+asyncpg://aec:aec@localhost:55432/aec" \\
    COSTPULSE_RLS_DB_URL="postgresql+asyncpg://aec:aec@localhost:55432/aec" \\
    pytest apps/api/tests/test_price_scrapers_writer.py

We verify two things:

  1. First write creates new `material_prices` rows with `source='government'`.
  2. Re-running with a changed price on the same (code, province, date)
     updates in place rather than inserting a duplicate — which matters
     because provinces republish bulletins with corrections.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from db.session import SessionFactory, engine
from services.price_scrapers.base import NormalisedPrice
from services.price_scrapers.writer import write_prices

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


async def _wipe() -> None:
    """Delete any leftover writer-test rows so runs are independent."""
    async with SessionFactory() as s:
        await s.execute(
            text("DELETE FROM material_prices WHERE material_code LIKE 'SCRAPER_WRITER_%'")
        )
        await s.commit()


@pytest.fixture(autouse=True)
async def clean_writer_rows():
    """Autouse: wipe before + after every writer integration test.

    We also dispose the module-level engine after each test. `SessionFactory`
    holds its pool at import time, bound to whatever event loop imported it;
    pytest-asyncio rolls a new loop per test in auto mode, so without an
    explicit dispose the pool's asyncpg connections outlive their loop and
    next-test teardown throws `RuntimeError: Event loop is closed`.
    """
    await _wipe()
    try:
        yield
    finally:
        await _wipe()
        await engine.dispose()


async def test_write_prices_inserts_new_rows():
    rows = [
        NormalisedPrice(
            material_code="SCRAPER_WRITER_CONC",
            name="Concrete (writer test)",
            category="concrete",
            unit="m3",
            price_vnd=Decimal("2000000"),
            province="Hanoi",
            effective_date=date(2026, 3, 1),
            source_url="https://example/x",
        ),
        NormalisedPrice(
            material_code="SCRAPER_WRITER_STEEL",
            name="Steel (writer test)",
            category="steel",
            unit="kg",
            price_vnd=Decimal("20000"),
            province="Hanoi",
            effective_date=date(2026, 3, 1),
        ),
    ]

    summary = await write_prices(rows)
    assert summary == {"inserted_or_updated": 2}

    async with SessionFactory() as s:
        out = (await s.execute(
            text("SELECT material_code, price_vnd, source FROM material_prices "
                 "WHERE material_code LIKE 'SCRAPER_WRITER_%' ORDER BY material_code")
        )).mappings().all()

    assert len(out) == 2
    assert out[0]["material_code"] == "SCRAPER_WRITER_CONC"
    assert out[0]["price_vnd"] == 2_000_000
    assert out[0]["source"] == "government"
    assert out[1]["material_code"] == "SCRAPER_WRITER_STEEL"


async def test_write_prices_updates_on_conflict():
    """A republished bulletin with a corrected price should overwrite, not duplicate."""
    key = dict(
        material_code="SCRAPER_WRITER_UPDATE",
        category="concrete",
        unit="m3",
        province="Hanoi",
        effective_date=date(2026, 3, 1),
    )
    await write_prices([
        NormalisedPrice(name="Before", price_vnd=Decimal("2000000"), source_url=None, **key)
    ])
    await write_prices([
        NormalisedPrice(name="After", price_vnd=Decimal("2100000"), source_url=None, **key)
    ])

    async with SessionFactory() as s:
        out = (await s.execute(
            text("SELECT name, price_vnd FROM material_prices "
                 "WHERE material_code = 'SCRAPER_WRITER_UPDATE'")
        )).mappings().all()

    assert len(out) == 1, "conflict must UPDATE, not INSERT a duplicate"
    assert out[0]["name"] == "After"
    assert out[0]["price_vnd"] == 2_100_000


async def test_write_prices_empty_is_noop():
    summary = await write_prices([])
    assert summary == {"inserted_or_updated": 0}
