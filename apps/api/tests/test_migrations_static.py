"""Static checks against the alembic revision tree.

These don't need a live DB, so they run in the normal CI lane (no
`--integration` flag, no `MIGRATIONS_TEST_DB_URL` env). The companion
file `test_migrations_roundtrip.py` covers the integration-tier
upgrade/downgrade verification that does.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_API_ROOT = Path(__file__).resolve().parent.parent


def test_revision_chain_has_exactly_one_head() -> None:
    """Two heads at once is almost always accidental.

    Most often it's two feature branches that each ran
    `alembic revision --autogenerate` against main without rebasing.
    Detached heads ship as a quiet "Multiple head revisions are
    present" runtime error in `alembic upgrade head` — caught here
    at the static layer instead.

    We legitimately have merge revisions in the tree (see
    `0034_merge_api_key_branches.py`, `ceff072b3343_merge_*`), so the
    contract is "exactly one head", not "zero merges". When this
    test fails, resolve by running:

        alembic merge -m "merge: <reason>" <head1> <head2>

    and committing the resulting merge revision.
    """
    cfg = Config(str(_API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_API_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, (
        f"Expected exactly one alembic head, found {len(heads)}: {heads}. "
        "Resolve by running `alembic merge -m 'merge X' <head1> <head2>`."
    )


def test_every_revision_has_both_upgrade_and_downgrade() -> None:
    """Every revision file must define `upgrade()` AND `downgrade()`.

    A `downgrade()` body of `pass` is allowed (we don't introspect
    AST contents — the integration round-trip test is what catches
    "downgrade is wrong"); but the FUNCTION must exist. A revision
    that ships without `def downgrade()` will crash alembic at
    rollback time with a misleading AttributeError. Catch it at the
    earliest possible layer.
    """
    cfg = Config(str(_API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_API_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)

    missing: list[str] = []
    for rev in script.walk_revisions():
        # `module` here is the loaded revision module — alembic has
        # already imported it. We just check the two callables exist.
        mod = rev.module
        if not callable(getattr(mod, "upgrade", None)):
            missing.append(f"{rev.revision}: no upgrade()")
        if not callable(getattr(mod, "downgrade", None)):
            missing.append(f"{rev.revision}: no downgrade()")

    assert missing == [], "Revisions missing required callables:\n" + "\n".join(missing)
