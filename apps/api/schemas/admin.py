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
