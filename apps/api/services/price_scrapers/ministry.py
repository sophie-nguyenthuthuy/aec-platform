"""Ministry of Construction (Bộ Xây Dựng) price-index scraper.

MOC publishes construction-price indices + policy guidance at
xaydung.gov.vn. The actual per-material prices live at the provincial
DOCs, but MOC aggregates monthly "chỉ số giá xây dựng" (construction
cost indices) that we treat as a national baseline when a province
hasn't published yet that month.

This scraper fetches the MOC "Thông báo giá" listing page, follows the
latest monthly bulletin, and parses the embedded HTML table. When the
bulletin is only available as a DOCX/PDF attachment we log + skip;
provincial scrapers pick up the slack.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from .base import BaseScraper, ScrapedPrice, ScrapeError

logger = logging.getLogger(__name__)


_MOC_LISTING_URL = "https://moc.gov.vn/vn/thong-bao-gia-vat-lieu-xay-dung.html"


class MinistryOfConstructionScraper(BaseScraper):
    province = "Vietnam"  # Treated as the national fallback row.
    slug = "moc"

    def __init__(self, *, http_client=None) -> None:
        # `http_client` is injected for tests. In prod we lazy-import
        # httpx so this module can be imported without network deps.
        self._http = http_client

    async def scrape(self) -> list[ScrapedPrice]:
        client = await self._get_client()
        try:
            listing = await client.get(_MOC_LISTING_URL, timeout=30.0)
            listing.raise_for_status()
            bulletin_url = _find_latest_bulletin_url(listing.text)
            if bulletin_url is None:
                logger.warning("MOC scraper: no bulletin link found on listing")
                return []

            bulletin = await client.get(bulletin_url, timeout=30.0)
            bulletin.raise_for_status()
            return _parse_bulletin_html(bulletin.text, source_url=bulletin_url)
        except Exception as exc:  # httpx.HTTPError, parse errors, etc.
            raise ScrapeError(f"MOC scrape failed: {exc}") from exc

    async def _get_client(self):
        if self._http is not None:
            return self._http
        import httpx

        return httpx.AsyncClient(follow_redirects=True)


# ---------- Parsers (pulled out for unit testing) ----------

_BULLETIN_LINK_RE = re.compile(
    r'href="([^"]*(?:thong-bao-gia|thongbao-gia)[^"]*\.html?)"',
    re.IGNORECASE,
)
_MONTH_YEAR_RE = re.compile(r"(\d{1,2})\s*[-/]\s*(\d{4})")
_ROW_RE = re.compile(
    r"<tr[^>]*>\s*"
    r"<td[^>]*>([^<]+)</td>\s*"  # raw_name
    r"<td[^>]*>([^<]+)</td>\s*"  # unit
    r"<td[^>]*>([^<]+)</td>\s*"  # price
    r"</tr>",
    re.IGNORECASE | re.DOTALL,
)


def _find_latest_bulletin_url(listing_html: str) -> str | None:
    """Return the first bulletin link on the listing page (assumed newest-first)."""
    match = _BULLETIN_LINK_RE.search(listing_html)
    if match is None:
        return None
    href = match.group(1)
    if href.startswith("/"):
        return f"https://moc.gov.vn{href}"
    return href


def _parse_bulletin_html(html: str, *, source_url: str) -> list[ScrapedPrice]:
    """Extract (name, unit, price) triples from the bulletin table."""
    effective = _extract_effective_date(html) or date.today()
    rows: list[ScrapedPrice] = []

    for match in _ROW_RE.finditer(html):
        raw_name = match.group(1).strip()
        raw_unit = match.group(2).strip()
        price_str = match.group(3).strip()

        try:
            price = _parse_vnd(price_str)
        except InvalidOperation:
            logger.debug("MOC: unparseable price %r in row %r", price_str, raw_name)
            continue

        if not raw_name or price <= 0:
            continue

        rows.append(
            ScrapedPrice(
                raw_name=raw_name,
                raw_unit=raw_unit,
                price_vnd=price,
                effective_date=effective,
                province="Vietnam",
                source_url=source_url,
            )
        )

    logger.info("MOC: parsed %d price rows from bulletin", len(rows))
    return rows


def _extract_effective_date(html: str) -> date | None:
    """MOC bulletins title themselves "Thông báo giá tháng 03/2026" etc."""
    match = _MONTH_YEAR_RE.search(html)
    if not match:
        return None
    try:
        m, y = int(match.group(1)), int(match.group(2))
        if 1 <= m <= 12 and 2015 <= y <= date.today().year + 1:
            return date(y, m, 1)
    except ValueError:
        pass
    return None


def _parse_vnd(s: str) -> Decimal:
    """'1.234.567' or '1,234,567' or '1 234 567 đ' → Decimal."""
    cleaned = re.sub(r"[^\d]", "", s)
    if not cleaned:
        raise InvalidOperation(f"no digits in {s!r}")
    return Decimal(cleaned)
