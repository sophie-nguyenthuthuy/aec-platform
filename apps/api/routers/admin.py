"""Cross-module admin / ops endpoints.

Distinct from per-vertical routers because the data here is *global*:

  * No tenant scope — `scraper_runs` etc. have no `organization_id`.
  * Reads use `AdminSessionFactory` (BYPASSRLS) for that reason.
  * Routes gated to the `admin` role via `require_role` so a regular
    org member can't enumerate ops telemetry across tenants.

First endpoint: `GET /api/v1/admin/scraper-runs` — surfaces drift
trends from the B.2 telemetry table to the dashboard.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from core.envelope import ok
from db.session import AdminSessionFactory
from middleware.auth import AuthContext, require_role
from models.core import ScraperRun
from schemas.admin import ScraperRunOut

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/scraper-runs")
async def list_scraper_runs(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
    slug: str | None = Query(default=None, description="Filter to one scraper slug"),
    limit: int = Query(default=20, ge=1, le=200),
):
    """Most-recent N runs, optionally for a single slug.

    Index-friendly: the `(slug, started_at DESC)` index from migration
    0012 covers both the slug-filter and the no-filter branches.
    """
    stmt = select(ScraperRun).order_by(ScraperRun.started_at.desc()).limit(limit)
    if slug:
        stmt = stmt.where(ScraperRun.slug == slug)

    async with AdminSessionFactory() as session:
        rows = (await session.execute(stmt)).scalars().all()

    return ok([ScraperRunOut.model_validate(r).model_dump(mode="json") for r in rows])
