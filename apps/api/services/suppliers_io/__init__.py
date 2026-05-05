"""Supplier batch-import.

Mirrors `services.boq_io`'s split:

  * `core` — library-agnostic header detection + row coercion. Pure
    Python; testable without openpyxl installed.
  * `xlsx` — thin openpyxl adapter (lazy-imported by callers).
  * `csv`  — thin stdlib `csv` adapter.

Both adapters return `list[SupplierRow]` ready to insert. The router
de-duplicates on `(organization_id, lower(name))` so a re-import is
idempotent — the buyer can edit their spreadsheet and re-upload
without manual cleanup.
"""

from __future__ import annotations

from .core import SupplierImportError, SupplierRow, coerce_row, detect_columns
from .csv_adapter import parse_suppliers_csv
from .export import render_suppliers_csv, render_suppliers_xlsx
from .xlsx import parse_suppliers_xlsx

__all__ = [
    "SupplierImportError",
    "SupplierRow",
    "coerce_row",
    "detect_columns",
    "parse_suppliers_csv",
    "parse_suppliers_xlsx",
    "render_suppliers_csv",
    "render_suppliers_xlsx",
]
