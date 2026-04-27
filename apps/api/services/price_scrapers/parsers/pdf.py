"""PDF bulletin adapter — lazy-imports `pdfplumber`, feeds tables to the core.

Provincial PDF bulletins come in two flavours:

  * Table-layer PDFs — generated from Word / Excel, so the table cells
    are first-class objects. `pdfplumber.Page.extract_tables()` handles
    these cleanly.
  * Scanned PDFs — images wrapped in PDF. `extract_tables()` returns
    nothing for these. We try a Tesseract OCR fallback — pages are
    rendered at 300dpi and OCR'd in Vietnamese — and reconstruct
    pseudo-table rows from line-aligned tokens. Provincial scans tend
    to be one rectangular table per page so this works for the common
    shape; deeply-formatted layouts will fail through to "0 rows" and
    surface as an unmatched-bulletin in B.2 drift telemetry.

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


# Tesseract render DPI for scanned-PDF fallback. 300 is the sweet spot
# for printed documents — lower drops accuracy on small numbers (the
# whole point of a price bulletin), higher ballons render time without
# meaningfully improving OCR. Adjustable via env if a province turns
# out to publish particularly low-resolution scans.
_OCR_DPI = 300

# Tesseract languages, in priority order. `vie` recognises Vietnamese
# diacritics (the material descriptions); `eng` covers numerics and
# the occasional English header. Tesseract takes them as a `+`-joined
# string and tries each.
_OCR_LANG = "vie+eng"


def parse_pdf_bulletin(
    content: bytes,
    *,
    source_url: str,
    province: str,
) -> list[ScrapedPrice]:
    """Extract price rows from a PDF bulletin's embedded tables.

    Falls through to OCR if the PDF has no extractable tables — most
    provincial DOCs publish either pure table-layer PDFs or pure scans,
    so we don't try to mix the two paths within one document.
    """
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
        # No table layer — try OCR. `_ocr_tables` returns ([], "") if the
        # OCR deps aren't installed or the OCR pass found nothing useful;
        # downstream behaviour (log + return 0 rows) is unchanged from
        # the pre-OCR code, so skipping OCR is degraded-but-safe.
        ocr_rows, ocr_text = _ocr_tables(content, province=province)
        if not ocr_rows:
            logger.warning(
                "parser.pdf[%s]: no tables found and OCR yielded no usable rows — manual verification needed",
                province,
            )
            return []
        rows = ocr_rows
        all_text_parts.append(ocr_text)

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


# ---------- OCR fallback ----------


def _ocr_tables(content: bytes, *, province: str) -> tuple[list[list[str]], str]:
    """Render a scanned PDF to images and OCR each page into pseudo-rows.

    Returns `(rows, full_text)` where `rows` mirrors the shape
    `extract_tables()` produces — list of rows, each a list of cell
    strings. Pseudo-cells are split on runs of 2+ spaces, which matches
    Tesseract's column-gap heuristic on tabular layouts. The price
    bulletins we care about put name / unit / price in three columns
    with generous padding, so this lands the right cell boundaries
    on the typical case.

    `full_text` is the unfiltered OCR output, used by
    `extract_effective_date` to find the "tháng MM/YYYY" banner.

    Returns `([], "")` when:
      * pytesseract or pdf2image is missing (logged).
      * The system tesseract binary is missing or vie traineddata isn't
        installed (TesseractError, logged).
      * OCR ran but every page came back empty / tokens were too sparse
        to look like a table.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError:
        # Either dep missing → silently degrade. We log at INFO rather
        # than WARNING because absent OCR is the *expected* state in
        # local dev / CI; only prod is supposed to have the binaries.
        logger.info(
            "parser.pdf[%s]: OCR deps not installed (pytesseract / pdf2image); skipping",
            province,
        )
        return [], ""

    try:
        images = convert_from_bytes(content, dpi=_OCR_DPI)
    except Exception as exc:
        logger.warning(
            "parser.pdf[%s]: pdf2image failed (poppler missing?): %s",
            province,
            exc,
        )
        return [], ""

    rows: list[list[str]] = []
    full_text_parts: list[str] = []
    try:
        for page_num, image in enumerate(images, start=1):
            text = pytesseract.image_to_string(image, lang=_OCR_LANG)
            full_text_parts.append(text)
            page_rows = _split_ocr_text_into_rows(text)
            logger.debug(
                "parser.pdf[%s]: OCR page %d → %d candidate rows",
                province,
                page_num,
                len(page_rows),
            )
            rows.extend(page_rows)
    except Exception as exc:
        # pytesseract.TesseractError, missing language data, etc.
        logger.warning("parser.pdf[%s]: tesseract failed: %s", province, exc)
        return [], ""

    if rows:
        logger.info(
            "parser.pdf[%s]: OCR fallback produced %d candidate rows from %d pages",
            province,
            len(rows),
            len(images),
        )
    return rows, "\n".join(full_text_parts)


def _split_ocr_text_into_rows(text: str) -> list[list[str]]:
    """Tesseract output → list of pseudo-table rows.

    Splits on newlines, then within each line splits on runs of 2+
    spaces. Single-space runs are *within* a cell (Vietnamese names
    contain spaces); 2+ spaces signal a column gap in a typeset table.

    Filters out:
      * Empty / whitespace-only lines.
      * Lines that produced exactly 1 cell — those are paragraph text,
        not table rows. The downstream `detect_columns` would skip them
        anyway, but pruning here keeps the row count diagnostic in the
        log line meaningful.
    """
    import re

    out: list[list[str]] = []
    for raw_line in text.splitlines():
        # Pre-trim: leading/trailing spaces don't carry layout info.
        line = raw_line.strip()
        if not line:
            continue
        cells = [c.strip() for c in re.split(r"\s{2,}", line)]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            out.append(cells)
    return out
