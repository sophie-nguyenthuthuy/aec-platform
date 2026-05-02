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
from sqlalchemy import select, text

from core.envelope import ok
from db.session import AdminSessionFactory
from middleware.auth import AuthContext, require_role
from models.core import ScraperRun
from schemas.admin import (
    NormalizerRuleCreate,
    NormalizerRuleUpdate,
    ScraperRunOut,
    ScraperRunsSummaryRow,
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


@router.get("/scraper-runs/summary")
async def scraper_runs_summary(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
    days: int = Query(default=30, ge=1, le=365),
):
    """Per-slug aggregate over the last `days` days. Drives the
    `/admin/scrapers` summary table + drift sparkline.

    Returns rows sorted by `avg_drift DESC NULLS LAST` so the slugs
    most likely to need ops attention surface at the top of the table.
    Each row carries a `points` series (oldest → newest) for the inline
    sparkline; we don't downsample because a daily cron over a 30-day
    window only produces ~30 points per slug.

    Raw SQL (not ORM) because we need a window function for `last_run_ok`
    + a JSON aggregate for `points`. The `(slug, started_at DESC)` index
    from migration 0012 covers the `started_at >= now - interval` filter
    on the slug-grouped path.
    """
    sql = text(
        """
        WITH recent AS (
            SELECT slug, started_at, ok, scraped, unmatched
            FROM scraper_runs
            WHERE started_at >= now() - make_interval(days := :days)
        ),
        last_runs AS (
            -- One row per slug — the most recent run within the window.
            -- DISTINCT ON is the conventional PG idiom for this; the
            -- (slug, started_at DESC) index makes it index-only.
            SELECT DISTINCT ON (slug) slug, ok
            FROM recent
            ORDER BY slug, started_at DESC
        )
        SELECT
            r.slug                                                  AS slug,
            COUNT(*)                                                AS total_runs,
            -- failure_rate = fraction of runs in the window where ok=false.
            -- Cast to float so PG returns a numeric, not an integer 0/1.
            (SUM(CASE WHEN r.ok THEN 0 ELSE 1 END)::float
                / NULLIF(COUNT(*), 0))                              AS failure_rate,
            -- avg_drift averages per-run unmatched ratios, ignoring runs
            -- that scraped 0 rows (would be NaN). PG's AVG() already
            -- skips NULLs.
            AVG(
                CASE WHEN r.scraped > 0
                     THEN r.unmatched::float / r.scraped
                     ELSE NULL END
            )                                                       AS avg_drift,
            MAX(r.started_at)                                       AS last_run_at,
            lr.ok                                                   AS last_run_ok,
            -- json_agg with ORDER BY is supported PG 9.5+. The result
            -- is a JSON array which Pydantic happily parses into the
            -- `list[ScraperRunsSummaryPoint]` schema.
            json_agg(
                json_build_object(
                    'started_at', r.started_at,
                    'ratio',
                    CASE WHEN r.scraped > 0
                         THEN r.unmatched::float / r.scraped
                         ELSE NULL END
                )
                ORDER BY r.started_at ASC
            )                                                       AS points
        FROM recent r
        JOIN last_runs lr ON lr.slug = r.slug
        GROUP BY r.slug, lr.ok
        ORDER BY avg_drift DESC NULLS LAST
        """
    )

    async with AdminSessionFactory() as session:
        rows = (await session.execute(sql, {"days": days})).mappings().all()

    return ok([ScraperRunsSummaryRow.model_validate(dict(r)).model_dump(mode="json") for r in rows])


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
        # `normalizer_rules` is GLOBAL config — a single edit affects
        # every tenant's price scrapes. We MUST audit it. Attribute to
        # the actor's org so that org's admins can see what their
        # members did. Same transaction as the row write so a rollback
        # on commit() takes the audit row with it.
        from services.audit import record as audit_record

        await audit_record(
            session,
            organization_id=auth.organization_id,
            actor_user_id=auth.user_id,
            action="admin.normalizer_rule.create",
            resource_type="normalizer_rule",
            resource_id=row.id,
            after={
                "priority": row.priority,
                "pattern": row.pattern,
                "material_code": row.material_code,
                "canonical_name": row.canonical_name,
                "enabled": row.enabled,
            },
        )
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

        # Snapshot the pre-mutation values for any field the caller is
        # about to change. Limiting the diff to ACTUALLY-CHANGED fields
        # keeps audit rows small and PII-free, and matches the contract
        # documented in `services/audit.py` ("`before` / `after` are
        # *minimal* JSON diffs").
        before_diff: dict[str, object] = {}
        after_diff: dict[str, object] = {}

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
                old = getattr(row, field)
                if old != value:
                    before_diff[field] = old
                    after_diff[field] = value
                setattr(row, field, value)
        row.updated_at = datetime.now(UTC)

        # Only emit an audit event when SOMETHING actually changed —
        # a no-op PATCH (caller PATCHed with the same value) shouldn't
        # pollute the trail. Same transaction so a commit rollback
        # rolls back the audit row too.
        if after_diff:
            from services.audit import record as audit_record

            await audit_record(
                session,
                organization_id=auth.organization_id,
                actor_user_id=auth.user_id,
                action="admin.normalizer_rule.update",
                resource_type="normalizer_rule",
                resource_id=row.id,
                before=before_diff,
                after=after_diff,
            )

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

        # Snapshot the row's content into the audit `before` BEFORE the
        # delete — once delete() runs the row is detached and the
        # captured fields are the only record of what existed. Audit
        # row goes in the same transaction so a rollback un-deletes
        # the rule AND removes the audit row in lockstep.
        before_snapshot = {
            "priority": row.priority,
            "pattern": row.pattern,
            "material_code": row.material_code,
            "canonical_name": row.canonical_name,
            "enabled": row.enabled,
        }
        rule_id_captured = row.id

        await session.delete(row)

        from services.audit import record as audit_record

        await audit_record(
            session,
            organization_id=auth.organization_id,
            actor_user_id=auth.user_id,
            action="admin.normalizer_rule.delete",
            resource_type="normalizer_rule",
            resource_id=rule_id_captured,
            before=before_snapshot,
        )

        await session.commit()

    from services.price_scrapers.normalizer import refresh_db_rules

    await refresh_db_rules()
    return None


# ---------- Retention dashboard ----------


@router.get("/retention/status")
async def retention_status(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
):
    """Per-table retention metrics: row count, oldest row age, TTL,
    and how many rows the next nightly cron run will prune.

    Uses `AdminSessionFactory` because retention is platform-global —
    we want totals across every tenant, not just the admin's. The
    underlying tables that ARE tenant-scoped (audit_events,
    search_queries, import_jobs) have their own RLS, but BYPASSRLS
    is the right posture here — this is ops telemetry, not
    customer-facing data.
    """
    from services.retention import collect_stats

    async with AdminSessionFactory() as session:
        stats = await collect_stats(session)
    return ok(stats)


@router.post("/retention/run", status_code=202)
async def retention_run_now(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
):
    """On-demand prune. Same job as the nightly cron, fired manually.

    Useful for: (1) initial cleanup after deploying retention to a
    long-lived org with years of audit history; (2) reproducing a
    cron failure with the operator watching the logs. Bounded by
    the same per-run row cap as the cron, so a single click won't
    lock the table for minutes.
    """
    from services.retention import run_retention_cron

    async with AdminSessionFactory() as session:
        summaries = await run_retention_cron(session)
    return ok({"tables": summaries})
