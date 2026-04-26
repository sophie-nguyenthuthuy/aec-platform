"""Pydantic schemas for PROJECTPULSE module."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Enums ----------


class TaskStatus(StrEnum):
    todo = "todo"
    in_progress = "in_progress"
    review = "review"
    done = "done"
    blocked = "blocked"


class Priority(StrEnum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class Phase(StrEnum):
    design = "design"
    permit = "permit"
    construction = "construction"
    closeout = "closeout"


class MilestoneStatus(StrEnum):
    upcoming = "upcoming"
    achieved = "achieved"
    missed = "missed"


class ChangeOrderStatus(StrEnum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"


class ChangeOrderInitiator(StrEnum):
    client = "client"
    contractor = "contractor"
    designer = "designer"


class ReportStatus(StrEnum):
    draft = "draft"
    sent = "sent"
    archived = "archived"


class RAG(StrEnum):
    green = "green"
    amber = "amber"
    red = "red"


# ---------- Tasks ----------


class TaskBase(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    status: TaskStatus = TaskStatus.todo
    priority: Priority = Priority.normal
    assignee_id: UUID | None = None
    phase: Phase | None = None
    discipline: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    position: float | None = None
    tags: list[str] = Field(default_factory=list)
    parent_id: UUID | None = None


class TaskCreate(TaskBase):
    project_id: UUID


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    assignee_id: UUID | None = None
    phase: Phase | None = None
    discipline: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    position: float | None = None
    tags: list[str] | None = None
    parent_id: UUID | None = None


class Task(TaskBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    organization_id: UUID
    completed_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime


class TaskBulkItem(BaseModel):
    id: UUID
    status: TaskStatus | None = None
    phase: Phase | None = None
    position: float | None = None
    assignee_id: UUID | None = None


class TaskBulkUpdate(BaseModel):
    items: list[TaskBulkItem] = Field(min_length=1, max_length=200)


class TaskListFilters(BaseModel):
    project_id: UUID | None = None
    assignee_id: UUID | None = None
    phase: Phase | None = None
    status: TaskStatus | None = None
    parent_id: UUID | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


# ---------- Milestones ----------


class MilestoneBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    due_date: date
    status: MilestoneStatus = MilestoneStatus.upcoming


class MilestoneCreate(MilestoneBase):
    project_id: UUID


class Milestone(MilestoneBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    organization_id: UUID
    achieved_at: datetime | None = None


# ---------- Change orders ----------


class ChangeOrderBase(BaseModel):
    number: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    initiator: ChangeOrderInitiator | None = None
    cost_impact_vnd: int | None = None
    schedule_impact_days: int | None = None


class ChangeOrderCreate(ChangeOrderBase):
    project_id: UUID


class ChangeOrderUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: ChangeOrderStatus | None = None
    initiator: ChangeOrderInitiator | None = None
    cost_impact_vnd: int | None = None
    schedule_impact_days: int | None = None


class ChangeOrderAIAnalysis(BaseModel):
    root_cause: Literal["design_change", "scope_creep", "site_condition", "error", "other"]
    cost_breakdown: dict[str, Any] = Field(default_factory=dict)
    schedule_analysis: dict[str, Any] = Field(default_factory=dict)
    contract_clauses: list[str] = Field(default_factory=list)
    recommendation: Literal["approve", "negotiate", "reject", "request_more_info"]
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)


class ChangeOrder(ChangeOrderBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    organization_id: UUID
    status: ChangeOrderStatus
    ai_analysis: ChangeOrderAIAnalysis | None = None
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    created_at: datetime


class ChangeOrderApproval(BaseModel):
    decision: Literal["approve", "reject"]
    notes: str | None = None


class ChangeOrderListFilters(BaseModel):
    project_id: UUID | None = None
    status: ChangeOrderStatus | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


# ---------- Meeting notes ----------


class ActionItem(BaseModel):
    title: str
    owner: str | None = None
    owner_user_id: UUID | None = None
    deadline: date | None = None


class MeetingStructured(BaseModel):
    summary: str
    decisions: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_meeting: date | None = None


class MeetingNoteCreate(BaseModel):
    project_id: UUID
    meeting_date: date
    attendees: list[str] = Field(default_factory=list)
    raw_notes: str = Field(min_length=1)


class MeetingNote(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    organization_id: UUID
    meeting_date: date
    attendees: list[str] = Field(default_factory=list)
    raw_notes: str | None = None
    ai_structured: MeetingStructured | None = None
    created_by: UUID | None = None
    created_at: datetime


class MeetingStructureRequest(BaseModel):
    raw_notes: str = Field(min_length=1, max_length=20000)
    language: Literal["vi", "en"] | None = None
    project_id: UUID | None = None
    meeting_note_id: UUID | None = None
    persist: bool = True


# ---------- Client reports ----------


class ReportGenerateRequest(BaseModel):
    project_id: UUID
    period: str = Field(description="e.g. 2026-W16, 2026-04, custom")
    date_from: date | None = None
    date_to: date | None = None
    language: Literal["vi", "en"] = "vi"
    include_photos: bool = True
    include_financials: bool = True


class ClientReportContent(BaseModel):
    header_summary: str
    progress_section: dict[str, Any]
    photos_section: list[dict[str, Any]] = Field(default_factory=list)
    financials: dict[str, Any] | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class ClientReport(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    organization_id: UUID
    report_date: date
    period: str | None = None
    content: ClientReportContent | None = None
    rendered_html: str | None = None
    pdf_url: str | None = None
    status: ReportStatus
    sent_at: datetime | None = None
    sent_to: list[str] | None = None


class ReportSendRequest(BaseModel):
    recipients: list[str] = Field(min_length=1)
    subject: str | None = None
    message: str | None = None


# ---------- Dashboard ----------


class TaskCountsByStatus(BaseModel):
    todo: int = 0
    in_progress: int = 0
    review: int = 0
    done: int = 0
    blocked: int = 0


class ProjectDashboard(BaseModel):
    project_id: UUID
    rag_status: RAG
    progress_pct: float = Field(ge=0.0, le=100.0)
    task_counts: TaskCountsByStatus
    overdue_tasks: int
    upcoming_milestones: list[Milestone]
    open_change_orders: int
    open_cost_impact_vnd: int
    last_report_date: date | None = None
    alerts: list[str] = Field(default_factory=list)
