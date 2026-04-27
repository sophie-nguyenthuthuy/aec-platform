"""invitations — admin-issued tokens that let a new user join an existing org

The dev user is currently the only seed; everyone else has to be added
via the Supabase admin API + a manual SQL insert into `org_members`.
This is fine for a single-tenant smoke but blocks any real customer
demo where a project owner needs to invite a contractor.

Flow:
  1. An owner/admin POSTs `/api/v1/orgs/{id}/invitations` with the
     invitee's email + role. The api inserts a row in this table with
     a one-time `token` (UUID), an `expires_at` 7 days out, and the
     inviter's user_id.
  2. The api returns the accept URL `${PUBLIC_WEB_URL}/invite/{token}`.
     In dev the admin copies it manually; in prod a follow-up SMTP
     integration will email the link.
  3. The invitee opens the link, sets a password, and POSTs
     `/api/v1/invitations/{token}/accept`. The api creates the Supabase
     user via the admin API, inserts a `users` + `org_members` row,
     stamps `accepted_at`, and returns 204.

Tokens are single-use: `accepted_at IS NOT NULL` rejects further accept
calls. RLS scopes reads to the inviter's org; the public accept endpoint
uses `AdminSessionFactory` to bypass RLS so an anonymous request can
look up its own invitation row.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_invitations"
down_revision = "0016_assistant_threads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column(
            "token",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "expires_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW() + INTERVAL '7 days'"),
        ),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_invitations_org_email", "invitations", ["organization_id", "email"]
    )
    # Token lookups are the hot path for the accept endpoint.
    op.create_index("ix_invitations_token", "invitations", ["token"])

    # RLS — admin reads only see their own org's invitations. The accept
    # path bypasses RLS via AdminSessionFactory.
    op.execute("ALTER TABLE invitations ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY invitations_org_isolation ON invitations
          FOR ALL
          USING (organization_id::text = current_setting('app.current_org_id', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invitations CASCADE")
