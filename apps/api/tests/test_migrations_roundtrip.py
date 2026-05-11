"""Migration round-trip safety net.

Why this exists
---------------
Every alembic revision in `alembic/versions/` ships a `downgrade()`
implementation, but downgrades are almost never exercised — the prod
deploy path is always forward-only. The ones that matter (the one
operators reach for at 2am during a rollback) are the latest few, and
nobody verifies them until the rollback button gets pressed and a
column ends up missing or a CHECK constraint reversed.

This test runs against a real, throwaway Postgres and proves two
things:

  1. **The latest migration round-trips cleanly.** Upgrade to head,
     snapshot the schema, downgrade -1, upgrade +1 back to head,
     snapshot again. The two snapshots must be identical. Catches the
     "downgrade dropped a column the upgrade still needs" bug, the
     "downgrade is empty / `pass`" footgun, and constraint-reversal
     drift.

  2. **The full chain unwinds.** Upgrade head, then downgrade base.
     This is a smoke test that no revision in the chain is a one-way
     door: every `downgrade()` at least executes without raising.
     Doesn't catch wrong-but-runs (covered by #1 for the latest), but
     does catch the much easier-to-merge mistake of a `downgrade()`
     that calls a non-existent helper or references a renamed table.

Why not in CI by default
------------------------
Each round-trip runs the entire migration chain, which on a cold DB
takes 10-30s. The test is `pytest.mark.integration` and gated behind
`--integration` + `MIGRATIONS_TEST_DB_URL` (sync DSN, e.g.
`postgresql://aec:aec@localhost:55432/aec_migrations_test`). Run before
shipping a migration that meaningfully alters columns / constraints,
or quarterly via the same Makefile target as the other integration
suites.

The test ALWAYS targets a freshly-DROPped public schema on the
provided DB — `MIGRATIONS_TEST_DB_URL` MUST point at a throwaway
database, never at a dev DB you care about. The fixture asserts the
db name contains "test" or "migrations" to make foot-shooting harder,
but does not enforce it absolutely (the operator is responsible).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from alembic import command

_DB_URL = os.environ.get("MIGRATIONS_TEST_DB_URL")
_API_ROOT = Path(__file__).resolve().parent.parent

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        _DB_URL is None,
        reason="MIGRATIONS_TEST_DB_URL not set — round-trip test requires a throwaway live DB",
    ),
]


# ---------- alembic config helper ----------


def _alembic_cfg(db_url: str) -> Config:
    """Build a programmatic Config that points at our `alembic/` tree.

    We don't reuse `alembic.ini` directly because it sets
    `sqlalchemy.url` from `DATABASE_URL_SYNC` env. The test wants to
    override that to the throwaway URL without poking at process env
    (env mutation across tests is racy when xdist parallelises).
    """
    cfg = Config(str(_API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


# ---------- schema snapshot ----------
#
# A snapshot is a JSON-serialisable dict of {tables, columns, indexes,
# constraints} read from `information_schema` + `pg_indexes`. It's
# deliberately structural — we don't snapshot row data. The point is
# "did downgrade-then-upgrade leave the schema bit-identical to
# upgrade-from-fresh", and rows would just add noise.


def _snapshot_schema(conn: Connection) -> dict[str, Any]:
    """Capture a deterministic dict of the public-schema structure.

    Sort everything: information_schema row order is undefined, and
    set comparisons would obscure the diff in failure messages.
    """
    tables = [
        r[0]
        for r in conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
        )
    ]

    columns = [
        # Tuple → list so JSON-encodes cleanly. Keep the column type
        # AND nullability + default — a downgrade that drops the
        # default but keeps the column would otherwise look identical.
        list(r)
        for r in conn.execute(
            text(
                """
                SELECT table_name, column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position
                """
            )
        )
    ]

    indexes = [
        list(r)
        for r in conn.execute(
            text(
                """
                SELECT tablename, indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                ORDER BY tablename, indexname
                """
            )
        )
    ]

    constraints = [
        list(r)
        for r in conn.execute(
            text(
                """
                SELECT table_name, constraint_name, constraint_type
                FROM information_schema.table_constraints
                WHERE table_schema = 'public'
                ORDER BY table_name, constraint_name
                """
            )
        )
    ]

    return {
        "tables": tables,
        "columns": columns,
        "indexes": indexes,
        "constraints": constraints,
    }


# ---------- DB lifecycle ----------


@pytest.fixture
def clean_db():
    """Drop + recreate the `public` schema before yielding the URL.

    This is the destructive bit: every test that uses this fixture
    starts from a known-empty schema. The DB itself is NOT dropped or
    created — that's the operator's job (a pre-existing throwaway DB
    is assumed). The schema reset is reversible and idempotent across
    aborted runs.
    """
    assert _DB_URL is not None
    # Soft guard against pointing at a real DB. Not foolproof; the
    # operator is responsible for the env var. The substring check
    # covers `aec_test`, `migrations_test`, etc.
    if not any(s in _DB_URL.lower() for s in ("test", "migrations", "scratch")):
        pytest.fail(
            "MIGRATIONS_TEST_DB_URL must point at a throwaway DB "
            "(name should contain 'test' or 'migrations'); refusing to drop schema."
        )

    engine = create_engine(_DB_URL, future=True, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    yield _DB_URL


# ---------- Tests ----------


def test_latest_migration_downgrade_upgrade_is_identity(clean_db):
    """upgrade head → downgrade -1 → upgrade head → schema unchanged.

    Targets the most-recent migration's `downgrade()` specifically —
    the one a rollback at 2am would invoke. Schema diff (not just
    "did it run") because a no-op `downgrade()` would pass the smoke
    test in the next test but leak rows / constraints across rollback.
    """
    cfg = _alembic_cfg(clean_db)
    command.upgrade(cfg, "head")

    engine = create_engine(clean_db, future=True)
    with engine.connect() as conn:
        before = _snapshot_schema(conn)
    engine.dispose()

    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "+1")

    engine = create_engine(clean_db, future=True)
    with engine.connect() as conn:
        after = _snapshot_schema(conn)
    engine.dispose()

    if before != after:
        # Print a focused diff before pytest's full-dict spew. Most of
        # the time the regression is one column / index — surface that.
        diff_lines: list[str] = []
        for key in ("tables", "columns", "indexes", "constraints"):
            removed = [x for x in before[key] if x not in after[key]]
            added = [x for x in after[key] if x not in before[key]]
            if removed:
                diff_lines.append(f"  {key}: removed by round-trip: {removed[:5]}")
            if added:
                diff_lines.append(f"  {key}: added by round-trip:   {added[:5]}")
        pytest.fail(
            "Schema drift after downgrade -1 / upgrade +1.\n"
            "The latest migration's downgrade() does not invert its upgrade():\n"
            + "\n".join(diff_lines or ["  (full snapshots differ; see -vv)"])
            + f"\n\nFull before: {json.dumps(before, default=str)[:500]}..."
        )


def test_full_chain_unwinds_to_base(clean_db):
    """upgrade head → downgrade base.

    Smoke test only: every `downgrade()` in the chain must at least
    execute. A revision whose downgrade references a renamed helper
    or a table dropped by a later revision will raise here. We don't
    snapshot — the schema at base is empty (or close to it), so the
    informative signal is "did it raise". A passing run leaves the
    schema empty for the next test that pulls `clean_db`.
    """
    cfg = _alembic_cfg(clean_db)
    command.upgrade(cfg, "head")
    # Will raise if any single downgrade in the chain trips.
    command.downgrade(cfg, "base")

    # Belt-and-suspenders: if a downgrade silently no-op'd while
    # leaving objects behind, this catches it. We don't enforce a
    # strict "0 tables" because alembic's own `alembic_version` row
    # in the alembic_version table stays — but no app tables should.
    engine = create_engine(clean_db, future=True)
    with engine.connect() as conn:
        leftover = [
            r[0]
            for r in conn.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_type  = 'BASE TABLE'
                      AND table_name <> 'alembic_version'
                    ORDER BY table_name
                    """
                )
            )
        ]
    engine.dispose()

    assert leftover == [], (
        f"Downgrading to base left {len(leftover)} app tables behind: "
        f"{leftover[:10]}. Some `downgrade()` in the chain isn't dropping "
        "what its `upgrade()` created."
    )
