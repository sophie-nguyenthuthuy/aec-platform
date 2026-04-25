"""Generic provincial DOC scraper.

Most of Vietnam's 63 provincial Departments of Construction publish
monthly price bulletins under a near-identical CMS template:

  * A listing page ("Thông báo giá VLXD") whose first link points to
    the latest monthly or quarterly bulletin.
  * A bulletin page with an HTML table of (name, unit, price) rows.
  * The bulletin title embeds "tháng MM/YYYY" so the month is extractable.

This lets us share 95% of the scraping logic across provinces and
parameterise per-province config (URL, canonical province name, slug).
Provinces that diverge (HCMC publishes only DOCX, some provinces gate
the listing behind a CAPTCHA) get a bespoke class in their own module.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from .base import BaseScraper, ScrapedPrice, ScrapeError
from .ministry import _parse_bulletin_html
from .parsers import parse_docx_bulletin, parse_pdf_bulletin

logger = logging.getLogger(__name__)


# Binary attachments we know how to parse. Maps the file extension
# (lower-case, including dot) to the (parser, format-tag) pair. Formats
# we *don't* yet handle (.doc legacy Word, .xls/.xlsx Excel) are left
# out and fall through to the skip-and-log branch.
_BINARY_PARSERS = {
    ".docx": (parse_docx_bulletin, "docx"),
    ".pdf": (parse_pdf_bulletin, "pdf"),
}


@dataclass(frozen=True)
class ProvinceConfig:
    """Scraper configuration for a single province."""

    slug: str
    """Machine slug, e.g. 'danang', 'nghe-an'."""

    province: str
    """Canonical province name as stored in material_prices.province.
    Use English where there's a common English form (Hanoi, HCMC),
    otherwise keep the Vietnamese (Đà Nẵng → 'Da Nang' is acceptable)."""

    listing_url: str
    """Full URL of the 'Thông báo giá' listing page.

    Use the `PENDING_URL` sentinel for provinces whose page we haven't
    verified yet — the scraper will log + skip instead of making an
    HTTP request to a guessed URL."""

    bulletin_link_re: str = r"(?:thong-bao-gia|bao-gia|cong-bo-gia)"
    """Regex (case-insensitive) that must appear in the bulletin link's
    href. Tweak per-province when their link text diverges."""


PENDING_URL = "PENDING"


class GenericProvinceScraper(BaseScraper):
    """Scraper driven entirely by a `ProvinceConfig` — no code per province.

    Adding a province: append its `ProvinceConfig` to `provinces.ALL` and
    the registry will auto-wire it on next import. No new class needed
    unless the province's DOC site diverges from the template.
    """

    def __init__(self, config: ProvinceConfig, *, http_client=None) -> None:
        self._config = config
        self._http = http_client

        # Populate BaseScraper fields so the registry key + repr work.
        self.slug = config.slug
        self.province = config.province

    async def scrape(self) -> list[ScrapedPrice]:
        if self._config.listing_url == PENDING_URL:
            logger.info("scraper.generic[%s]: listing URL not yet verified; skipping", self._config.slug)
            return []

        client = await self._get_client()
        try:
            listing = await client.get(self._config.listing_url, timeout=30.0)
            listing.raise_for_status()
            bulletin_url = _find_first_matching_link(
                listing.text,
                link_re=self._config.bulletin_link_re,
                base_url=_base_of(self._config.listing_url),
            )
            if bulletin_url is None:
                logger.warning("scraper.generic[%s]: no bulletin link found", self._config.slug)
                return []

            ext = _ext_of(bulletin_url)
            if ext in _BINARY_PARSERS:
                parser, fmt = _BINARY_PARSERS[ext]
                bulletin = await client.get(bulletin_url, timeout=60.0)
                bulletin.raise_for_status()
                logger.info(
                    "scraper.generic[%s]: parsing %s bulletin (%s)",
                    self._config.slug,
                    fmt,
                    bulletin_url,
                )
                return parser(
                    bulletin.content,
                    source_url=bulletin_url,
                    province=self._config.province,
                )
            if ext in {".doc", ".xls", ".xlsx"}:
                logger.warning(
                    "scraper.generic[%s]: latest bulletin is a %s attachment (%s); "
                    "skipping — no parser for this format yet",
                    self._config.slug,
                    ext,
                    bulletin_url,
                )
                return []

            bulletin = await client.get(bulletin_url, timeout=30.0)
            bulletin.raise_for_status()
            rows = _parse_bulletin_html(bulletin.text, source_url=bulletin_url)

            # Parser defaults to province='Vietnam' — override per province.
            return [
                ScrapedPrice(
                    raw_name=r.raw_name,
                    raw_unit=r.raw_unit,
                    price_vnd=r.price_vnd,
                    effective_date=r.effective_date,
                    province=self._config.province,
                    source_url=r.source_url,
                    attributes=r.attributes,
                )
                for r in rows
            ]
        except Exception as exc:
            raise ScrapeError(f"generic scrape failed for {self._config.slug}: {exc}") from exc

    async def _get_client(self):
        if self._http is not None:
            return self._http
        import httpx

        return httpx.AsyncClient(follow_redirects=True)


# ---------- helpers (pulled out for unit testing) ----------


def _base_of(url: str) -> str:
    """Return the scheme + netloc of `url` so we can resolve relative hrefs."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _ext_of(url: str) -> str:
    """Return the lower-cased extension of the URL's path (incl. dot), or ''.

    Strips query and fragment so '/foo.pdf?download=1' → '.pdf'.
    """
    path = urlparse(url).path
    dot = path.rfind(".")
    if dot == -1:
        return ""
    return path[dot:].lower()


def _find_first_matching_link(html: str, *, link_re: str, base_url: str) -> str | None:
    """Return the first href in `html` whose value matches `link_re`, rewritten absolute."""
    # We scan all hrefs and pick the first that matches the per-province pattern
    # — more forgiving than ministry.py's strict table-driven regex.
    pattern = re.compile(
        r'href="([^"]+)"',
        re.IGNORECASE,
    )
    link_matcher = re.compile(link_re, re.IGNORECASE)

    for match in pattern.finditer(html):
        href = match.group(1)
        if link_matcher.search(href):
            return urljoin(base_url + "/", href.lstrip("/"))
    return None
