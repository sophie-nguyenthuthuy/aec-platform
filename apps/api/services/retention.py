"""Per-table retention + archival for unbounded growth tables.

Without this, `audit_events`, `search_queries`, `import_jobs`, and the
delivered/failed slice of `webhook_deliveries` grow forever. Storage
cost climbs, and indexed scans on org-scoped queries get slower as
the relation pages bloat.

Design:

  * **Per-table TTL.** A small frozen registry (`RETENTION_POLICIES`)
    maps table → days + age column + archive flag. Adding a table is
    one entry here; the cron walks them all.

  * **DELETE … RETURNING.** One round trip — we get the JSON-shaped
    rows back to archive without a separate SELECT. The DELETE is
    capped per-run so a misconfig (or a previously-stalled cron
    catching up) can't hold an exclusive lock for minutes.

  * **Optional S3 JSONL archive.** When `archive=True` the service
    writes one `.jsonl` per (table, run) to
    `s3://{bucket}/retention/{table}/{run_date}.jsonl` BEFORE deleting.
    Each line is a row encoded by `json.dumps(default=str)` so
    datetimes / UUIDs / Decimals serialise without bespoke encoders.
    Skipped (logs a warning) when `AWS_BUCKET` isn't configured —
    dev/test paths get the prune semantics without needing S3.

  * **Admin session.** The cron uses `AdminSessionFactory` (BYPASSRLS)
    rather than `TenantAwareSession` because retention is a global
    job — we want to prune ALL orgs in one pass, with the per-org
    isolation enforced by the WHERE clause on age, not by RLS.

What this DOESN'T do:

  * Per-org overrides. Real customers will eventually want
    "keep audit for 7 years for compliance". When that lands we'll
    add a `retention_policies` table and read from there before
    falling back to the registry. For v1, env-var TTL is enough.

  * Restore. The S3 archive is a one-way ticket — operators who need
    to reconstruct deleted rows must download the JSONL and re-INSERT
    manually. A restore script would be its own bucket of work.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings

logger = logging.getLogger(__name__)


# Hard cap on rows per prune run. Two reasons:
#   * Lock duration: a 100k-row DELETE on `audit_events` would hold a
#     tuple lock long enough to slow down concurrent inserts. 10k
#     keeps the run under a few seconds.
#   * Archive size: 10k JSONL rows ~ a few MB at most.
# A backed-up cron will catch up over multiple runs — daily cadence
# means a tenant churning 100k rows/day fills the cap once and
# steady-states.
_MAX_PRUNE_ROWS_PER_RUN = 10_000


# ---------- Registry ----------


@dataclass(frozen=True)
class RetentionPolicy:
    """One row per table that ever needs pruning. `age_column` is the
    column we compare to NOW() — usually `created_at`, sometimes
    `committed_at` or `next_retry_at` depending on what "old enough
    to delete" means for the row."""

    table: str
    age_column: str
    default_days: int
    # Optional extra WHERE fragment AND'd onto the delete predicate.
    # Used by `webhook_deliveries` to keep `pending` rows alive even
    # if they're older than the TTL — the delivery cron will retry
    # them, deleting now would mean silently losing the event.
    extra_where: str | None
    # When True, copy the deleted rows to S3 as JSONL before the
    # DELETE commits. Keep False for high-churn tables where the
    # archive cost outweighs the recovery value (search_queries
    # are purely telemetry — losing old ones isn't recoverable
    # anyway).
    archive: bool


# Order doesn't matter functionally but the cron iterates in order;
# heaviest table first so a cap-hit there doesn't starve the others.
RETENTION_POLICIES: tuple[RetentionPolicy, ...] = (
    # Compliance-relevant. Default 365d; ops can extend by ENV.
    RetentionPolicy(
        table="audit_events",
        age_column="created_at",
        default_days=365,
        extra_where=None,
        archive=True,
    ),
    # Webhook delivery history — only delete terminal states.
    RetentionPolicy(
        table="webhook_deliveries",
        age_column="created_at",
        default_days=30,
        extra_where="status IN ('delivered', 'failed')",
        archive=False,  # Subscriber URL + payload size make this expensive.
    ),
    # Pure telemetry — losing old rows is fine.
    RetentionPolicy(
        table="search_queries",
        age_column="created_at",
        default_days=90,
        extra_where=None,
        archive=False,
    ),
    # Operational records. Once committed, we don't need the JSONB
    # `rows` blob anymore, but the user might want to know "did I
    # import that supplier in March". Keep summary metadata; the
    # blob is what bloats. For v1 we just delete the whole row.
    RetentionPolicy(
        table="import_jobs",
        age_column="created_at",
        default_days=30,
        extra_where=None,
        archive=True,
    ),
    # Per-minute API call rollup. A busy partner produces ~1.5k
    # rows/key/day; 30d caps a single key at ~45k rows. Pure
    # observability — no archive value beyond the dashboard window.
    RetentionPolicy(
        table="api_key_calls",
        age_column="minute_bucket",
        default_days=30,
        extra_where=None,
        archive=False,
    ),
    # Codeguard quota mutation audit. Compliance-relevant: tenant
    # admins answer "who raised our cap last quarter" and auditors
    # do year-over-year compares. 730d (2 years) balances "compliance
    # has the window they need" against "the table can't unbounded-
    # grow if a misconfigured `quota_reconcile` cron writes thousands
    # of rows per tick". `archive=True` mirrors `audit_events` so a
    # deletion is recoverable from S3 if a customer disputes a much
    # older cap change. `occurred_at` is the audit-row timestamp
    # (DEFAULT NOW() at insert) — preferred over a generic `created_at`
    # because semantically the audit row IS the event timestamp.
    RetentionPolicy(
        table="codeguard_quota_audit_log",
        age_column="occurred_at",
        default_days=730,
        extra_where=None,
        archive=True,
    ),
)


def policy_ttl_days(policy: RetentionPolicy) -> int:
    """Read the TTL from `AEC_RETENTION_<TABLE>_DAYS` env, falling
    back to `policy.default_days`. The env override is the v1
    customisation hook — Customer Success can bump audit retention
    for a compliance-conscious tenant by setting one variable."""
    settings = get_settings()
    # `extra` field on Settings holds raw env keys — read defensively
    # so a missing override doesn't 500 on every cron run.
    env_key = f"retention_{policy.table}_days"
    override = getattr(settings, env_key, None)
    if isinstance(override, int) and override > 0:
        return override
    return policy.default_days


# ---------- Stats ----------


async def collect_stats(session: AsyncSession) -> list[dict[str, Any]]:
    """One row per managed table: row count, oldest age, configured
    TTL, projected next-prune count. Drives the admin dashboard.

    The `projected_next_prune_count` is capped at MAX_PRUNE_ROWS_PER_RUN
    to match what the cron would actually do. A misconfigured tenant
    that's months behind will still see "10000+" not "8.4M" —
    operationally what they care about.
    """
    out: list[dict[str, Any]] = []
    for policy in RETENTION_POLICIES:
        ttl_days = policy_ttl_days(policy)
        extra = f" AND ({policy.extra_where})" if policy.extra_where else ""
        # Age stats + total count in one round trip per table.
        row = (
            (
                await session.execute(
                    text(
                        f"""
                        SELECT
                            COUNT(*) AS row_count,
                            MIN({policy.age_column}) AS oldest_at,
                            COUNT(*) FILTER (
                                WHERE {policy.age_column} < NOW() - INTERVAL '{int(ttl_days)} days'
                                {extra}
                            ) AS overdue_count
                        FROM {policy.table}
                        """
                    )
                )
            )
            .mappings()
            .one()
        )
        overdue = int(row["overdue_count"] or 0)
        out.append(
            {
                "table": policy.table,
                "ttl_days": ttl_days,
                "row_count": int(row["row_count"] or 0),
                "oldest_at": row["oldest_at"].isoformat() if row["oldest_at"] else None,
                "overdue_count": overdue,
                "projected_next_prune_count": min(overdue, _MAX_PRUNE_ROWS_PER_RUN),
                "archived_to_s3": policy.archive,
            }
        )
    return out


# ---------- Prune ----------


async def prune_table(
    session: AsyncSession,
    *,
    policy: RetentionPolicy,
) -> dict[str, Any]:
    """Delete up to `_MAX_PRUNE_ROWS_PER_RUN` rows older than the TTL,
    optionally archiving them to S3 first.

    Returns `{"table", "deleted_count", "archived_key_or_none"}`. The
    caller (cron / admin endpoint) is expected to log the dict —
    operationally the count is what we watch in dashboards.

    The DELETE is wrapped in a CTE so we can pull `RETURNING *` for
    archival in one round trip. Without the CTE we'd need a separate
    SELECT before DELETE, which would race a concurrent INSERT and
    let new rows slip in between SELECT and DELETE — not catastrophic
    here (pending → archived later) but the CTE shape is cleaner.
    """
    ttl_days = policy_ttl_days(policy)
    extra_clause = f" AND ({policy.extra_where})" if policy.extra_where else ""
    sql = f"""
    WITH victims AS (
        SELECT ctid
        FROM {policy.table}
        WHERE {policy.age_column} < NOW() - INTERVAL '{int(ttl_days)} days'
          {extra_clause}
        ORDER BY {policy.age_column} ASC
        LIMIT :cap
    )
    DELETE FROM {policy.table} t
    USING victims v
    WHERE t.ctid = v.ctid
    RETURNING t.*
    """
    result = await session.execute(text(sql), {"cap": _MAX_PRUNE_ROWS_PER_RUN})
    deleted = [dict(r) for r in result.mappings().all()]
    if not deleted:
        return {"table": policy.table, "deleted_count": 0, "archive_key": None}

    archive_key: str | None = None
    if policy.archive:
        try:
            archive_key = await _archive_to_s3(table=policy.table, rows=deleted)
        except Exception as exc:  # pragma: no cover — defensive
            # Don't roll back the delete on archive failure — the
            # operator's intent ("get rid of these rows") is more
            # important than the archive (which is a recovery aid,
            # not a correctness invariant). Log loudly so we notice.
            logger.error(
                "retention.archive failed for %s: %s — rows still deleted",
                policy.table,
                exc,
            )
    return {
        "table": policy.table,
        "deleted_count": len(deleted),
        "archive_key": archive_key,
    }


# ---------- S3 archive ----------


async def _archive_to_s3(*, table: str, rows: list[dict[str, Any]]) -> str | None:
    """Upload `rows` as a JSONL blob to
    `s3://{bucket}/retention/{table}/{YYYY-MM-DD}-{HHMMSS}.jsonl`.

    Returns the storage key (relative to bucket) on success, or None
    when no S3 bucket is configured. Each row is `json.dumps`'d with
    `default=str` so datetimes / UUIDs / Decimals serialise without
    bespoke encoders.
    """
    settings = get_settings()
    bucket = getattr(settings, "s3_bucket", None)
    if not bucket:
        logger.warning("retention.archive: AEC_S3_BUCKET not set; skipping archive for %s", table)
        return None

    import aioboto3  # lazy: only used by the cron path

    stamp = datetime.utcnow().strftime("%Y-%m-%d-%H%M%S")
    key = f"retention/{table}/{stamp}.jsonl"
    body = "\n".join(json.dumps(r, default=str) for r in rows).encode("utf-8")

    session = aioboto3.Session(region_name=settings.aws_region)
    async with session.client("s3") as client:
        await client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/x-ndjson",
        )

    logger.info(
        "retention.archive: %s rows → s3://%s/%s (%d bytes)",
        len(rows),
        bucket,
        key,
        len(body),
    )
    return key


# ---------- Cron entrypoint ----------


async def run_retention_cron(session: AsyncSession) -> list[dict[str, Any]]:
    """Iterate the registry and prune each table. Returns one summary
    dict per table — the arq cron logs the list at INFO so a operator
    can grep one log line for the day's prune metrics.

    Per-table errors are caught and reported in-line so a transient
    failure on one table doesn't skip the others. The cron-level
    transaction commits per-table so a partial run is durable: if
    `audit_events` succeeds and `search_queries` fails, we still
    archived + pruned audit_events.
    """
    summaries: list[dict[str, Any]] = []
    for policy in RETENTION_POLICIES:
        try:
            summary = await prune_table(session, policy=policy)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error("retention.prune_table failed for %s: %s", policy.table, exc)
            summary = {"table": policy.table, "deleted_count": 0, "error": str(exc)}
        summaries.append(summary)
    return summaries
