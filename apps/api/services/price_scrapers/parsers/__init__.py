"""Bulletin parsers — extract `ScrapedPrice` rows from various formats.

Most provinces publish HTML tables (handled by `ministry._parse_bulletin_html`),
but many publish only as DOCX or PDF attachments. This package splits the
work into:

  * `table` — library-agnostic core: given a list-of-lists of cell strings,
    detect which columns hold material name / unit / price, and emit
    `ScrapedPrice` rows. Fully unit-testable with no external deps.
  * `docx` — thin adapter. Lazy-imports `python-docx`, extracts tables,
    hands cells to `table.extract_prices_from_table`.
  * `pdf`  — thin adapter. Lazy-imports `pdfplumber`, extracts tables,
    hands cells to the same core.

Adding a new format (XLSX, CSV, OpenOffice ODT, …) is one thin adapter
module; the column-detection + row-mapping logic doesn't change.
"""
from __future__ import annotations

from .docx import parse_docx_bulletin
from .pdf import parse_pdf_bulletin
from .table import (
    ColumnMap,
    detect_columns,
    extract_effective_date,
    extract_prices_from_table,
)

__all__ = [
    "ColumnMap",
    "detect_columns",
    "extract_effective_date",
    "extract_prices_from_table",
    "parse_docx_bulletin",
    "parse_pdf_bulletin",
]
