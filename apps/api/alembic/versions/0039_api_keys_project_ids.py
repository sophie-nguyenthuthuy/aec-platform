"""api_keys.project_ids — per-project scope allowlist

Today an api-key with `projects:read` can see every project in the
org. A partner integrating with a single project (e.g. a vendor
building a tower-A site-eye dashboard) shouldn't have access to
tower B. Industry pattern: per-project allowlist on the key.

Schema rationale:

  * **`UUID[]` not a join table.** An api-key with no scope
    restriction has `project_ids = ARRAY[]::uuid[]` — empty array =
    "all projects" (back-compat: every existing key keeps full
    org-wide access). A non-empty array means "ONLY these projects."
    Storing as a column avoids a join on every authenticated
    request.

  * **`DEFAULT ARRAY[]::uuid[]`.** Existing rows get the empty array
    and continue working. New keys default to "all projects" too;
    the partner explicitly opts into project-scoping at mint time.

  * **No FK enforcement.** Postgres doesn't support FK constraints
    on array elements without a trigger. Stale UUIDs (project
    deleted) become inert: the access check `project_id = ANY(scope)`
    just evaluates to `false` for the deleted id. Cheaper than
    cascading the delete; lets us drop the trigger.

  * **No index.** The column is read on the hot path (every
    authenticated request) but the row lookup is by `hash` (the
    auth path's existing partial unique index). Once the row is in
    memory, `ANY()` against an in-memory array is microseconds.

Revision ID: 0039_api_keys_project_ids
Revises: 0038_merge_idempotency_slack
Create Date: 2026-05-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0039_api_keys_project_ids"
# `0038_merge_idempotency_slack` is the sole pre-existing head:
# 0033_audit_actor_api_key was branched off 0032_api_key_calls and
# already merged via 0034_merge_api_key_branches, which feeds the
# linear chain that 0038 descends from. Earlier versions of this
# file listed `0038_audit_actor_api_key` as a second parent — that
# revision name doesn't exist (the actual file is 0033) and the
# resulting `KeyError` broke `alembic heads` / migrations_static
# tests for everyone.
down_revision = "0038_merge_idempotency_slack"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "project_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "project_ids")
