"""One-shot backfill: embed every existing RFI into rfi_embeddings.

Symmetric to scripts/backfill_dailylog_from_siteeye. The drawbridge router
auto-embeds new RFIs at create/update time (since 658fc23), but RFIs that
existed before that change have no row in `rfi_embeddings`, so the
similar-RFI search at /api/v1/submittals/rfis/{id}/similar can't find them
and `/draft` can't use them as ground-truth precedents.

Walks `rfis` ordered by created_at, calls
`ml.pipelines.rfi.upsert_rfi_embedding` for each. The upsert is idempotent
on (rfi_id) — a row already embedded gets refreshed (model_version + new
created_at), which is also useful when you want to re-embed against a new
model version.

Usage
-----

The pipeline lives in `apps/ml`, so PYTHONPATH must include both
`apps/api` (for `core.config`, `services.*`) and `apps` (for
`ml.pipelines.*`).

    cd /path/to/aec-platform
    PYTHONPATH=apps/api:apps python -m scripts.backfill_rfi_embeddings \
      [--skip-existing] [--org-id <uuid>] [--dry-run] [-v]

    # Or via the Makefile target if one exists:
    make backfill-rfi-embeddings ARGS="--dry-run"

The pipeline's embed_text() degrades gracefully without OPENAI_API_KEY
(returns a zero vector), so the script will still complete in dev — but
those RFIs will all be "identical" in similarity space, which is useless
for the search. Run this in an environment with credentials when you
actually want hits.
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

logger = logging.getLogger("backfill_rfi_embeddings")


async def _iter_rfis(session: Any, *, org_id: UUID | None, batch_size: int):
    """Yield rfis in batches ordered by created_at."""
    where = "TRUE"
    params: dict[str, Any] = {"limit": batch_size, "offset": 0}
    if org_id:
        where = "organization_id = :org"
        params["org"] = str(org_id)

    while True:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT id, organization_id, subject, description
                    FROM rfis
                    WHERE {where}
                    ORDER BY created_at ASC, id ASC
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


async def _has_embedding(session: Any, rfi_id: UUID) -> bool:
    row = (
        await session.execute(
            text("SELECT 1 FROM rfi_embeddings WHERE rfi_id = :id LIMIT 1"),
            {"id": str(rfi_id)},
        )
    ).one_or_none()
    return row is not None


async def run_backfill(
    *,
    org_id: UUID | None,
    dry_run: bool,
    skip_existing: bool,
    batch_size: int,
) -> dict[str, int]:
    # Late import — the pipeline lives in `apps/ml` which the caller must
    # add to PYTHONPATH (see module docstring). Importing at module top
    # would fail at the `python -m scripts.backfill_rfi_embeddings --help`
    # line for users who haven't set it yet, hiding the actual error.
    from ml.pipelines.rfi import upsert_rfi_embedding

    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    counters = {"scanned": 0, "embedded": 0, "skipped_existing": 0, "errors": 0}

    async with sessionmaker() as session:
        async for rfi in _iter_rfis(session, org_id=org_id, batch_size=batch_size):
            counters["scanned"] += 1
            try:
                if skip_existing and await _has_embedding(session, rfi.id):
                    counters["skipped_existing"] += 1
                    continue
                if dry_run:
                    counters["embedded"] += 1
                    continue

                await upsert_rfi_embedding(
                    session,
                    organization_id=rfi.organization_id,
                    rfi_id=rfi.id,
                    subject=rfi.subject,
                    description=rfi.description,
                )
                await session.commit()
                counters["embedded"] += 1
            except Exception as exc:  # noqa: BLE001
                counters["errors"] += 1
                logger.exception("backfill: rfi %s failed: %s", rfi.id, exc)
                await session.rollback()

            if counters["scanned"] % 50 == 0:
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
        "--skip-existing",
        action="store_true",
        help="Skip RFIs that already have a row in rfi_embeddings",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write — count what would be embedded",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="DB pagination batch size (default: 100)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    counters = asyncio.run(
        run_backfill(
            org_id=args.org_id,
            dry_run=args.dry_run,
            skip_existing=args.skip_existing,
            batch_size=args.batch_size,
        )
    )
    print(
        f"\nBackfill {'(DRY-RUN) ' if args.dry_run else ''}done — "
        f"scanned={counters['scanned']} "
        f"embedded={counters['embedded']} "
        f"skipped_existing={counters['skipped_existing']} "
        f"errors={counters['errors']}"
    )


if __name__ == "__main__":
    main()
