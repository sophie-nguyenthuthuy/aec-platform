"""One-shot backfill: relocate api-key UUIDs from audit_events.actor_user_id
to audit_events.actor_api_key_id.

Pairs with migration 0033_audit_actor_api_key. Before that migration,
api-key-driven mutations either FK-violated on insert (the dominant
failure mode) or — wherever the FK happened to be off — landed an
`api_keys.id` UUID in `actor_user_id`, which has an FK to `users.id`.
Those rows JOIN to NULL on the read endpoint and render as anonymous
"system" entries.

This script finds those orphaned rows, confirms each one's
`actor_user_id` resolves to a real `api_keys.id` (and NOT a `users.id`
that just happens to have been deleted), and moves the UUID across.

Idempotent: re-running is a no-op once the audit table is clean.

Why a script and not a data-migration in alembic:
  * Alembic's data migrations live forever in the chain and run on every
    fresh DB upgrade. A backfill is a one-shot — keeping it in alembic
    would replay it every time someone bootstraps a DB from scratch,
    which is conceptually wrong (a fresh DB has no orphans to move).
  * Convention in this repo: schema → alembic, data → scripts/. See
    backfill_rfi_embeddings.py and backfill_dailylog_from_siteeye.py.

Usage
-----
    cd /path/to/aec-platform
    PYTHONPATH=apps/api python -m scripts.backfill_audit_actor_api_key \
      [--dry-run] [-v]

`--dry-run` prints what WOULD change and exits 0 without writing.
Always run with `--dry-run` first against prod.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import text

from db.session import AdminSessionFactory

logger = logging.getLogger("backfill_audit_actor_api_key")


# Two queries:
#
#   1. orphans: audit rows whose `actor_user_id` doesn't resolve to a
#      real user. These are the candidates — every one is either
#      (a) an api-key UUID we want to move, or (b) a user that was
#      hard-deleted (rare; the FK is ON DELETE SET NULL so this should
#      already be NULL, but we're paranoid).
#   2. movable: the subset of orphans whose UUID DOES resolve to an
#      `api_keys.id`. These are the rows we'll UPDATE.
#
# Done in two passes (instead of one nested EXISTS) because we want to
# log the size of each set distinctly so an unexpected (a)/(b) ratio
# is visible in the script output.

_ORPHAN_COUNT_SQL = text(
    """
    SELECT count(*)
    FROM audit_events a
    LEFT JOIN users u ON u.id = a.actor_user_id
    WHERE a.actor_user_id IS NOT NULL
      AND u.id IS NULL
    """
)

_MOVABLE_PREVIEW_SQL = text(
    """
    SELECT a.id          AS audit_id,
           a.actor_user_id AS misplaced_uuid,
           ak.name        AS api_key_name,
           a.action,
           a.created_at
    FROM audit_events a
    JOIN api_keys ak ON ak.id = a.actor_user_id
    LEFT JOIN users u ON u.id = a.actor_user_id
    WHERE a.actor_user_id IS NOT NULL
      AND u.id IS NULL
    ORDER BY a.created_at ASC
    LIMIT 20
    """
)

# UPDATE that does the move. Matched only when the misplaced UUID
# resolves to a real api_keys row — protects against accidentally
# zeroing out audit rows whose `actor_user_id` is junk for some other
# reason (hard-deleted user, manual seed gone wrong, etc.).
_MOVE_SQL = text(
    """
    UPDATE audit_events a
    SET    actor_api_key_id = a.actor_user_id,
           actor_user_id    = NULL
    FROM   api_keys ak
    LEFT JOIN users u ON u.id = a.actor_user_id
    WHERE  ak.id            = a.actor_user_id
      AND  a.actor_user_id IS NOT NULL
      AND  u.id IS NULL
    """
)


async def main(*, dry_run: bool, verbose: bool) -> int:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    async with AdminSessionFactory() as session:
        orphan_total = (await session.execute(_ORPHAN_COUNT_SQL)).scalar_one()
        logger.info(
            "audit rows with actor_user_id not resolving to a user: %d",
            orphan_total,
        )

        if orphan_total == 0:
            logger.info("nothing to backfill — table is already clean.")
            return 0

        # Show a sample of what we'd move (capped at 20). If `movable`
        # is < `orphan_total`, the difference is rows whose UUID
        # doesn't resolve to either users OR api_keys — those are
        # left alone and printed in a separate WARN below.
        sample = (await session.execute(_MOVABLE_PREVIEW_SQL)).mappings().all()
        logger.info("sample of movable rows (up to 20):")
        for r in sample:
            logger.info(
                "  audit=%s  api_key=%s (%s)  action=%s  at=%s",
                r["audit_id"],
                r["misplaced_uuid"],
                r["api_key_name"],
                r["action"],
                r["created_at"].isoformat(),
            )

        if dry_run:
            logger.info("--dry-run set; not writing. Re-run without to apply.")
            return 0

        result = await session.execute(_MOVE_SQL)
        moved = result.rowcount or 0
        await session.commit()
        logger.info("moved %d row(s).", moved)

        # If any orphans remain, those are UUIDs that don't resolve
        # to api_keys either — surface them so an operator can look.
        remaining = (await session.execute(_ORPHAN_COUNT_SQL)).scalar_one()
        if remaining > 0:
            logger.warning(
                "%d orphan row(s) remain — actor_user_id resolves to neither users nor api_keys. Inspect manually.",
                remaining,
            )

    return 0


def _parse_argv(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change and exit without writing.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_argv(sys.argv[1:])
    sys.exit(asyncio.run(main(dry_run=args.dry_run, verbose=args.verbose)))
