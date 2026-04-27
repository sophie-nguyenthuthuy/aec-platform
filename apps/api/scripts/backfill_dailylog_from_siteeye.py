"""One-shot backfill: mirror existing SafetyIncident rows into DailyLog observations.

Walks every safety_incidents row that has a project_id, calls
`services.dailylog_sync.sync_incident_to_dailylog` for each, and prints a
summary. Idempotent: incidents whose mirror observation already exists
(via `related_safety_incident_id`) are skipped by the sync helper.

Usage
-----

    cd apps/api
    PYTHONPATH=. python -m scripts.backfill_dailylog_from_siteeye

    # Dry-run (count what would be synced, don't write):
    PYTHONPATH=. python -m scripts.backfill_dailylog_from_siteeye --dry-run

    # Limit to one organisation (e.g. when re-running after a tenant
    # imported historical incidents from a 3rd-party system):
    PYTHONPATH=. python -m scripts.backfill_dailylog_from_siteeye --org-id <uuid>

The script issues one DB connection per incident batch and commits per
incident — so a Ctrl-C in the middle leaves the partial sync intact and
the next run picks up where it stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from services.dailylog_sync import sync_incident_to_dailylog

logger = logging.getLogger("backfill_dailylog")


async def _iter_incidents(session: Any, *, org_id: UUID | None, batch_size: int):
    """Yield incidents in batches of `batch_size`, ordered by detected_at."""
    where = "project_id IS NOT NULL"
    params: dict[str, Any] = {"limit": batch_size, "offset": 0}
    if org_id:
        where += " AND organization_id = :org"
        params["org"] = str(org_id)

    while True:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT id, organization_id, project_id, detected_at,
                           severity, incident_type, ai_description
                    FROM safety_incidents
                    WHERE {where}
                    ORDER BY detected_at ASC, id ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        ).all()
        if not rows:
            return
        for r in rows:
            yield r
        params["offset"] += batch_size


async def run_backfill(*, org_id: UUID | None, dry_run: bool, batch_size: int) -> dict[str, int]:
    """Returns counters. The script doesn't take any locks: it's safe to run
    concurrently with the live SiteEye worker that creates new incidents
    (those are mirrored inline by the worker; backfill skips them via the
    idempotency check)."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    counters = {"scanned": 0, "synced": 0, "skipped": 0, "errors": 0}

    async with sessionmaker() as session:
        async for inc in _iter_incidents(session, org_id=org_id, batch_size=batch_size):
            counters["scanned"] += 1
            try:
                if dry_run:
                    # Without inserting, we can't know "would-be-synced" precisely
                    # without doing the idempotency check ourselves. Cheap proxy:
                    # check whether an observation already exists.
                    existing = (
                        await session.execute(
                            text(
                                "SELECT 1 FROM daily_log_observations WHERE related_safety_incident_id = :iid LIMIT 1"
                            ),
                            {"iid": str(inc.id)},
                        )
                    ).one_or_none()
                    if existing is None:
                        counters["synced"] += 1
                    else:
                        counters["skipped"] += 1
                    continue

                result = await sync_incident_to_dailylog(
                    session,
                    organization_id=inc.organization_id,
                    incident=inc,
                )
                if result is None:
                    counters["skipped"] += 1
                else:
                    counters["synced"] += 1
                    await session.commit()
            except Exception as exc:  # noqa: BLE001
                counters["errors"] += 1
                logger.exception("backfill: incident %s failed: %s", inc.id, exc)
                await session.rollback()

            if counters["scanned"] % 100 == 0:
                logger.info("backfill: %s", counters)

    await engine.dispose()
    return counters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--org-id",
        type=UUID,
        default=None,
        help="Limit backfill to a single organization (default: all orgs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write — count what would be synced",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="DB pagination batch size (default: 200)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    counters = asyncio.run(run_backfill(org_id=args.org_id, dry_run=args.dry_run, batch_size=args.batch_size))
    print(
        f"\nBackfill {'(DRY-RUN) ' if args.dry_run else ''}done — "
        f"scanned={counters['scanned']} "
        f"synced={counters['synced']} "
        f"skipped={counters['skipped']} "
        f"errors={counters['errors']}"
    )


if __name__ == "__main__":
    main()
