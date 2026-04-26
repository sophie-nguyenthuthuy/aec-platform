"""ORM models for the cross-module AI assistant.

Two tables: `assistant_threads` (one row per conversation, scoped to a
user + project + org) and `assistant_messages` (the replayable transcript).

The assistant itself remains stateless on the wire — the client sends a
thread_id and we hydrate prior turns from `assistant_messages` rather
than trusting a chat log the client managed in memory. That gives us:

  * Resumable conversations across browsers / devices.
  * A server-side audit trail (helpful when debugging hallucinations).
  * The ability to render a "Recent threads" sidebar without the client
    having to hold all of history in localStorage.

`(thread_id, created_at)` covers the message-replay query; threads are
indexed by `(user_id, project_id, last_message_at DESC)` for the
"recent threads I care about" sidebar query.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from models.core import TZ  # type: ignore[attr-defined]


class AssistantThread(Base):
    """One conversation between a user and the assistant about a project."""

    __tablename__ = "assistant_threads"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Auto-derived from the first user question (`text[:80]`). Lets the
    # sidebar render a meaningful label without re-querying the first
    # message every time.
    title: Mapped[str] = mapped_column(Text, nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class AssistantMessage(Base):
    """One message in a thread — either user prompt or assistant reply.

    `sources` carries the typed citations the assistant emitted with its
    answer (module + label + optional in-app route); `tool_calls` is a
    placeholder for the upcoming tool-use loop where a single assistant
    turn may invoke multiple tools before producing the final answer.
    """

    __tablename__ = "assistant_messages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assistant_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    tool_calls: Mapped[list] = mapped_column(JSONB, default=list)
    context_token_estimate: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
