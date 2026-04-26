"""assistant_threads + assistant_messages — persistent AI chat history

Today the assistant is fully stateless: the client manages chat history
in component state and replays it on each turn. That works but loses
conversations when the panel closes, blocks "recent threads" UI, and
gives ops zero audit trail when debugging hallucinations.

This migration adds:

  * `assistant_threads` — one row per conversation, scoped to (org,
    project, user). The title is auto-derived from the first user
    question (truncated to 80 chars) so the sidebar can render
    meaningful labels without joining to messages.

  * `assistant_messages` — the replayable transcript. `sources` carries
    the typed citations the assistant emitted; `tool_calls` is a
    forward-compat slot for the tool-use loop landing in the next pass.

Indexes:

  * `(user_id, project_id, last_message_at DESC)` on threads — drives
    the "recent conversations for this user/project" sidebar.
  * `(thread_id, created_at)` on messages — the replay query.

Both tables carry RLS via `organization_id` (threads) and via the FK to
threads (messages — RLS on `assistant_threads` plus the cascade FK is
sufficient; messages don't need their own org column because every
read goes through a thread anyway).

Revision ID: 0016_assistant_threads
Revises: 0015_changeorder
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0016_assistant_threads"
down_revision = "0015_changeorder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_threads",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("last_message_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_assistant_threads_user_project_recent",
        "assistant_threads",
        ["user_id", "project_id", sa.text("last_message_at DESC")],
    )
    op.execute("ALTER TABLE assistant_threads ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_assistant_threads
            ON assistant_threads
            USING (organization_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    op.create_table(
        "assistant_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assistant_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "sources",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "tool_calls",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("context_token_estimate", sa.Integer),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_assistant_messages_role"),
    )
    op.create_index(
        "ix_assistant_messages_thread_created",
        "assistant_messages",
        ["thread_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_thread_created", table_name="assistant_messages")
    op.drop_table("assistant_messages")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_assistant_threads ON assistant_threads"
    )
    op.drop_index(
        "ix_assistant_threads_user_project_recent", table_name="assistant_threads"
    )
    op.drop_table("assistant_threads")
