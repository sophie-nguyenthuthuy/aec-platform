"""Data retention policies and cron helpers (cycles T3 / R-prune).

  RETENTION_POLICIES           -- ordered tuple of all policy descriptors
  _MAX_PRUNE_ROWS_PER_RUN      -- hard cap per cron iteration
  policy_ttl_days(policy, ...) -- effective TTL for one policy
  collect_stats(session)       -- per-policy stats for the admin dashboard
  prune_table(session, policy) -- CTE DELETE + optional S3 archive
  run_retention_cron(session)  -- iterate all policies, commit per table

Per-tenant override helpers:
  set_retention_override(...)
  get_retention_override(...)
  clear_retention_override(...)
"""

from __future__ import annotations

import json
import logging
import uuid as _uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings

logger = logging.getLogger(__name__)

_MAX_PRUNE_ROWS_PER_RUN = 10_000

# Table → Settings attribute name for env-based TTL override.
_TABLE_SETTINGS_ATTR: dict[str, str] = {
    "audit_events": "retention_audit_events_days",
    "webhook_deliveries": "retention_webhook_deliveries_days",
    "search_queries": "retention_search_queries_days",
    "import_jobs": "retention_import_jobs_days",
}


@dataclass(frozen=True)
class RetentionPolicy:
    table: str
    age_column: str
    default_days: int
    extra_where: str | None = None
    archive: bool = False


RETENTION_POLICIES: tuple[RetentionPolicy, ...] = (
    RetentionPolicy(
        table="audit_events",
        age_column="created_at",
        default_days=365,
        extra_where=None,
        archive=True,
    ),
    RetentionPolicy(
        table="webhook_deliveries",
        age_column="created_at",
        default_days=30,
        extra_where="status IN ('delivered', 'failed')",
        archive=False,
    ),
    RetentionPolicy(
        table="search_queries",
        age_column="created_at",
        default_days=90,
        extra_where=None,
        archive=False,
    ),
    RetentionPolicy(
        table="import_jobs",
        age_column="created_at",
        default_days=30,
        extra_where=None,
        archive=True,
    ),
    RetentionPolicy(
        table="api_key_calls",
        age_column="minute_bucket",
        default_days=30,
        extra_where=None,
        archive=False,
    ),
    RetentionPolicy(
        table="codeguard_quota_audit_log",
        age_column="occurred_at",
        default_days=730,
        extra_where=None,
        archive=True,
    ),
    RetentionPolicy(
        table="cron_runs",
        age_column="started_at",
        default_days=30,
        extra_where=None,
        archive=False,
    ),
)

_KNOWN_TABLES: frozenset[str] = frozenset(p.table for p in RETENTION_POLICIES)


def policy_ttl_days(
    policy: RetentionPolicy,
    *,
    per_tenant_override: int | None = None,
) -> int:
    """Return effective TTL days. Priority: per_tenant_override > env > default."""
    if per_tenant_override is not None and per_tenant_override > 0:
        return per_tenant_override
    attr = _TABLE_SETTINGS_ATTR.get(policy.table)
    if attr is not None:
        val = getattr(get_settings(), attr, None)
        if isinstance(val, int) and val > 0:
            return val
    return policy.default_days


async def collect_stats(session: AsyncSession) -> list[dict[str, Any]]:
    """Per-policy stats row for the admin retention dashboard."""
    stats: list[dict[str, Any]] = []
    for policy in RETENTION_POLICIES:
        ttl = policy_ttl_days(policy)
        sql = text(
            f"""
            SELECT
                COUNT(*) AS row_count,
                MIN({policy.age_column}) AS oldest_at,
                COUNT(*) FILTER (
                    WHERE {policy.age_column} < NOW() - INTERVAL '{ttl} days'
                ) AS overdue_count
            FROM {policy.table}
            """
        )
        row = (await session.execute(sql)).mappings().one()
        overdue = row["overdue_count"]
        stats.append(
            {
                "table": policy.table,
                "ttl_days": ttl,
                "row_count": row["row_count"],
                "oldest_at": row["oldest_at"],
                "overdue_count": overdue,
                "projected_next_prune_count": min(overdue, _MAX_PRUNE_ROWS_PER_RUN),
                "archived_to_s3": policy.archive,
            }
        )
    return stats


async def prune_table(
    session: AsyncSession,
    *,
    policy: RetentionPolicy,
) -> dict[str, Any]:
    """Delete up to `_MAX_PRUNE_ROWS_PER_RUN` rows older than `policy_ttl_days(policy)`.

    Uses a CTE + ctid join pattern so the capped batch DELETE is
    race-free against concurrent inserts.  Rows are returned via
    RETURNING and optionally archived to S3 before the commit.

    Archive failure does NOT rollback the DELETE — rows still deleted.
    S3 is a recovery aid; the commit is authoritative.  Archive
    failures are logged at ERROR so they surface without blocking
    the cron run.
    """
    ttl = policy_ttl_days(policy)
    cap = _MAX_PRUNE_ROWS_PER_RUN
    extra = f"AND {policy.extra_where}" if policy.extra_where else ""
    sql = text(
        f"""
        WITH victims AS (
            SELECT ctid FROM {policy.table}
            WHERE {policy.age_column} < NOW() - INTERVAL :interval
            {extra}
            ORDER BY {policy.age_column}
            LIMIT :cap
        )
        DELETE FROM {policy.table} AS t
        USING victims
        WHERE t.ctid = victims.ctid
        RETURNING t.*
        """
    )
    result = await session.execute(sql, {"interval": f"{ttl} days", "cap": cap})
    deleted_rows = list(result.mappings().all())

    archive_key: str | None = None
    if policy.archive and deleted_rows:
        settings = get_settings()
        if settings.s3_bucket:
            try:
                archive_key = await _archive_to_s3(policy, deleted_rows, settings)
            except Exception as exc:
                # rows still deleted — archive failure must not abort the prune
                logger.error(
                    "S3 archive failed for table %s (%d rows): %s — rows still deleted",
                    policy.table,
                    len(deleted_rows),
                    exc,
                )

    return {
        "table": policy.table,
        "deleted_count": len(deleted_rows),
        "archive_key": archive_key,
    }


async def _archive_to_s3(
    policy: RetentionPolicy,
    rows: list[Any],
    settings: Any,
) -> str:
    """Write deleted rows to S3 as JSONL. Returns the S3 key."""
    import aioboto3

    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    key = f"retention/{policy.table}/{stamp}_{_uuid.uuid4().hex}.ndjson"
    body = "\n".join(json.dumps(dict(row), default=str) for row in rows).encode("utf-8")

    s3 = aioboto3.Session(region_name=settings.aws_region)
    async with s3.client("s3") as client:
        await client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=body,
            ContentType="application/x-ndjson",
        )
    return key


async def run_retention_cron(session: AsyncSession) -> list[dict[str, Any]]:
    """Full retention sweep: prune every policy, commit per table.

    Per-table isolation: a failure on one table is caught, rolled back,
    and logged so the remaining tables still run.
    """
    summaries: list[dict[str, Any]] = []
    for policy in RETENTION_POLICIES:
        try:
            out = await prune_table(session, policy=policy)
            await session.commit()
            summaries.append(out)
        except Exception as exc:
            await session.rollback()
            logger.error("retention cron failed for table %s: %s", policy.table, exc)
            summaries.append({"table": policy.table, "error": str(exc)})
    return summaries


# ---------- Per-tenant retention override helpers ----------


async def set_retention_override(
    session: AsyncSession,
    *,
    organization_id: UUID,
    table_name: str,
    ttl_days: int,
    set_by: UUID,
    reason: str | None,
) -> dict[str, Any]:
    if table_name not in _KNOWN_TABLES:
        raise ValueError(f"unknown table_name: {table_name!r}")
    policy = next(p for p in RETENTION_POLICIES if p.table == table_name)
    if ttl_days < policy.default_days:
        raise ValueError(
            f"ttl_days {ttl_days} is shorter than the policy default "
            f"{policy.default_days} for {table_name!r} — "
            "per-tenant overrides may only extend retention"
        )
    await session.execute(
        text(
            """
            INSERT INTO retention_overrides
              (organization_id, table_name, ttl_days, set_by, reason)
            VALUES
              (:org, :table, :ttl, :set_by, :reason)
            ON CONFLICT (organization_id, table_name)
            DO UPDATE SET
              ttl_days   = EXCLUDED.ttl_days,
              set_by     = EXCLUDED.set_by,
              reason     = EXCLUDED.reason,
              updated_at = NOW()
            """
        ),
        {
            "org": str(organization_id),
            "table": table_name,
            "ttl": ttl_days,
            "set_by": str(set_by),
            "reason": reason,
        },
    )
    await session.commit()
    return {
        "organization_id": str(organization_id),
        "table_name": table_name,
        "ttl_days": ttl_days,
        "reason": reason,
    }


async def get_retention_override(
    session: AsyncSession,
    *,
    organization_id: UUID,
    table_name: str,
) -> int | None:
    row = (
        (
            await session.execute(
                text("SELECT ttl_days FROM retention_overrides WHERE organization_id = :org AND table_name = :table"),
                {"org": str(organization_id), "table": table_name},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return int(row["ttl_days"])


async def clear_retention_override(
    session: AsyncSession,
    *,
    organization_id: UUID,
    table_name: str,
) -> bool:
    result = await session.execute(
        text("DELETE FROM retention_overrides WHERE organization_id = :org AND table_name = :table"),
        {"org": str(organization_id), "table": table_name},
    )
    await session.commit()
    return result.rowcount > 0
