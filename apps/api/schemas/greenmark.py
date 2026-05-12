"""Pydantic schemas for GREENMARK — LOTUS + EDGE scoring."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------- Enums ----------


class CertSystem(StrEnum):
    lotus_nr = "lotus_nr"  # LOTUS New Construction
    lotus_homes = "lotus_homes"  # LOTUS Homes (residential)
    lotus_bio = "lotus_bio"  # LOTUS Buildings In Operation
    lotus_intl = "lotus_intl"  # LOTUS Interiors
    edge = "edge"  # IFC EDGE


class TargetLevel(StrEnum):
    # LOTUS tiers
    certified = "certified"
    silver = "silver"
    gold = "gold"
    platinum = "platinum"
    # EDGE tiers
    edge_certified = "edge_certified"  # ≥20% savings (E + W + M)
    edge_advanced = "edge_advanced"  # ≥40% energy savings
    edge_zero = "edge_zero"  # net-zero ops


class CertStatus(StrEnum):
    planning = "planning"
    self_assessment = "self_assessment"
    submitted = "submitted"
    provisional = "provisional"  # design-stage cert
    final_cert = "final_cert"
    rejected = "rejected"
    expired = "expired"


class CreditCategory(StrEnum):
    energy = "energy"
    water = "water"
    materials = "materials"
    ieq = "ieq"  # Indoor Environmental Quality
    site = "site"
    operations = "operations"
    innovation = "innovation"


class CreditStatus(StrEnum):
    not_attempted = "not_attempted"
    targeted = "targeted"
    documented = "documented"
    verified = "verified"
    rejected = "rejected"


# LOTUS NR point thresholds per VGBC v3 ratings. Used by the
# gap-to-next-level endpoint.
LOTUS_LEVEL_THRESHOLDS: dict[TargetLevel, int] = {
    TargetLevel.certified: 40,
    TargetLevel.silver: 55,
    TargetLevel.gold: 75,
    TargetLevel.platinum: 90,
}


# EDGE savings thresholds (fraction of baseline). EDGE Advanced
# additionally requires ≥40% energy savings specifically.
EDGE_LEVEL_THRESHOLDS: dict[TargetLevel, dict[str, float]] = {
    TargetLevel.edge_certified: {"energy_min": 0.20, "water_min": 0.20, "materials_min": 0.20},
    TargetLevel.edge_advanced: {"energy_min": 0.40, "water_min": 0.20, "materials_min": 0.20},
    TargetLevel.edge_zero: {"energy_min": 1.00, "water_min": 0.20, "materials_min": 0.20},
}


# ---------- Certifications ----------


class GreenCertificationCreate(BaseModel):
    project_id: UUID
    system: CertSystem
    target_level: TargetLevel
    project_brief: dict[str, Any] = Field(default_factory=dict)
    assessor_name: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _level_matches_system(self) -> GreenCertificationCreate:
        lotus_levels = {
            TargetLevel.certified,
            TargetLevel.silver,
            TargetLevel.gold,
            TargetLevel.platinum,
        }
        edge_levels = {
            TargetLevel.edge_certified,
            TargetLevel.edge_advanced,
            TargetLevel.edge_zero,
        }
        is_edge = self.system == CertSystem.edge
        if is_edge and self.target_level not in edge_levels:
            raise ValueError("EDGE system requires an EDGE target_level")
        if not is_edge and self.target_level not in lotus_levels:
            raise ValueError("LOTUS systems require a LOTUS target_level")
        return self


class GreenCertificationUpdate(BaseModel):
    target_level: TargetLevel | None = None
    status: CertStatus | None = None
    project_brief: dict[str, Any] | None = None
    certification_no: str | None = None
    awarded_at: date | None = None
    valid_until: date | None = None
    assessor_name: str | None = None
    notes: str | None = None


class GreenCertification(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    system: CertSystem
    target_level: TargetLevel
    achieved_level: TargetLevel | None = None
    status: CertStatus
    achieved_points: Decimal
    max_points: Decimal
    project_brief: dict[str, Any] = Field(default_factory=dict)
    certification_no: str | None = None
    awarded_at: date | None = None
    valid_until: date | None = None
    assessor_name: str | None = None
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class CertListFilters(BaseModel):
    project_id: UUID | None = None
    system: CertSystem | None = None
    status: CertStatus | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CertSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    system: CertSystem
    target_level: TargetLevel
    achieved_level: TargetLevel | None = None
    status: CertStatus
    achieved_points: Decimal
    max_points: Decimal
    credit_total: int = 0
    credit_verified: int = 0
    certification_no: str | None = None
    awarded_at: date | None = None
    valid_until: date | None = None
    created_at: datetime


# ---------- Credits ----------


class GreenCreditCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    category: CreditCategory
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    max_points: Decimal = Field(ge=0)
    sort_order: int = 0


class GreenCreditUpdate(BaseModel):
    status: CreditStatus | None = None
    claimed_points: Decimal | None = Field(default=None, ge=0)
    awarded_points: Decimal | None = Field(default=None, ge=0)
    computed_metrics: dict[str, Any] | None = None
    evidence_file_ids: list[UUID] | None = None
    reviewer_note: str | None = None


class GreenCredit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    certification_id: UUID
    code: str
    category: CreditCategory
    title: str
    description: str | None = None
    status: CreditStatus
    max_points: Decimal
    claimed_points: Decimal
    awarded_points: Decimal
    computed_metrics: dict[str, Any] = Field(default_factory=dict)
    evidence_file_ids: list[UUID] = Field(default_factory=list)
    reviewer_note: str | None = None
    reviewer_user_id: UUID | None = None
    reviewed_at: datetime | None = None
    sort_order: int
    created_at: datetime
    updated_at: datetime


# ---------- Scoring helpers ----------


def score_for_credit(c: dict[str, Any]) -> Decimal:
    """Per-credit contribution to the running total.

    Verified credits use `awarded_points`; everything else uses
    `claimed_points`. `rejected` always 0. `not_attempted` always 0.
    """
    status = CreditStatus(c["status"])
    if status in (CreditStatus.rejected, CreditStatus.not_attempted):
        return Decimal("0")
    if status == CreditStatus.verified:
        return Decimal(c["awarded_points"])
    return Decimal(c["claimed_points"])


def lotus_level_for_points(points: Decimal) -> TargetLevel | None:
    """Highest LOTUS level achievable at this point total.

    Returns None when below 'certified' threshold (40 pts) — caller
    surfaces that as "not yet certifiable".
    """
    achieved = None
    for level in (
        TargetLevel.certified,
        TargetLevel.silver,
        TargetLevel.gold,
        TargetLevel.platinum,
    ):
        if points >= LOTUS_LEVEL_THRESHOLDS[level]:
            achieved = level
    return achieved


# ---------- Detail / scoring response ----------


class CertDetail(GreenCertification):
    credits: list[GreenCredit] = Field(default_factory=list)


class ScoreBreakdownRow(BaseModel):
    category: CreditCategory
    earned_points: Decimal
    max_points: Decimal


class ScoreResult(BaseModel):
    certification_id: UUID
    system: CertSystem
    achieved_points: Decimal
    max_points: Decimal
    achieved_level: TargetLevel | None = None
    breakdown: list[ScoreBreakdownRow]


class GapToNextLevel(BaseModel):
    certification_id: UUID
    current_level: TargetLevel | None = None
    next_level: TargetLevel | None = None
    points_needed: Decimal
    candidate_credits: list[GreenCredit] = Field(default_factory=list)


class SeedCreditsRequest(BaseModel):
    """Seed the default credit catalog for the certification's system."""

    template_version: str = "vgbc_lotus_v3"
