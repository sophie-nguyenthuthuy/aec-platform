"""PDF bulletin adapter — lazy-imports `pdfplumber`, feeds tables to the core.

Provincial PDF bulletins come in two flavours:

  * Table-layer PDFs — generated from Word / Excel, so the table cells
    are first-class objects. `pdfplumber.Page.extract_tables()` handles
    these cleanly.
  * Scanned PDFs — images wrapped in PDF. These have no extractable
    text; we'd need OCR to handle them. For now we log + skip and leave
    that for a future "B.1.1 OCR fallback" if the manual-verification
    backlog (B.3) turns up enough of them to matter.

We walk every page, collect every table, and concatenate rows into a
single list before dispatching to the core. Bulletins occasionally
split a single material category across pages (e.g. "Thép cuộn" spans
pages 2-3 before "Xi măng" starts on page 4) — keeping rows in page
order preserves the original layout.
"""

from __future__ import annotations

import io
import logging
from datetime import date

from ..base import ScrapedPrice, ScrapeError
from .table import extract_effective_date, extract_prices_from_table

logger = logging.getLogger(__name__)


def parse_pdf_bulletin(
    content: bytes,
    *,
    source_url: str,
    province: str,
) -> list[ScrapedPrice]:
    """Extract price rows from a PDF bulletin's embedded tables."""
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover — deployed env always has it
        raise ScrapeError("pdfplumber not installed; cannot parse .pdf bulletins") from exc

    rows: list[list[str]] = []
    all_text_parts: list[str] = []

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text:
                    all_text_parts.append(text)
                for table in page.extract_tables() or []:
                    # pdfplumber returns cells as str | None; normalise.
                    rows.extend([(c or "").strip() for c in row] for row in table)
    except Exception as exc:
        raise ScrapeError(f"could not open .pdf content: {exc}") from exc

    if not rows:
        logger.warning(
            "parser.pdf[%s]: no tables found — likely a scanned (image) PDF",
            province,
        )
        return []

    full_text = "\n".join(all_text_parts)
    effective = extract_effective_date(full_text) or date.today()

    scraped = extract_prices_from_table(
        rows,
        effective_date=effective,
        source_url=source_url,
        province=province,
    )
    logger.info(
        "parser.pdf[%s]: parsed %d rows from %d total table rows across all pages",
        province,
        len(scraped),
        len(rows),
    )
    return scraped
