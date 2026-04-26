"""RFI/Submittals — formal contractor submissions + AI augmentation of existing
DrawBridge RFIs (similar-RFI search, grounded auto-draft responses).

Three concerns, four tables:

  1. Submittals (workflow): a *contractor* submits shop drawings, samples,
     product data, mockups or certificates for design-team review. Lives
     adjacent to drawbridge.documents but is not the same: documents are
     drawing/spec deliverables produced by the design team, submittals are
     proposed *materials/products* coming back from the field for approval.
       * `submittals` — one per submittal package (numbered like S-001).
       * `submittal_revisions` — every cycle of "revise & resubmit" lives
         here so we keep the lineage. The submittal's `current_revision`
         points at the latest one.

  2. RFI similarity index: a per-RFI embedding so a fresh question can find
     the most relevant past RFIs ("we already answered this in RFI-042").
       * `rfi_embeddings` — vector(3072) column managed in raw SQL inside
         the migration (mirrors `document_chunks.embedding`); the ORM
         layer treats it as opaque so we don't need pgvector at import time.

  3. AI response drafts: when a designer asks the system for an answer, we
     run a RAG pipeline over the project's drawing chunks and produce a
     draft + citations. Persisted so the user can edit, accept, or reject.
       * `rfi_response_drafts` — one row per generation; `accepted_at`
         flips when the user promotes the draft to the RFI's `response`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


# ---------- Submittals ----------


class Submittal(Base):
    __tablename__ = "submittals"

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
    # Package number (S-001) — unique per project.
    package_number: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # shop_drawing | sample | product_data | mock_up | certificate | other
    submittal_type: Mapped[str] = mapped_column(Text, nullable=False, default="shop_drawing")
    # CSI MasterFormat division (e.g. "03 30 00") for filtering.
    spec_section: Mapped[str | None] = mapped_column(Text)
    csi_division: Mapped[str | None] = mapped_column(Text)
    # pending_review | under_review | approved | approved_as_noted | revise_resubmit | rejected | superseded
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending_review")
    # Index of the latest revision (1-based).
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # designer | contractor | unassigned
    ball_in_court: Mapped[str] = mapped_column(Text, nullable=False, default="designer")
    contractor_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    due_date: Mapped[date | None] = mapped_column(Date)
    submitted_at: Mapped[datetime | None] = mapped_column(TZ)
    closed_at: Mapped[datetime | None] = mapped_column(TZ)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class SubmittalRevision(Base):
    __tablename__ = "submittal_revisions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    submittal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("submittals.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"))
    # pending_review | approved | approved_as_noted | revise_resubmit | rejected
    review_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending_review")
    reviewer_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(TZ)
    reviewer_notes: Mapped[str | None] = mapped_column(Text)
    # Free-form annotations (markup coordinates, comments) attached to the rev.
    annotations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


# ---------- RFI augmentation ----------


class RfiEmbedding(Base):
    """One vector per RFI. The actual `embedding vector(3072)` column lives on
    the same table but is managed via raw SQL in the migration to avoid a
    hard dependency on pgvector at ORM-import time. The ORM treats it as
    metadata-only and uses raw `text()` queries for similarity search.
    """

    __tablename__ = "rfi_embeddings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    rfi_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("rfis.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    # NB: `embedding vector(3072)` lives here in the DB but is NOT mapped
    # on this ORM class — see the migration for how it's added.
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class RfiResponseDraft(Base):
    """LLM-drafted response for an RFI, with grounded citations to drawing/spec
    chunks. The user can edit and `accepted_at` flips when they promote it
    to the RFI's `response` column."""

    __tablename__ = "rfi_response_drafts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    rfi_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("rfis.id", ondelete="CASCADE"),
        nullable=False,
    )
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    # [{document_id, page_number, chunk_id, snippet, drawing_number?}]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(TZ)
    accepted_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
