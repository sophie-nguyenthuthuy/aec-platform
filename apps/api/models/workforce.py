"""WORKFORCE models — site labor records aligned with VN labor law.

Regulatory anchors:

  * **Bộ luật Lao động 2019** — labor relationship, working hours, OT.
  * **Luật ATVSLĐ 84/2015 + NĐ 44/2016/NĐ-CP** — occupational safety
    training (6 groups), mandatory certification + 2/3-year renewals.
  * **Luật BHXH 58/2014 + NĐ 115/2015** — BHXH (24% — 17.5% employer +
    8% employee), BHYT (4.5%), BHTN (2% — 1% each side), KPCĐ (2%
    employer-only).
  * **NĐ 152/2020/NĐ-CP** — foreign worker permits & exemptions.

Tables hang off `workers` (one row per individual, org-scoped, can be
assigned to multiple projects via `project_worker_assignments`).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class Worker(Base):
    """Person record. One row per individual, per org.

    Deliberately org-scoped (not project-scoped) — the same mason or
    electrician rotates across projects. The `project_worker_assignments`
    table tracks where they currently work; this table is the identity.
    """

    __tablename__ = "workers"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    dob: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(Text)  # `male` | `female` | `other`
    # Vietnamese national ID: 9 or 12 digits (CMND legacy / CCCD new).
    # Stored as text since leading zeros matter.
    id_no: Mapped[str | None] = mapped_column(Text)
    id_issued_date: Mapped[date | None] = mapped_column(Date)
    id_issued_place: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    # Free-form but with a recommended vocabulary (mason, electrician,
    # plumber, foreman, engineer, surveyor, …) — kept as text to
    # accommodate trade variants per project.
    trade: Mapped[str] = mapped_column(Text, nullable=False)
    # `direct` | `subcontractor` | `temporary` | `foreign`
    employment_type: Mapped[str] = mapped_column(Text, nullable=False, default="direct")
    employer_org_name: Mapped[str | None] = mapped_column(Text)
    nationality: Mapped[str] = mapped_column(Text, nullable=False, default="VN")
    # `active` | `inactive` | `terminated`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    hire_date: Mapped[date | None] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        # Stable de-dup key: an (org, id_no) pair is unique when id_no
        # is provided. NULL id_no is allowed (foreign worker pre-permit,
        # or temp labor) — Postgres allows multiple NULLs by default.
        UniqueConstraint("organization_id", "id_no", name="uq_workers_org_id_no"),
    )


class WorkerSafetyTraining(Base):
    """ATLD safety training record (Luật ATVSLĐ 84/2015 + NĐ 44/2016).

    Groups 1-6 per NĐ 44/2016 Art. 17:
      * Group 1: senior managers
      * Group 2: safety officers
      * Group 3: workers in hazardous trades (most site workers)
      * Group 4: workers in non-hazardous trades
      * Group 5: medical & first aid
      * Group 6: safety supervisors of contractors

    Renewal cycle: groups 1, 2, 5, 6 every 2 years; groups 3, 4 every
    3 years. The alerts cron warns ahead of expiry.
    """

    __tablename__ = "worker_safety_trainings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    worker_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workers.id", ondelete="CASCADE"),
        nullable=False,
    )
    group: Mapped[int] = mapped_column(Text, nullable=False)  # "1".."6"
    training_org: Mapped[str] = mapped_column(Text, nullable=False)
    training_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    certificate_no: Mapped[str | None] = mapped_column(Text)
    certificate_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL")
    )
    # `valid` | `expired` | `revoked`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="valid")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class WorkerInsuranceEnrollment(Base):
    """BHXH / BHYT / BHTN enrollment status.

    One row per worker, updated when basic salary / enrollment booleans
    change. History preserved by inserting a new row and superseding —
    not via column updates — so the audit trail survives.
    """

    __tablename__ = "worker_insurance_enrollments"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    worker_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workers.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Monthly basic salary used as the contribution base. Capped at 20×
    # minimum wage per regulation, but we store the raw figure here and
    # the cap is applied at computation time.
    basic_salary_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bhxh_enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bhyt_enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bhtn_enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Mã số BHXH — 10 digits issued by BHXH agency.
    bhxh_no: Mapped[str | None] = mapped_column(Text)
    enrolled_at: Mapped[date | None] = mapped_column(Date)
    terminated_at: Mapped[date | None] = mapped_column(Date)
    # `enrolled` | `pending` | `not_required` | `terminated` |
    # `superseded` (when replaced by a later row)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("worker_insurance_enrollments.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ForeignWorkerPermit(Base):
    """Work permit for foreign workers (giấy phép lao động).

    Per NĐ 152/2020, permits run up to 2 years and are renewable once.
    Some categories are exemption-eligible (intra-company transfer,
    short-term assignment ≤30 days, etc.) — `exemption_type` captures
    that path.
    """

    __tablename__ = "foreign_worker_permits"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    worker_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workers.id", ondelete="CASCADE"),
        nullable=False,
    )
    nationality: Mapped[str] = mapped_column(Text, nullable=False)
    passport_no: Mapped[str] = mapped_column(Text, nullable=False)
    job_position: Mapped[str] = mapped_column(Text, nullable=False)
    permit_no: Mapped[str | None] = mapped_column(Text)
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    # `required` | `exempt_short_term` | `exempt_intracompany` |
    # `exempt_other`
    exemption_type: Mapped[str] = mapped_column(Text, nullable=False, default="required")
    # `pending` | `approved` | `rejected` | `expired` | `cancelled`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    permit_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ProjectWorkerAssignment(Base):
    """Worker × Project assignment with date bounds.

    `role_on_project` may differ from `worker.trade` (e.g. a mason
    serving as foreman on a specific project). The `(worker_id,
    project_id, start_date)` triple is unique — re-assigning after a
    gap creates a new row, preserving the timeline.
    """

    __tablename__ = "project_worker_assignments"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    worker_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workers.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_on_project: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    # `active` | `ended` | `cancelled`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "worker_id",
            "project_id",
            "start_date",
            name="uq_project_worker_assignments_worker_project_start",
        ),
    )
