"""CSV adapter for supplier import.

`csv` is in the stdlib; no lazy-import dance needed. We accept either
a true `text/csv` upload (UTF-8, comma-delimited) or one with a BOM
(common when buyers export from Excel as "CSV UTF-8"). The Sniffer
guesses the delimiter so `;`-separated files (common in VN locales
where comma is the decimal separator) just work.
"""

from __future__ import annotations

import csv
import io

from .core import SupplierImportError, SupplierRow, coerce_row, detect_columns


def parse_suppliers_csv(content: bytes) -> list[SupplierRow]:
    """Parse a CSV upload (text/csv) into supplier rows.

    Strategy:
      1. Decode with `utf-8-sig` so Excel's UTF-8-with-BOM is handled.
         If decode fails we fall back to `cp1258` (common VN Excel
         locale) — buyers exporting from a non-Unicode-aware tool.
      2. Sniff the delimiter (comma vs. semicolon vs. tab).
      3. First non-empty row is the header; body rows follow.

    Raises `SupplierImportError` on malformed input or missing name
    column.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("cp1258")  # Vietnamese legacy codepage
        except UnicodeDecodeError as exc:
            raise SupplierImportError(f"could not decode CSV — not UTF-8 or cp1258: {exc}") from exc

    if not text.strip():
        raise SupplierImportError("CSV is empty")

    # Sniff with a 4 KB sample — enough to spot the delimiter without
    # paying the cost of scanning a giant file.
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        # Sniff failure on tiny/unusual files — default to comma.
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect=dialect)
    rows: list[list[str]] = []
    for r in reader:
        if not any((c or "").strip() for c in r):
            continue
        rows.append([(c or "") for c in r])

    if not rows:
        raise SupplierImportError("CSV has no rows")

    header, *body = rows
    cols = detect_columns(header)
    out: list[SupplierRow] = []
    for line in body:
        row = coerce_row(line, cols)
        if row is not None:
            out.append(row)
    return out
