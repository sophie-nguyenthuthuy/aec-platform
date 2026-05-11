"""merge: idempotency_records + slack_deliveries

Two parallel feature branches both forked off 0036_scraper_runs and
landed independently as `0037_idempotency_records` and
`0037_slack_deliveries`. Neither touches the other's tables, so the
merge is a structural no-op — but alembic refuses to upgrade a multi-
head chain, so we need an explicit revision that names both as
parents to make `head` unambiguous again.

This revision was caught by `tests/test_migrations_static.py`
(`test_revision_chain_has_exactly_one_head`); landing it green is the
whole reason the test exists.
"""

from __future__ import annotations

# Alembic identifiers.
revision = "0038_merge_idempotency_slack"
down_revision = ("0037_idempotency_records", "0037_slack_deliveries")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: this revision exists only to merge the two parents.

    Adding schema changes here would couple two unrelated features'
    rollback behaviour together — keep it strictly empty.
    """
    pass


def downgrade() -> None:
    """No-op (mirror of upgrade)."""
    pass
