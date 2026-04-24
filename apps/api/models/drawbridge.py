"""SQLAlchemy models for DRAWBRIDGE module (documents, chunks, conflicts, RFIs)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class DocumentSet(Base):
    __tablename__ = "document_sets"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    discipline: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[str | None] = mapped_column(Text)
    issued_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column()


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    document_set_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_sets.id", ondelete="SET NULL")
    )
    file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL")
    )
    doc_type: Mapped[str | None] = mapped_column(Text)
    drawing_number: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[str | None] = mapped_column(Text)
    discipline: Mapped[str | None] = mapped_column(Text)
    scale: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str] = mapped_column(Text, default="pending")
    extracted_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column()


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    chunk_type: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # embedding vector(3072) — managed via raw SQL to avoid hard pgvector import at model load.


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(Text, default="open")
    severity: Mapped[str | None] = mapped_column(Text)
    conflict_type: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    document_a_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    chunk_a_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL")
    )
    document_b_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    chunk_b_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL")
    )
    ai_explanation: Mapped[str | None] = mapped_column(Text)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column()
    resolved_at: Mapped[datetime | None] = mapped_column()
    resolved_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class Rfi(Base):
    __tablename__ = "rfis"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    number: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open")
    priority: Mapped[str] = mapped_column(Text, default="normal")
    related_document_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), default=list
    )
    raised_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_to: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column()
