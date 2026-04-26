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
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from .base import BaseScraper, NormalisedPrice, ScrapedPrice, ScrapeError
from .normalizer import normalise
from .writer import write_prices

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Cap on how many distinct unmatched names we keep per run. The full
# list could be hundreds of rows; the sample exists so ops can spot
# new naming conventions, not for exhaustive enumeration.
_UNMATCHED_SAMPLE_CAP = 25

# Threshold over which run_scraper logs a DRIFT WARNING. 30% picked as
# "noticeably worse than typical (~5-15%) but not so tight it cries
# wolf on a freshly-added province whose first scrape predates rule
# tuning". Tune downward once we have telemetry across enough runs.
_DRIFT_THRESHOLD = 0.30


def _now() -> datetime:
    """Wall clock for run timestamps — patched in tests for determinism."""
    return datetime.now(UTC)


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
    """Scrape → normalise → write. Never raises — returns status dict.

    Also persists one `scraper_runs` row per invocation (success or
    failure) for drift telemetry, and logs a `scraper.drift[slug]`
    WARNING when `unmatched / scraped > 30%`. Persistence is best-effort:
    a DB failure is logged but doesn't propagate, so a temporarily-
    degraded ops DB never cascades into "every scrape job marked failed
    in arq".
    """
    started_at = _now()
    try:
        raw = await scraper.scrape()
    except ScrapeError as exc:
        logger.exception("%s failed: %s", scraper.slug, exc)
        summary = {
            "slug": scraper.slug,
            "ok": False,
            "error": str(exc),
            "scraped": 0,
            "matched": 0,
            "unmatched": 0,
            "written": 0,
            "rule_hits": {},
            "unmatched_sample": [],
        }
        await _persist_run(summary, started_at=started_at, finished_at=_now())
        return summary

    result = normalise(raw)
    write_summary = await write_prices(result.matched)

    summary = {
        "slug": scraper.slug,
        "ok": True,
        "scraped": len(raw),
        "matched": len(result.matched),
        "unmatched": len(result.unmatched),
        "written": write_summary["inserted_or_updated"],
        "rule_hits": result.rule_hits,
        "unmatched_sample": _unmatched_sample(result.unmatched),
    }
    logger.info("scraper.run %s: %s", scraper.slug, _summary_for_log(summary))
    _maybe_log_drift(scraper.slug, summary)
    await _persist_run(summary, started_at=started_at, finished_at=_now())
    return summary


def _unmatched_sample(unmatched: list[ScrapedPrice]) -> list[str]:
    """Distinct raw_names from `unmatched`, capped — for drift telemetry."""
    seen: set[str] = set()
    out: list[str] = []
    for row in unmatched:
        if row.raw_name in seen:
            continue
        seen.add(row.raw_name)
        out.append(row.raw_name)
        if len(out) >= _UNMATCHED_SAMPLE_CAP:
            break
    return out


def _summary_for_log(summary: dict) -> dict:
    """Trimmed summary suitable for a log line — drops verbose fields."""
    return {k: v for k, v in summary.items() if k not in ("rule_hits", "unmatched_sample")}


def _maybe_log_drift(slug: str, summary: dict) -> None:
    """Surface a high-visibility WARN when too many rows fail to normalise."""
    scraped = summary["scraped"]
    unmatched = summary["unmatched"]
    if scraped == 0:
        return
    ratio = unmatched / scraped
    if ratio < _DRIFT_THRESHOLD:
        return
    logger.warning(
        "scraper.drift[%s]: %d/%d (%.0f%%) unmatched — rules may need updating; sample names: %s",
        slug,
        unmatched,
        scraped,
        ratio * 100,
        summary["unmatched_sample"][:5],
    )


async def _persist_run(summary: dict, *, started_at: datetime, finished_at: datetime) -> None:
    """Write one `scraper_runs` row. Best-effort: failures log + return.

    Uses `AdminSessionFactory` because `scraper_runs` is global ops data
    with no `organization_id`; the `aec_app` runtime role gets DML grants
    via 0010's `ALTER DEFAULT PRIVILEGES`, but using the admin factory
    keeps the call site identical for cross-tenant batch contexts that
    have no `app.current_org_id` set.
    """
    try:
        from db.session import AdminSessionFactory
        from models.core import ScraperRun

        async with AdminSessionFactory() as session:
            session.add(
                ScraperRun(
                    id=uuid4(),
                    slug=summary["slug"],
                    started_at=started_at,
                    finished_at=finished_at,
                    ok=bool(summary.get("ok")),
                    error=summary.get("error"),
                    scraped=int(summary.get("scraped", 0)),
                    matched=int(summary.get("matched", 0)),
                    unmatched=int(summary.get("unmatched", 0)),
                    written=int(summary.get("written", 0)),
                    rule_hits=summary.get("rule_hits") or {},
                    unmatched_sample=summary.get("unmatched_sample") or [],
                )
            )
            await session.commit()
    except Exception as exc:  # pragma: no cover — telemetry must never fail the scrape
        logger.warning(
            "scraper.persist_run[%s]: failed to write telemetry row: %s",
            summary.get("slug"),
            exc,
        )


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
