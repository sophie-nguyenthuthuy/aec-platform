"""Schemas for the cross-module AI assistant."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    thread_id: UUID | None = Field(
        default=None,
        description="When provided, the question is appended to this thread "
        "and prior messages are hydrated from the DB. When omitted, a new "
        "thread is auto-created (titled from the first ~80 chars of the "
        "question).",
    )
    # Legacy slot — clients that pre-date thread persistence pass history
    # in the body. Ignored when `thread_id` is set (the DB is authoritative).
    history: list[ChatTurn] = Field(
        default_factory=list,
        max_length=20,
        description="DEPRECATED. Pre-thread clients pass prior turns here. "
        "When `thread_id` is provided, history is loaded from the DB and "
        "this field is ignored.",
    )


class AssistantSource(BaseModel):
    """A pointer to a module/route the assistant drew from. The frontend
    renders these as clickable citations under the answer."""

    module: str  # "pulse" / "siteeye" / "handover" / etc.
    label: str
    route: str | None = None  # optional in-app route, e.g. /pulse/{id}/change-orders


class AssistantResponse(BaseModel):
    project_id: UUID
    thread_id: UUID | None = Field(
        default=None,
        description="ID of the thread this turn was appended to. Clients should round-trip this on follow-up turns.",
    )
    answer: str
    sources: list[AssistantSource] = Field(default_factory=list)
    context_token_estimate: int = Field(
        default=0,
        description="Rough token count of the project context fed to the LLM. "
        "Lets ops see how heavy a request was without parsing logs.",
    )


# ---------- Thread CRUD shapes ----------


class ThreadSummary(BaseModel):
    """Sidebar-friendly projection: enough to render a list of threads
    without joining to messages."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    title: str
    last_message_at: datetime
    created_at: datetime


class ThreadMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    sources: list[AssistantSource] = Field(default_factory=list)
    created_at: datetime


class ThreadDetail(ThreadSummary):
    """Full thread with messages, returned by `GET /threads/{id}`."""

    messages: list[ThreadMessage] = Field(default_factory=list)
