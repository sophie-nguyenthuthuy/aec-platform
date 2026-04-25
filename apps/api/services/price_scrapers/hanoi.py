"""Hà Nội Department of Construction price scraper.

Hanoi publishes monthly price lists at `soxaydung.hanoi.gov.vn` under
"Thông báo giá vật liệu xây dựng". Structure is similar to MOC's — a
listing page with the latest bulletin linked first. This scraper reuses
the MOC parsers (the table shape is identical across most provinces'
DOC sites — they're all based on the same Vietnamese construction
procurement template) but sets `province='Hanoi'` on every row.
"""

from __future__ import annotations

import logging
import re

from .base import BaseScraper, ScrapedPrice, ScrapeError
from .ministry import _parse_bulletin_html  # re-use identical table parser

logger = logging.getLogger(__name__)


_HANOI_LISTING_URL = "https://soxaydung.hanoi.gov.vn/thong-bao-gia-vat-lieu-xd"


class HanoiScraper(BaseScraper):
    province = "Hanoi"
    slug = "hanoi"

    def __init__(self, *, http_client=None) -> None:
        self._http = http_client

    async def scrape(self) -> list[ScrapedPrice]:
        client = await self._get_client()
        try:
            listing = await client.get(_HANOI_LISTING_URL, timeout=30.0)
            listing.raise_for_status()
            bulletin_url = _find_latest_hanoi_bulletin_url(listing.text)
            if bulletin_url is None:
                logger.warning("Hanoi scraper: no bulletin link found")
                return []

            bulletin = await client.get(bulletin_url, timeout=30.0)
            bulletin.raise_for_status()
            rows = _parse_bulletin_html(bulletin.text, source_url=bulletin_url)

            # Force the province to Hanoi (the parser defaults to 'Vietnam').
            return [
                ScrapedPrice(
                    raw_name=r.raw_name,
                    raw_unit=r.raw_unit,
                    price_vnd=r.price_vnd,
                    effective_date=r.effective_date,
                    province="Hanoi",
                    source_url=r.source_url,
                    attributes=r.attributes,
                )
                for r in rows
            ]
        except Exception as exc:
            raise ScrapeError(f"Hanoi scrape failed: {exc}") from exc

    async def _get_client(self):
        if self._http is not None:
            return self._http
        import httpx

        return httpx.AsyncClient(follow_redirects=True)


_HANOI_BULLETIN_RE = re.compile(r'href="([^"]*(?:thong-bao-gia|bao-gia)[^"]*)"', re.IGNORECASE)


def _find_latest_hanoi_bulletin_url(listing_html: str) -> str | None:
    match = _HANOI_BULLETIN_RE.search(listing_html)
    if match is None:
        return None
    href = match.group(1)
    if href.startswith("/"):
        return f"https://soxaydung.hanoi.gov.vn{href}"
    if href.startswith("http"):
        return href
    return f"https://soxaydung.hanoi.gov.vn/{href}"
