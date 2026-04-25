"""Write normalised scraper output into `material_prices`.

Idempotent: the table has a unique constraint on
`(material_code, province, effective_date)`, so re-running the same
scrape for the same period updates existing rows rather than duplicating.

The writer operates outside any tenant scope (`app.current_org_id` is
not set). `material_prices` is a platform-wide catalogue without
`organization_id` — no RLS applies.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import text

from db.session import SessionFactory

from .base import NormalisedPrice

logger = logging.getLogger(__name__)


_UPSERT_SQL = text(
    """
    INSERT INTO material_prices (
        id, material_code, name, category, unit, price_vnd,
        province, source, effective_date
    ) VALUES (
        :id, :code, :name, :cat, :unit, :price,
        :prov, 'government', :eff
    )
    ON CONFLICT (material_code, province, effective_date) DO UPDATE
    SET price_vnd = EXCLUDED.price_vnd,
        name      = EXCLUDED.name,
        category  = COALESCE(EXCLUDED.category, material_prices.category),
        unit      = EXCLUDED.unit,
        source    = 'government'
    """
)


async def write_prices(rows: list[NormalisedPrice]) -> dict:
    """Upsert `rows` in a single transaction. Returns summary counts."""
    if not rows:
        return {"inserted_or_updated": 0}

    async with SessionFactory() as session:
        for row in rows:
            await session.execute(
                _UPSERT_SQL,
                {
                    "id": str(uuid4()),
                    "code": row.material_code,
                    "name": row.name,
                    "cat": row.category,
                    "unit": row.unit,
                    "price": int(row.price_vnd),
                    "prov": row.province,
                    "eff": row.effective_date,
                },
            )
        await session.commit()

    logger.info("scraper.writer: upserted %d rows", len(rows))
    return {"inserted_or_updated": len(rows)}
