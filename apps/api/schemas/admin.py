"""Pydantic schemas for the cross-module admin / ops surface.

Distinct from per-vertical schemas because admin endpoints are
*platform-wide* — they ignore tenant scope and surface global ops data
(scraper telemetry, system queue depths, etc.). Schemas live here
rather than in `schemas/costpulse.py` even when the data originates
from a single vertical, so the admin API stays cohesive even as more
verticals add ops surfaces.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NormalizerRuleOut(BaseModel):
    """One row from `normalizer_rules`. Mirrors `models.core.NormalizerRule`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    priority: int
    pattern: str
    material_code: str
    category: str | None = None
    canonical_name: str
    preferred_units: str = ""
    enabled: bool
    created_at: datetime
    updated_at: datetime


class NormalizerRuleCreate(BaseModel):
    """Body for `POST /api/v1/admin/normalizer-rules`.

    No id / timestamps — server stamps both. `priority` defaults to 50
    (between code rules' implicit priority and the typical "experiment"
    bucket of 100+).
    """

    priority: int = Field(default=50, ge=0, le=10_000)
    pattern: str = Field(min_length=1, max_length=500)
    material_code: str = Field(min_length=1, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    canonical_name: str = Field(min_length=1, max_length=200)
    preferred_units: str = Field(default="", max_length=200)
    enabled: bool = True


class NormalizerRuleUpdate(BaseModel):
    """PATCH-shaped: every field optional, only set what's changing."""

    priority: int | None = Field(default=None, ge=0, le=10_000)
    pattern: str | None = Field(default=None, min_length=1, max_length=500)
    material_code: str | None = Field(default=None, min_length=1, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    canonical_name: str | None = Field(default=None, min_length=1, max_length=200)
    preferred_units: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


class ScraperRunOut(BaseModel):
    """One row from `scraper_runs`. Mirrors `models.core.ScraperRun`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    started_at: datetime
    finished_at: datetime | None = None
    ok: bool
    error: str | None = None
    scraped: int
    matched: int
    unmatched: int
    written: int
    rule_hits: dict[str, int] = Field(default_factory=dict)
    unmatched_sample: list[str] = Field(default_factory=list)

    @property
    def unmatched_ratio(self) -> float | None:
        """Convenience for the UI — drift signal, on the wire as a number."""
        return self.unmatched / self.scraped if self.scraped else None


class ScraperRunsSummaryPoint(BaseModel):
    """One drift data point inside `ScraperRunsSummaryRow.points`.

    `ratio` is `unmatched / scraped` for that single run. `None` when
    the run had `scraped == 0` (couldn't drive a ratio without
    division-by-zero) — the sparkline renders such points as gaps.
    """

    started_at: datetime
    ratio: float | None = None


class ScraperRunsSummaryRow(BaseModel):
    """Per-slug aggregate over a configurable window. Drives the
    `/admin/scrapers` dashboard summary table + drift sparkline.

    `points` is the per-run drift series (oldest first), bounded by
    the same `days` window used for the aggregates. The series is
    intentionally NOT downsampled — daily-cron slugs produce ~30 points
    over a 30d window, which is fine for an inline SVG sparkline.
    """

    slug: str
    total_runs: int
    failure_rate: float | None = None
    avg_drift: float | None = None
    last_run_at: datetime | None = None
    last_run_ok: bool | None = None
    points: list[ScraperRunsSummaryPoint] = Field(default_factory=list)
