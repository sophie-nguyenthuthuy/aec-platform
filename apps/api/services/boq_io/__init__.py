"""BOQ Excel/PDF I/O for CostPulse estimates.

Three operations, one library-agnostic core:

  * `parse_boq_xlsx(content)` → list[BoqRow]   — Excel import.
  * `render_boq_xlsx(rows)`   → bytes          — Excel export.
  * `render_boq_pdf(estimate_name, rows)` → bytes — PDF export.

Shape `BoqRow` is the lingua franca — same shape we use for the API's
`BoqItemIn` schema, but unbound from Pydantic so the parser core stays
testable without bringing in the framework. The router maps `BoqRow`
↔ `BoqItemIn` at the boundary.

Format adapters lazy-import their heavy deps:

  * `openpyxl` (Excel) — pure Python, but slow to import; lazy keeps
    HTML-only request paths fast.
  * `reportlab` (PDF) — same story. Also: reportlab pulls in PIL on
    first use, which we'd rather defer past app startup.
"""

from __future__ import annotations

from .core import (
    BoqIOError,
    BoqRow,
    detect_columns,
    rows_to_grid,
)
from .pdf import render_boq_pdf
from .xlsx import parse_boq_xlsx, render_boq_xlsx

__all__ = [
    "BoqRow",
    "BoqIOError",
    "detect_columns",
    "rows_to_grid",
    "parse_boq_xlsx",
    "render_boq_xlsx",
    "render_boq_pdf",
]
