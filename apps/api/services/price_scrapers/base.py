"""Contracts for provincial price scrapers.

Every province has a slightly different publication cadence (monthly vs
quarterly), format (HTML table, PDF, DOCX, XLSX), and vocabulary for the
same materials. We standardise around two shapes:

- `ScrapedPrice`: one row after scraping, before normalisation. Raw
  material name + unit + price as published.
- `NormalisedPrice`: after the normaliser maps `raw_name` → standard
  `material_code` from our catalogue.

A concrete scraper implements `BaseScraper.scrape()` and returns a list
of `ScrapedPrice`. The runner feeds those through the normaliser + writer.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class ScrapedPrice:
    """Raw published price row — material name in the language the province used."""

    raw_name: str
    """Material description exactly as published (often Vietnamese)."""

    raw_unit: str
    """Unit as published — normalised to lower-case ASCII where obvious."""

    price_vnd: Decimal
    """Unit price in VND. Provinces publish without VAT; we store without VAT."""

    effective_date: date
    """Date the price list took effect (publication date, not fetch date)."""

    province: str
    """Canonical province name (e.g. 'Hanoi', 'HCMC'). See `PROVINCES`."""

    source_url: str | None = None
    """Canonical page or attachment URL for audit."""

    attributes: dict[str, str] = field(default_factory=dict)
    """Free-form metadata — section, notes, government decision number, etc."""


@dataclass
class NormalisedPrice:
    """After normalisation — ready to upsert into `material_prices`."""

    material_code: str
    name: str
    category: str | None
    unit: str
    price_vnd: Decimal
    province: str
    effective_date: date
    source_url: str | None = None


class ScrapeError(Exception):
    """Raised when a scraper can't reach its source or parse its output."""


class BaseScraper(abc.ABC):
    """Implement `scrape()` to return this province's current price list.

    Implementations should be idempotent (calling twice returns the same
    data for the same publication period) and must never raise on
    per-row failure — log, skip, and continue, so one bad row doesn't
    abort the whole province.
    """

    #: Canonical province name as stored in `material_prices.province`.
    province: str = ""

    #: Short machine slug used as registry key (e.g. 'moc', 'hanoi', 'hcmc').
    slug: str = ""

    @abc.abstractmethod
    async def scrape(self) -> list[ScrapedPrice]:
        """Fetch + parse the latest price list. May hit the network."""

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return f"<{type(self).__name__} slug={self.slug!r} province={self.province!r}>"
