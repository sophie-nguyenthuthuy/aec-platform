"""audit_events.actor_api_key_id — track api-key actors distinctly

Before this migration, `audit_events.actor_user_id` carried *whichever*
UUID the auth layer surfaced as `auth.user_id`. For api-key callers
that's the `api_keys.id`, which the FK to `users.id` rejects — so any
api-key-driven mutation that tried to emit an audit row failed with a
foreign-key violation. Even where it didn't fail, the read endpoint's
`LEFT JOIN users` left api-key actors as anonymous "system" rows in
the admin UI.

Add a parallel `actor_api_key_id` column with its own FK to
`api_keys.id`. Convention (not a CHECK) is that exactly one of
`actor_user_id` / `actor_api_key_id` is non-NULL on any row; system /
cron events leave both NULL. A CHECK would have to also accept the
both-NULL case and would buy us little over the call-site contract in
`services.audit.record(...)`.

`ON DELETE SET NULL` matches the user-actor column: revoking and then
purging an api key (rare, but possible for a key minted in error)
shouldn't cascade-delete its audit history.

Branched off 0032_api_key_calls in parallel with 0033_api_keys_mode;
the 0034_merge_api_key_branches migration converges both 0033 heads.

Revision ID: 0033_audit_actor_api_key
Revises: 0032_api_key_calls
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0033_audit_actor_api_key"
down_revision = "0032_api_key_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column(
            "actor_api_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("audit_events", "actor_api_key_id")
