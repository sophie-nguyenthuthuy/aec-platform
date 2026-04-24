"""TP. Hồ Chí Minh Department of Construction price scraper.

Source: soxaydung.hochiminhcity.gov.vn. HCMC publishes quarterly
(slightly slower cadence than Hanoi) and sometimes gates the full price
list behind a DOCX attachment. This scraper handles the HTML-table path;
DOCX-only bulletins are logged and skipped (operator picks them up
manually or we add a docx parser later).
"""
from __future__ import annotations

import logging
import re
from datetime import date

from .base import BaseScraper, ScrapedPrice, ScrapeError
from .ministry import _parse_bulletin_html

logger = logging.getLogger(__name__)


_HCMC_LISTING_URL = "https://soxaydung.hochiminhcity.gov.vn/thong-bao-gia-vat-lieu"


class HCMCScraper(BaseScraper):
    province = "HCMC"
    slug = "hcmc"

    def __init__(self, *, http_client=None) -> None:
        self._http = http_client

    async def scrape(self) -> list[ScrapedPrice]:
        client = await self._get_client()
        try:
            listing = await client.get(_HCMC_LISTING_URL, timeout=30.0)
            listing.raise_for_status()
            bulletin_url = _find_latest_hcmc_bulletin_url(listing.text)
            if bulletin_url is None:
                logger.warning("HCMC scraper: no bulletin link found")
                return []

            # Detect DOCX-only bulletins: their URL ends in .doc/.docx/.pdf.
            if bulletin_url.lower().endswith((".doc", ".docx", ".pdf")):
                logger.warning(
                    "HCMC scraper: latest bulletin is a binary attachment (%s); "
                    "skipping — add a DOCX parser to pick this up",
                    bulletin_url,
                )
                return []

            bulletin = await client.get(bulletin_url, timeout=30.0)
            bulletin.raise_for_status()
            rows = _parse_bulletin_html(bulletin.text, source_url=bulletin_url)
            return [
                ScrapedPrice(
                    raw_name=r.raw_name,
                    raw_unit=r.raw_unit,
                    price_vnd=r.price_vnd,
                    effective_date=r.effective_date,
                    province="HCMC",
                    source_url=r.source_url,
                    attributes=r.attributes,
                )
                for r in rows
            ]
        except Exception as exc:
            raise ScrapeError(f"HCMC scrape failed: {exc}") from exc

    async def _get_client(self):
        if self._http is not None:
            return self._http
        import httpx

        return httpx.AsyncClient(follow_redirects=True)


_HCMC_BULLETIN_RE = re.compile(
    r'href="([^"]*(?:thong-bao-gia|cong-bo-gia)[^"]*)"', re.IGNORECASE
)


def _find_latest_hcmc_bulletin_url(listing_html: str) -> str | None:
    match = _HCMC_BULLETIN_RE.search(listing_html)
    if match is None:
        return None
    href = match.group(1)
    if href.startswith("/"):
        return f"https://soxaydung.hochiminhcity.gov.vn{href}"
    if href.startswith("http"):
        return href
    return f"https://soxaydung.hochiminhcity.gov.vn/{href}"
