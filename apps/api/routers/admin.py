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
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from core.envelope import ok
from db.session import AdminSessionFactory
from middleware.auth import AuthContext, require_role
from models.core import ScraperRun
from schemas.admin import (
    NormalizerRuleCreate,
    NormalizerRuleUpdate,
    ScraperRunOut,
)

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


# ---------- Normaliser rules ----------
#
# DB-backed regex rules merged on top of the in-code `_RULES` in
# `services.price_scrapers.normalizer`. Lets ops tune material
# coverage from the admin UI without a deploy. See migration
# `0028_normalizer_rules.py` for the table-shape rationale and
# the in-code merge semantics.


@router.get("/normalizer-rules")
async def list_normalizer_rules(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
):
    """All rules (enabled + disabled), sorted by priority ASC."""
    from models.core import NormalizerRule
    from schemas.admin import NormalizerRuleOut

    async with AdminSessionFactory() as session:
        rows = (
            (
                await session.execute(
                    select(NormalizerRule).order_by(
                        NormalizerRule.priority.asc(),
                        NormalizerRule.created_at.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
    return ok([NormalizerRuleOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/normalizer-rules", status_code=201)
async def create_normalizer_rule(
    payload: NormalizerRuleCreate,
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
):
    """Add a new rule. Returns the persisted row.

    The pattern is validated as a Python regex BEFORE the row is
    written so a typo gets a 400, not a silent "this rule never
    matches anything" 0-hit row in production telemetry.
    """
    import re
    from datetime import UTC, datetime
    from uuid import uuid4

    from fastapi import HTTPException
    from fastapi import status as http_status

    from models.core import NormalizerRule
    from schemas.admin import NormalizerRuleOut

    try:
        re.compile(payload.pattern, re.IGNORECASE)
    except re.error as exc:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, f"Invalid regex: {exc}") from exc

    now = datetime.now(UTC)
    row = NormalizerRule(
        id=uuid4(),
        priority=payload.priority,
        pattern=payload.pattern,
        material_code=payload.material_code,
        category=payload.category,
        canonical_name=payload.canonical_name,
        preferred_units=payload.preferred_units,
        enabled=payload.enabled,
        created_at=now,
        updated_at=now,
        created_by=auth.user_id,
    )
    async with AdminSessionFactory() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    # Bust the in-process rule cache. Without this, a freshly-created
    # rule wouldn't take effect until the next scraper-run kick.
    from services.price_scrapers.normalizer import refresh_db_rules

    await refresh_db_rules()
    return ok(NormalizerRuleOut.model_validate(row).model_dump(mode="json"))


@router.patch("/normalizer-rules/{rule_id}")
async def update_normalizer_rule(
    rule_id: UUID,
    payload: NormalizerRuleUpdate,
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
):
    """Partial update. Only fields present in the body get written.

    `pattern` is regex-validated when it changes — same 400 behaviour
    as `create_normalizer_rule`.
    """
    import re
    from datetime import UTC, datetime

    from fastapi import HTTPException
    from fastapi import status as http_status

    from models.core import NormalizerRule
    from schemas.admin import NormalizerRuleOut

    if payload.pattern is not None:
        try:
            re.compile(payload.pattern, re.IGNORECASE)
        except re.error as exc:
            raise HTTPException(http_status.HTTP_400_BAD_REQUEST, f"Invalid regex: {exc}") from exc

    async with AdminSessionFactory() as session:
        row = (await session.execute(select(NormalizerRule).where(NormalizerRule.id == rule_id))).scalar_one_or_none()
        if row is None:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Rule not found")

        # Apply only the fields the caller actually set (PATCH semantics).
        for field in (
            "priority",
            "pattern",
            "material_code",
            "category",
            "canonical_name",
            "preferred_units",
            "enabled",
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(row, field, value)
        row.updated_at = datetime.now(UTC)

        await session.commit()
        await session.refresh(row)

    from services.price_scrapers.normalizer import refresh_db_rules

    await refresh_db_rules()
    return ok(NormalizerRuleOut.model_validate(row).model_dump(mode="json"))


@router.delete("/normalizer-rules/{rule_id}", status_code=204)
async def delete_normalizer_rule(
    rule_id: UUID,
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
):
    """Hard-delete a rule.

    Soft-disable (PATCH `enabled=false`) is preferred when ops just
    want to silence a rule — keeps the row + audit trail. DELETE is
    here for the "this was a typo, get it out of the table" case.
    """
    from fastapi import HTTPException
    from fastapi import status as http_status

    from models.core import NormalizerRule

    async with AdminSessionFactory() as session:
        row = (await session.execute(select(NormalizerRule).where(NormalizerRule.id == rule_id))).scalar_one_or_none()
        if row is None:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Rule not found")
        await session.delete(row)
        await session.commit()

    from services.price_scrapers.normalizer import refresh_db_rules

    await refresh_db_rules()
    return None
