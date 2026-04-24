"""Public entrypoints for the price-scraper framework.

Adding a new province:
  1. Create `services/price_scrapers/<slug>.py` with a `BaseScraper`
     subclass that sets `province` + `slug` and implements `scrape()`.
  2. Register it in `SCRAPERS` below.
  3. The monthly arq cron will pick it up automatically.

Runtime contract:

    scraper = get_scraper("hanoi")
    summary = await run_scraper(scraper)   # scrape + normalise + write
    # summary == {"scraped": 120, "matched": 95, "unmatched": 25, "written": 95}
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import BaseScraper, NormalisedPrice, ScrapedPrice, ScrapeError
from .normalizer import normalise
from .writer import write_prices

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _build_bespoke_registry() -> dict[str, type[BaseScraper]]:
    """Scrapers that don't fit the generic template (custom CMS, DOCX-only, etc.)."""
    # Lazy imports so optional deps (httpx) only load when a scraper runs.
    from .hanoi import HanoiScraper
    from .hcmc import HCMCScraper
    from .ministry import MinistryOfConstructionScraper

    return {
        MinistryOfConstructionScraper.slug: MinistryOfConstructionScraper,
        HanoiScraper.slug: HanoiScraper,
        HCMCScraper.slug: HCMCScraper,
    }


def _build_generic_slugs() -> set[str]:
    """Slugs whose scraper is a `GenericProvinceScraper` driven by config."""
    from .provinces import ALL

    return {cfg.slug for cfg in ALL}


SCRAPERS: dict[str, type[BaseScraper]] = _build_bespoke_registry()
"""Bespoke scrapers, keyed by slug. For generic ones use `get_scraper(slug)`."""

GENERIC_SLUGS: set[str] = _build_generic_slugs()
"""Slugs handled by `GenericProvinceScraper` — can't be type-registered
because they all share one class, so we track them in a separate set."""


def all_slugs() -> list[str]:
    """Every registered scraper slug — bespoke + generic."""
    return sorted(set(SCRAPERS) | GENERIC_SLUGS)


def get_scraper(slug: str) -> BaseScraper:
    """Instantiate the scraper for `slug`. Raises KeyError on unknown slug."""
    if slug in SCRAPERS:
        return SCRAPERS[slug]()
    if slug in GENERIC_SLUGS:
        from .generic_province import GenericProvinceScraper
        from .provinces import ALL

        cfg = next(c for c in ALL if c.slug == slug)
        return GenericProvinceScraper(cfg)
    raise KeyError(slug)


async def run_scraper(scraper: BaseScraper) -> dict:
    """Scrape → normalise → write. Never raises — returns status dict."""
    try:
        raw = await scraper.scrape()
    except ScrapeError as exc:
        logger.exception("%s failed: %s", scraper.slug, exc)
        return {
            "slug": scraper.slug,
            "ok": False,
            "error": str(exc),
            "scraped": 0, "matched": 0, "unmatched": 0, "written": 0,
        }

    matched, unmatched = normalise(raw)
    write_summary = await write_prices(matched)

    summary = {
        "slug": scraper.slug,
        "ok": True,
        "scraped": len(raw),
        "matched": len(matched),
        "unmatched": len(unmatched),
        "written": write_summary["inserted_or_updated"],
    }
    logger.info("scraper.run %s: %s", scraper.slug, summary)
    return summary


async def run_all_scrapers() -> list[dict]:
    """Sequentially run every registered scraper. Returns per-slug summaries.

    We intentionally run serially — most provincial DOC sites are on shared
    infra and dislike concurrent hammering, and the overall job isn't
    latency-sensitive (cron, not user-facing).
    """
    results: list[dict] = []
    for slug in all_slugs():
        results.append(await run_scraper(get_scraper(slug)))
    return results


__all__ = [
    "BaseScraper",
    "NormalisedPrice",
    "ScrapedPrice",
    "ScrapeError",
    "SCRAPERS",
    "GENERIC_SLUGS",
    "all_slugs",
    "get_scraper",
    "run_scraper",
    "run_all_scrapers",
    "normalise",
    "write_prices",
]
