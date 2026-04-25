"""TP. Hồ Chí Minh Department of Construction price scraper.

Source: soxaydung.hochiminhcity.gov.vn. HCMC publishes quarterly
(slightly slower cadence than Hanoi) and sometimes gates the full price
list behind a DOCX attachment. This scraper dispatches to the DOCX/PDF
parsers when the bulletin link is a binary attachment, and falls back
to the HTML-table path otherwise. Legacy .doc / .xls bulletins are
still logged and skipped — no parser for those yet.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from .base import BaseScraper, ScrapedPrice, ScrapeError
from .ministry import _parse_bulletin_html
from .parsers import parse_docx_bulletin, parse_pdf_bulletin

logger = logging.getLogger(__name__)


# Mirrors generic_province._BINARY_PARSERS — kept duplicated rather than
# imported to avoid a circular dep and to keep this file self-contained.
_BINARY_PARSERS = {
    ".docx": (parse_docx_bulletin, "docx"),
    ".pdf": (parse_pdf_bulletin, "pdf"),
}


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

            ext = _ext_of(bulletin_url)
            if ext in _BINARY_PARSERS:
                parser, fmt = _BINARY_PARSERS[ext]
                bulletin = await client.get(bulletin_url, timeout=60.0)
                bulletin.raise_for_status()
                logger.info("HCMC scraper: parsing %s bulletin (%s)", fmt, bulletin_url)
                return parser(
                    bulletin.content,
                    source_url=bulletin_url,
                    province="HCMC",
                )
            if ext == ".doc":
                logger.warning(
                    "HCMC scraper: legacy .doc bulletin (%s); skipping — no parser for binary Word format yet",
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


def _ext_of(url: str) -> str:
    """Return the lower-cased extension of the URL's path (incl. dot), or ''.

    Strips query and fragment so '/foo.pdf?download=1' → '.pdf'.
    """
    path = urlparse(url).path
    dot = path.rfind(".")
    if dot == -1:
        return ""
    return path[dot:].lower()


_HCMC_BULLETIN_RE = re.compile(r'href="([^"]*(?:thong-bao-gia|cong-bo-gia)[^"]*)"', re.IGNORECASE)


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
