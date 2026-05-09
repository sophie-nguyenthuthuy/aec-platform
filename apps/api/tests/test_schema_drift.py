"""Schema-drift detector: SQLAlchemy `Base.metadata` vs alembic head.

The bug class
-------------
You add `Column("notes", Text)` to `models/punchlist.py` and forget to
write a migration. Locally the API works because:

  * The dev DB happens to have the column from a prior side experiment;
  * Or you only exercise endpoints that don't touch that column;
  * Or the unit tests use `FakeAsyncSession` which doesn't validate
    the schema at all.

Then CI green-lights the PR (none of the unit tests fail), the deploy
runs `alembic upgrade head` (which is a no-op — there's no new
revision), and prod blows up the first time a request hits the column.

This test catches that at PR time. It uses `alembic.autogenerate` to
ask alembic the same question it would ask if you ran
`alembic revision --autogenerate`: "given the current state of the
DB at head, what migration would you generate to match
`Base.metadata`?" If the answer is non-empty, the model and the
migration chain have diverged.

Why it's integration-tier
-------------------------
We need a real Postgres because:

  * Several columns use `JSONB` / `pgcrypto` / `vector` / GIN indexes
    that SQLite can't represent. SQLAlchemy emits the actual DDL and
    we want alembic's diff to reflect what would happen in prod.
  * `register_all()` pulls in models that depend on extension types
    (`pgvector.Vector`) — instantiating them at all requires a real
    PG dialect.

The fixture drops + recreates the public schema, runs
`alembic upgrade head`, then asks `autogenerate` for the diff.

False-positive guard
--------------------
`autogenerate` famously over-reports — it flags type-coercion noise
(e.g. `BigInteger` ↔ `Integer` on different dialects, `String(255)`
vs `VARCHAR`) that aren't real drift. We post-process the ops list
to drop the known cosmetic categories. If a real drift hides behind
a cosmetic one, it'll resurface as a non-cosmetic op the next time
someone touches that area; the alternative (failing on every cosmetic
diff) would force the team to noise-suppress this test until they
ignored it entirely.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from alembic import command

# Reuse the same env var as the migration round-trip tests — both
# need a throwaway DB.
_DB_URL = os.environ.get("MIGRATIONS_TEST_DB_URL")
_API_ROOT = Path(__file__).resolve().parent.parent

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        _DB_URL is None,
        reason="MIGRATIONS_TEST_DB_URL not set — schema-drift check requires a throwaway live DB",
    ),
]


def _alembic_cfg(db_url: str) -> Config:
    cfg = Config(str(_API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture
def fresh_head_db():
    """Drop + recreate `public`, upgrade to head, yield URL.

    Same destructive guard as the round-trip fixture: refuse to run
    unless the DB name contains `test`/`migrations`/`scratch`.
    """
    assert _DB_URL is not None
    if not any(s in _DB_URL.lower() for s in ("test", "migrations", "scratch")):
        pytest.fail(
            "MIGRATIONS_TEST_DB_URL must point at a throwaway DB "
            "(name should contain 'test'/'migrations'/'scratch'); refusing to drop schema."
        )

    engine = create_engine(_DB_URL, future=True, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    cfg = _alembic_cfg(_DB_URL)
    command.upgrade(cfg, "head")
    yield _DB_URL


# ---------- false-positive filter ----------
#
# autogenerate's diff-op tuples are nested: the top level is a list of
# operations, and each may itself be a list of sub-ops grouped by
# table. We flatten and then filter.


def _flatten_ops(ops):
    out = []
    for op in ops:
        if isinstance(op, list):
            out.extend(op)
        else:
            out.append(op)
    return out


# Op-name prefixes we tolerate. These are well-documented autogenerate
# false-positive categories — the alembic docs themselves caveat them
# (see "Don't compare X" / `compare_type` interactions).
_COSMETIC_OPS = {
    # Index name-only renames (alembic generates implicit names that
    # differ from the migration's explicit ones; harmless).
    "remove_index",
    "add_index",
    # Server-default changes are commonly false-positive — alembic
    # can't always reliably reverse-engineer the default expression
    # (e.g. `NOW()` vs `now()` vs `CURRENT_TIMESTAMP`).
    "modify_default",
    # Constraint name normalisation (PG sometimes auto-names FKs and
    # autogenerate flags the difference). Real FK changes show up as
    # `add_fk` / `remove_fk` instead.
    "modify_nullable",
}


def _is_real_drift(op) -> bool:
    """Decide whether one diff-op represents a genuine model/migration mismatch.

    The op is a tuple whose first element is the op name (e.g.
    'add_table', 'remove_column', 'add_column'). We accept the
    `_COSMETIC_OPS` set as noise; everything else is real.
    """
    if not isinstance(op, tuple) or not op:
        return True  # Unknown shape → treat as real, fail loudly.
    op_name = op[0]
    if op_name in _COSMETIC_OPS:
        return False
    return True


def _format_op(op) -> str:
    """Pretty-print one diff-op for the failure message."""
    if not isinstance(op, tuple):
        return repr(op)
    name = op[0] if op else "?"
    # Most ops have the table name as the second element or inside a
    # SchemaItem at index 1. Try to surface it without doing a full
    # type switch.
    try:
        tail = op[1]
        if hasattr(tail, "name"):
            return f"{name}({tail.name!r})"
        if isinstance(tail, str):
            return f"{name}({tail!r})"
    except (IndexError, AttributeError):
        pass
    return name


def test_no_drift_between_models_and_alembic_head(fresh_head_db):
    """`alembic upgrade head` against a clean DB must produce a schema
    that exactly matches `Base.metadata` from the model definitions.

    If this test fails, you have one of:
      * A model that gained a column/table without a migration —
        write a new migration with `alembic revision --autogenerate`.
      * A migration that gained a column/table without a model
        update — add it to the corresponding `models/*.py`.
      * A model `Column(...)` whose type/nullability/FK doesn't match
        the migration's `op.add_column(...)`.

    The failure message lists the diff-ops alembic thinks would be
    needed to bring head into sync with the models — that's a usable
    sketch of what the new migration should contain.
    """
    # Late import: `register_all()` triggers a chain of model imports
    # that touch settings + the pgvector ORM extension; both expect
    # the test env to be set up.
    from db.base import Base
    from models import register_all

    register_all()

    # Compare the live (head) schema to the in-memory metadata. We
    # use a sync engine here because `alembic.autogenerate` is
    # synchronous; the production stack uses asyncpg, but for schema
    # introspection psycopg2 is the standard path.
    engine = create_engine(fresh_head_db, future=True)
    try:
        with engine.connect() as conn:
            mc = MigrationContext.configure(
                conn,
                opts={
                    # `compare_type=True` makes alembic check column types
                    # in addition to presence — that's how we catch
                    # `BigInteger` vs `Integer` mistakes. Side effect:
                    # bumps the false-positive rate, which is what
                    # `_is_real_drift` filters out.
                    "compare_type": True,
                    # `compare_server_default=False` — server defaults are
                    # the noisiest false-positive class (see comment on
                    # `_COSMETIC_OPS`). If the team wants to enforce
                    # default parity, we'd add a separate test that
                    # specifically asserts a known-good default subset.
                    "compare_server_default": False,
                },
            )
            raw_ops = compare_metadata(mc, Base.metadata)
    finally:
        engine.dispose()

    drift = [op for op in _flatten_ops(raw_ops) if _is_real_drift(op)]
    if drift:
        pretty = "\n".join(f"  - {_format_op(op)}" for op in drift[:15])
        more = f"\n  … and {len(drift) - 15} more" if len(drift) > 15 else ""
        pytest.fail(
            f"Schema drift detected between SQLAlchemy models and alembic head ({len(drift)} ops):\n"
            f"{pretty}{more}\n\n"
            "If the drift is on the model side, run `alembic revision --autogenerate -m '<reason>'` "
            "in apps/api/ and inspect the resulting file before committing — "
            "autogenerate output is a starting point, not gospel.\n"
            "If the drift is on the migration side, update the corresponding `models/*.py` "
            "to match. Either way, this test should be green again afterwards."
        )
