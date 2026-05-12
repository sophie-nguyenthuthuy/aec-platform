"""Pydantic schemas for WORKFORCE — VN labor records."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EmploymentType(StrEnum):
    direct = "direct"
    subcontractor = "subcontractor"
    temporary = "temporary"
    foreign = "foreign"


class WorkerStatus(StrEnum):
    active = "active"
    inactive = "inactive"
    terminated = "terminated"


class SafetyGroup(StrEnum):
    """Safety training groups per NĐ 44/2016 Art. 17."""

    g1 = "1"  # senior managers
    g2 = "2"  # safety officers
    g3 = "3"  # workers in hazardous trades
    g4 = "4"  # workers in non-hazardous trades
    g5 = "5"  # medical & first aid
    g6 = "6"  # safety supervisors


class TrainingStatus(StrEnum):
    valid = "valid"
    expired = "expired"
    revoked = "revoked"


class InsuranceStatus(StrEnum):
    enrolled = "enrolled"
    pending = "pending"
    not_required = "not_required"
    terminated = "terminated"
    superseded = "superseded"


class PermitExemptionType(StrEnum):
    required = "required"
    exempt_short_term = "exempt_short_term"
    exempt_intracompany = "exempt_intracompany"
    exempt_other = "exempt_other"


class PermitStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    cancelled = "cancelled"


class AssignmentStatus(StrEnum):
    active = "active"
    ended = "ended"
    cancelled = "cancelled"


# CCCD (12 digits) or CMND (9 digits).
_ID_RE = re.compile(r"^\d{9}$|^\d{12}$")


def validate_vn_id(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not _ID_RE.match(value):
        raise ValueError(f"VN ID must be 9 or 12 digits, got {value!r}")
    return value


# Renewal cycles per NĐ 44/2016. Groups 1, 2, 5, 6 every 24 months;
# groups 3 & 4 every 36 months. Exposed as a helper so the cron uses
# the same logic the create endpoint uses.
def default_valid_until(group: SafetyGroup, training_date: date) -> date:
    if group in (SafetyGroup.g3, SafetyGroup.g4):
        return training_date + timedelta(days=365 * 3)
    return training_date + timedelta(days=365 * 2)


# ---------- Worker ----------


class WorkerCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    dob: date | None = None
    gender: str | None = None
    id_no: str | None = None
    id_issued_date: date | None = None
    id_issued_place: str | None = None
    phone: str | None = None
    address: str | None = None
    trade: str = Field(min_length=1, max_length=80)
    employment_type: EmploymentType = EmploymentType.direct
    employer_org_name: str | None = None
    nationality: str = Field(default="VN", min_length=2, max_length=3)
    hire_date: date | None = None
    notes: str | None = None

    @field_validator("id_no")
    @classmethod
    def _v_id(cls, v: str | None) -> str | None:
        return validate_vn_id(v)


class WorkerUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = None
    address: str | None = None
    trade: str | None = Field(default=None, min_length=1, max_length=80)
    employment_type: EmploymentType | None = None
    employer_org_name: str | None = None
    status: WorkerStatus | None = None
    termination_date: date | None = None
    notes: str | None = None


class Worker(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    full_name: str
    dob: date | None = None
    gender: str | None = None
    id_no: str | None = None
    id_issued_date: date | None = None
    id_issued_place: str | None = None
    phone: str | None = None
    address: str | None = None
    trade: str
    employment_type: EmploymentType
    employer_org_name: str | None = None
    nationality: str
    status: WorkerStatus
    hire_date: date | None = None
    termination_date: date | None = None
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class WorkerListFilters(BaseModel):
    project_id: UUID | None = None
    trade: str | None = None
    status: WorkerStatus | None = None
    employment_type: EmploymentType | None = None
    nationality: str | None = None
    q: str | None = None  # name/id search
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class WorkerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    full_name: str
    trade: str
    employment_type: EmploymentType
    nationality: str
    status: WorkerStatus
    id_no: str | None = None
    phone: str | None = None
    has_valid_safety_training: bool = False
    has_active_insurance: bool = False
    has_active_permit: bool = False
    active_assignment_count: int = 0
    created_at: datetime


# ---------- Safety training ----------


class SafetyTrainingCreate(BaseModel):
    group: SafetyGroup
    training_org: str = Field(min_length=1, max_length=200)
    training_date: date
    valid_until: date | None = None
    certificate_no: str | None = None
    certificate_file_id: UUID | None = None
    notes: str | None = None


class SafetyTraining(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    worker_id: UUID
    group: SafetyGroup
    training_org: str
    training_date: date
    valid_until: date
    certificate_no: str | None = None
    certificate_file_id: UUID | None = None
    status: TrainingStatus
    notes: str | None = None
    created_at: datetime


# ---------- Insurance ----------


class InsuranceEnrollmentCreate(BaseModel):
    basic_salary_vnd: int = Field(ge=0)
    bhxh_enrolled: bool = True
    bhyt_enrolled: bool = True
    bhtn_enrolled: bool = True
    bhxh_no: str | None = None
    enrolled_at: date | None = None
    notes: str | None = None


class InsuranceEnrollment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    worker_id: UUID
    basic_salary_vnd: int
    bhxh_enrolled: bool
    bhyt_enrolled: bool
    bhtn_enrolled: bool
    bhxh_no: str | None = None
    enrolled_at: date | None = None
    terminated_at: date | None = None
    status: InsuranceStatus
    superseded_by_id: UUID | None = None
    notes: str | None = None
    created_at: datetime


# Contribution-rate table (per NĐ 58/2020/NĐ-CP). Centralised so the
# `compute_monthly_contribution` helper and the UI render the same
# numbers.
class ContributionRates(BaseModel):
    """Rates expressed as Decimal fractions."""

    bhxh_employer: Decimal = Decimal("0.175")  # 17.5%
    bhxh_employee: Decimal = Decimal("0.080")  # 8%
    bhyt_employer: Decimal = Decimal("0.030")  # 3%
    bhyt_employee: Decimal = Decimal("0.015")  # 1.5%
    bhtn_employer: Decimal = Decimal("0.010")  # 1%
    bhtn_employee: Decimal = Decimal("0.010")  # 1%
    kpcd_employer: Decimal = Decimal("0.020")  # 2% — KPCĐ (union fund)


DEFAULT_RATES = ContributionRates()


def compute_monthly_contribution(
    basic_salary_vnd: int,
    *,
    bhxh: bool = True,
    bhyt: bool = True,
    bhtn: bool = True,
    rates: ContributionRates = DEFAULT_RATES,
) -> dict[str, int]:
    """Per-month contribution breakdown.

    Returns absolute VND amounts per fund + employer/employee totals.
    Caller controls the enrollment booleans so a worker on `bhxh` only
    pays into BHXH (no BHYT/BHTN).
    """
    salary = Decimal(basic_salary_vnd)
    def _vnd(v: Decimal) -> int:
        return int(v.quantize(Decimal("1")))

    out: dict[str, int] = {
        "bhxh_employer": _vnd(salary * rates.bhxh_employer) if bhxh else 0,
        "bhxh_employee": _vnd(salary * rates.bhxh_employee) if bhxh else 0,
        "bhyt_employer": _vnd(salary * rates.bhyt_employer) if bhyt else 0,
        "bhyt_employee": _vnd(salary * rates.bhyt_employee) if bhyt else 0,
        "bhtn_employer": _vnd(salary * rates.bhtn_employer) if bhtn else 0,
        "bhtn_employee": _vnd(salary * rates.bhtn_employee) if bhtn else 0,
        "kpcd_employer": _vnd(salary * rates.kpcd_employer),  # always
    }
    out["employer_total"] = (
        out["bhxh_employer"]
        + out["bhyt_employer"]
        + out["bhtn_employer"]
        + out["kpcd_employer"]
    )
    out["employee_total"] = (
        out["bhxh_employee"] + out["bhyt_employee"] + out["bhtn_employee"]
    )
    return out


# ---------- Foreign permit ----------


class PermitCreate(BaseModel):
    nationality: str = Field(min_length=2, max_length=3)
    passport_no: str = Field(min_length=1, max_length=20)
    job_position: str = Field(min_length=1, max_length=200)
    exemption_type: PermitExemptionType = PermitExemptionType.required
    permit_no: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _required_needs_dates(self) -> PermitCreate:
        if self.exemption_type == PermitExemptionType.required and self.issue_date and self.expiry_date:
            if self.expiry_date <= self.issue_date:
                raise ValueError("expiry_date must be after issue_date")
        return self


class ForeignPermit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    worker_id: UUID
    nationality: str
    passport_no: str
    job_position: str
    permit_no: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    exemption_type: PermitExemptionType
    status: PermitStatus
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------- Assignment ----------


class AssignmentCreate(BaseModel):
    project_id: UUID
    role_on_project: str | None = None
    start_date: date
    end_date: date | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Assignment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    worker_id: UUID
    project_id: UUID
    role_on_project: str | None = None
    start_date: date
    end_date: date | None = None
    status: AssignmentStatus
    notes: str | None = None
    created_at: datetime


# ---------- Detail / alerts ----------


class WorkerDetail(Worker):
    safety_trainings: list[SafetyTraining] = Field(default_factory=list)
    insurance_enrollments: list[InsuranceEnrollment] = Field(default_factory=list)
    foreign_permits: list[ForeignPermit] = Field(default_factory=list)
    assignments: list[Assignment] = Field(default_factory=list)


class WorkforceAlert(BaseModel):
    worker_id: UUID
    code: str
    severity: str
    message: str
    related_id: UUID | None = None
    days_until: int | None = None
    expiry_date: date | None = None
