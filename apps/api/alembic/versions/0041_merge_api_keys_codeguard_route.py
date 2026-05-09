"""merge: api_keys.project_ids + codeguard_user_usage_by_route

Two parallel feature branches both forked off `0033_audit_actor_api_key`
and landed independently:

  * `0039_api_keys_project_ids` — added `project_ids` column to
    `api_keys` (descends through 0034 → 0035 → … → 0038 → 0039).
  * `0040_codeguard_user_usage_route` — added a per-route breakdown
    column to `codeguard_user_usage` (branched directly off 0033, so
    its lineage is `0033 → 0040`).

Neither touches the other's tables, so the merge is a structural
no-op — but alembic refuses to upgrade a multi-head chain, so we
need an explicit revision that names both as parents to make `head`
unambiguous again.

Same shape as `0038_merge_idempotency_slack` and
`0034_merge_api_key_branches`. Caught by
`tests/test_migrations_static.py::test_revision_chain_has_exactly_one_head`;
landing this green is the whole reason that test exists.
"""

from __future__ import annotations

# Alembic identifiers.
revision = "0041_merge_api_keys_codeguard_route"
down_revision = (
    "0039_api_keys_project_ids",
    "0040_codeguard_user_usage_route",
)
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
