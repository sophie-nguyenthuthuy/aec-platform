"""Pydantic schemas for the RFI/Submittals module.

Two halves:
  * Submittals workflow — Pydantic mirrors of the new tables.
  * RFI AI — request/response payloads for the similar-search and
    grounded-draft endpoints (no DB-row mirror needed for those because
    the input is `rfi_id`).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Submittals enums ----------


class SubmittalType(StrEnum):
    shop_drawing = "shop_drawing"
    sample = "sample"
    product_data = "product_data"
    mock_up = "mock_up"
    certificate = "certificate"
    other = "other"


class SubmittalStatus(StrEnum):
    pending_review = "pending_review"
    under_review = "under_review"
    approved = "approved"
    approved_as_noted = "approved_as_noted"
    revise_resubmit = "revise_resubmit"
    rejected = "rejected"
    superseded = "superseded"


class BallInCourt(StrEnum):
    designer = "designer"
    contractor = "contractor"
    unassigned = "unassigned"


class RevisionStatus(StrEnum):
    pending_review = "pending_review"
    approved = "approved"
    approved_as_noted = "approved_as_noted"
    revise_resubmit = "revise_resubmit"
    rejected = "rejected"


# ---------- Submittals payloads ----------


class SubmittalCreate(BaseModel):
    project_id: UUID
    package_number: str | None = None  # auto-assigned if omitted
    title: str
    description: str | None = None
    submittal_type: SubmittalType = SubmittalType.shop_drawing
    spec_section: str | None = None
    csi_division: str | None = None
    contractor_id: UUID | None = None
    due_date: date | None = None
    notes: str | None = None
    file_id: UUID | None = None  # convenience: also seeds first revision


class SubmittalUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    submittal_type: SubmittalType | None = None
    spec_section: str | None = None
    csi_division: str | None = None
    status: SubmittalStatus | None = None
    ball_in_court: BallInCourt | None = None
    contractor_id: UUID | None = None
    due_date: date | None = None
    notes: str | None = None


class Submittal(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    package_number: str
    title: str
    description: str | None = None
    submittal_type: SubmittalType | str
    spec_section: str | None = None
    csi_division: str | None = None
    status: SubmittalStatus | str
    current_revision: int
    ball_in_court: BallInCourt | str
    contractor_id: UUID | None = None
    submitted_by: UUID | None = None
    due_date: date | None = None
    submitted_at: datetime | None = None
    closed_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class SubmittalRevisionCreate(BaseModel):
    file_id: UUID | None = None
    annotations: list[dict[str, Any]] = Field(default_factory=list)


class SubmittalRevisionReview(BaseModel):
    review_status: RevisionStatus
    reviewer_notes: str | None = None
    annotations: list[dict[str, Any]] | None = None


class SubmittalRevision(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    submittal_id: UUID
    revision_number: int
    file_id: UUID | None = None
    review_status: RevisionStatus | str
    reviewer_id: UUID | None = None
    reviewed_at: datetime | None = None
    reviewer_notes: str | None = None
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class SubmittalDetail(BaseModel):
    submittal: Submittal
    revisions: list[SubmittalRevision] = Field(default_factory=list)


# ---------- RFI AI ----------


class RfiSimilarRequest(BaseModel):
    """Trigger params for the similarity-search endpoint."""

    limit: int = Field(default=5, ge=1, le=20)
    # Cosine-distance ceiling — `<=>` returns 0 = identical, 2 = opposite.
    # 0.5 = "moderately similar" by default.
    max_distance: float = Field(default=0.5, ge=0, le=2)


class SimilarRfi(BaseModel):
    rfi_id: UUID
    number: str | None = None
    subject: str
    status: str
    distance: float  # cosine; lower = closer
    created_at: datetime


class RfiSimilarResponse(BaseModel):
    source_rfi_id: UUID
    results: list[SimilarRfi] = Field(default_factory=list)
    embedding_model: str | None = None


class RfiCitation(BaseModel):
    document_id: UUID
    chunk_id: UUID
    page_number: int | None = None
    snippet: str
    drawing_number: str | None = None
    discipline: str | None = None


class RfiDraftRequest(BaseModel):
    """Trigger params for POST /rfis/{id}/draft."""

    # Re-use an existing draft if generated < `cache_minutes` ago.
    cache_minutes: int = Field(default=60, ge=0, le=1440)
    # Number of drawing/spec chunks to retrieve as grounding context.
    retrieval_k: int = Field(default=6, ge=1, le=20)


class RfiResponseDraft(BaseModel):
    # `model_version` collides with Pydantic's protected namespace.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: UUID
    organization_id: UUID
    rfi_id: UUID
    draft_text: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    model_version: str
    generated_at: datetime
    accepted_at: datetime | None = None
    accepted_by: UUID | None = None
    notes: str | None = None


class AcceptDraftRequest(BaseModel):
    """User promotes a draft to the RFI's `response` column."""

    notes: str | None = None
