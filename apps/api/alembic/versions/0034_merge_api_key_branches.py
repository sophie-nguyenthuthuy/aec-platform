"""merge 0033 api-key branches

Two parallel features landed at revision 0033 and never converged:

  * 0033_api_keys_mode      — adds `mode` column to api_keys
  * 0033_audit_actor_api_key — adds `actor_api_key_id` column to audit_events

Both descend from 0032_api_key_calls and have the same down_revision.
The CI gate (`alembic heads | grep -c '(head)' = 1`) was failing on
this branch state. This migration is a pure merge — no DDL — to
re-converge the chain so subsequent migrations have a single head
to descend from.

Rationale for pure merge (vs. merge + schema change in one): merge
migrations are conventionally side-effect free so a fresh DB
upgrading through the chain doesn't have to reason about whether
the merge step itself introduces drift. The next migration in the
chain (per-user usage attribution) does the actual schema work.

Revision ID: 0034_merge_api_key_branches
Revises: 0033_api_keys_mode, 0033_audit_actor_api_key
Create Date: 2026-05-02
"""

from __future__ import annotations

# Revision name is under the 32-char `alembic_version.version_num`
# limit. `0034_merge_api_key_branches` is exactly 28 chars.
revision = "0034_merge_api_key_branches"
# Tuple of down-revs is the alembic convention for a merge node — both
# parents must exist in the DB before this migration can apply.
down_revision = ("0033_api_keys_mode", "0033_audit_actor_api_key")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Pure merge — no DDL. The whole point of this revision is to give
    # alembic a single node both 0033 branches collapse into.
    pass


def downgrade() -> None:
    # Symmetric no-op. Downgrading past the merge point reverts to the
    # branched state (alembic re-exposes both 0033 heads).
    pass
