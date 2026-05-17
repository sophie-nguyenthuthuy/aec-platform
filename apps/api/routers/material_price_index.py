"""MaterialPriceIndex — customer-facing surface over the existing
`material_prices` table.

Data source: monthly bulletins from Sở Xây dựng (province construction
departments) — scraped by the workers in
`apps/api/services/price_scrapers/`. The data is already ingested;
this router exposes it to PMs / estimators in the dashboard.

Endpoints (member-readable):
  * GET  /api/v1/material-prices/latest — latest price per (material,
    province, unit) for the bar-chart "current price" view.
  * GET  /api/v1/material-prices/materials — distinct material list
    with counts, used to populate the filter dropdown.
  * GET  /api/v1/material-prices/series — time series for one
    material across selected provinces (chart).
  * GET  /api/v1/material-prices/compare — pivoted "province × material"
    table for procurement decisions.

NOT a tenant-scoped data set — material prices are public knowledge.
Org scope only matters for caller auth (so anonymous traffic can't
hammer the endpoint without rate limit).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from core.envelope import ok
from db.session import AdminSessionFactory
from middleware.auth import AuthContext, require_auth

router = APIRouter(prefix="/api/v1/material-prices", tags=["material-prices"])


# Material codes the scrapers emit. Slugs follow VN industry convention
# (cement = xi măng, steel = thép, sand = cát, gravel = đá dăm, brick =
# gạch). The full catalogue is dynamic (scrapers add new codes as they
# discover them); this list is just the "popular" set for the empty-
# state dropdown.
POPULAR_MATERIALS = [
    "cement",
    "rebar",
    "concrete",
    "sand",
    "gravel",
    "brick",
    "tile",
    "steel_plate",
]


@router.get("/materials")
async def list_materials(
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Distinct material list across the scraped data — used to
    populate the filter dropdown. Returns count + last-observed date
    per code so a stale or no-longer-tracked material is visible.
    """
    async with AdminSessionFactory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        material_code,
                        name,
                        category,
                        unit,
                        COUNT(*)::int AS observation_count,
                        MAX(effective_date) AS last_observed,
                        COUNT(DISTINCT province) AS province_count
                    FROM material_prices
                    GROUP BY material_code, name, category, unit
                    ORDER BY MAX(effective_date) DESC NULLS LAST,
                             material_code ASC
                    """
                )
            )
        ).mappings().all()

    return ok(
        {
            "materials": [
                {
                    "material_code": r["material_code"],
                    "name": r["name"],
                    "category": r["category"],
                    "unit": r["unit"],
                    "observation_count": r["observation_count"],
                    "last_observed": r["last_observed"].isoformat() if r["last_observed"] else None,
                    "province_count": int(r["province_count"] or 0),
                }
                for r in rows
            ]
        }
    )


@router.get("/latest")
async def latest_prices(
    auth: Annotated[AuthContext, Depends(require_auth)],
    province: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """Most recent price per (material, province) — the bar-chart
    "current price" view.

    Uses DISTINCT ON (material, province) ORDER BY effective_date DESC
    to keep this a single round-trip vs a JOIN-on-aggregate query.
    """
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if province:
        where.append("province = :province")
        params["province"] = province
    if category:
        where.append("category = :category")
        params["category"] = category

    async with AdminSessionFactory() as session:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT DISTINCT ON (material_code, province)
                        material_code, name, category, unit,
                        price_vnd, price_usd,
                        province, source, effective_date
                    FROM material_prices
                    WHERE {' AND '.join(where)}
                    ORDER BY material_code, province, effective_date DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
        ).mappings().all()

    return ok(
        {
            "prices": [
                {
                    "material_code": r["material_code"],
                    "name": r["name"],
                    "category": r["category"],
                    "unit": r["unit"],
                    "price_vnd": int(r["price_vnd"]),
                    "price_usd": float(r["price_usd"]) if r["price_usd"] is not None else None,
                    "province": r["province"],
                    "source": r["source"],
                    "effective_date": r["effective_date"].isoformat(),
                }
                for r in rows
            ]
        }
    )


@router.get("/series")
async def price_series(
    auth: Annotated[AuthContext, Depends(require_auth)],
    material_code: Annotated[str, Query(min_length=1)],
    provinces: Annotated[list[str] | None, Query()] = None,
    days: Annotated[int, Query(ge=30, le=730)] = 365,
):
    """Time series for one material across the requested provinces.

    `provinces` is a repeated query param (`?provinces=hanoi&provinces=hcmc`).
    When unset, returns ALL provinces with observations for this material —
    useful for the "let me see everywhere" view but can be large
    (~30 provinces × 12 months = 360 points).
    """
    since = date.today() - timedelta(days=days)
    where = ["material_code = :code", "effective_date >= :since"]
    params: dict[str, Any] = {"code": material_code, "since": since}

    if provinces:
        # Postgres ANY(:array) — works with asyncpg's array binding
        where.append("province = ANY(:provinces)")
        params["provinces"] = provinces

    async with AdminSessionFactory() as session:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT
                        province,
                        effective_date,
                        AVG(price_vnd)::numeric AS price_vnd,
                        MIN(unit) AS unit,
                        MIN(name) AS name
                    FROM material_prices
                    WHERE {' AND '.join(where)}
                    GROUP BY province, effective_date
                    ORDER BY province, effective_date ASC
                    """
                ),
                params,
            )
        ).mappings().all()

    # Group by province for the chart's per-line dataset
    per_province: dict[str, list[dict[str, Any]]] = {}
    unit = None
    name = material_code
    for r in rows:
        per_province.setdefault(r["province"] or "(unknown)", []).append(
            {
                "date": r["effective_date"].isoformat(),
                "price_vnd": int(r["price_vnd"]),
            }
        )
        if r["unit"]:
            unit = r["unit"]
        if r["name"]:
            name = r["name"]

    return ok(
        {
            "material_code": material_code,
            "material_name": name,
            "unit": unit,
            "since": since.isoformat(),
            "until": date.today().isoformat(),
            "series": [
                {"province": p, "points": pts}
                for p, pts in sorted(per_province.items())
            ],
        }
    )


@router.get("/compare")
async def compare_provinces(
    auth: Annotated[AuthContext, Depends(require_auth)],
    materials: Annotated[list[str] | None, Query()] = None,
    provinces: Annotated[list[str] | None, Query()] = None,
):
    """Pivoted price matrix: provinces × materials → latest price.

    Used by the procurement view: "which province is cheapest for
    cement this month?". Defaults to the popular materials list +
    top 5 provinces by observation count.
    """
    if not materials:
        materials = POPULAR_MATERIALS

    async with AdminSessionFactory() as session:
        if not provinces:
            # Pick top-N most-observed provinces if caller didn't specify
            top_rows = (
                await session.execute(
                    text(
                        """
                        SELECT province
                        FROM material_prices
                        WHERE province IS NOT NULL
                        GROUP BY province
                        ORDER BY COUNT(*) DESC
                        LIMIT 5
                        """
                    )
                )
            ).scalars().all()
            provinces = list(top_rows)

        rows = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT ON (material_code, province)
                        material_code, name, unit,
                        province, price_vnd, effective_date
                    FROM material_prices
                    WHERE material_code = ANY(:materials)
                      AND province = ANY(:provinces)
                    ORDER BY material_code, province, effective_date DESC
                    """
                ),
                {"materials": materials, "provinces": provinces},
            )
        ).mappings().all()

    # Build the pivot: { material_code: { name, unit, prices: { province: { price, date } } } }
    pivot: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = r["material_code"]
        if code not in pivot:
            pivot[code] = {
                "material_code": code,
                "name": r["name"],
                "unit": r["unit"],
                "prices": {},
            }
        pivot[code]["prices"][r["province"]] = {
            "price_vnd": int(r["price_vnd"]),
            "effective_date": r["effective_date"].isoformat(),
        }

    return ok(
        {
            "provinces": provinces,
            "materials": [
                {
                    "material_code": code,
                    "name": data["name"],
                    "unit": data["unit"],
                    "prices": data["prices"],
                }
                for code, data in pivot.items()
            ],
        }
    )
