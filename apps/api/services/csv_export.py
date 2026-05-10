"""CSV export field escaper (cycle AA2).

Today the audit CSV, dead-letter CSV, deliveries CSV, and the
pinned-export CSV each call `csv.writer` with subtly different
`quoting=` flags and inconsistent formula-injection defenses.
This module is the single source of truth for shaping a single
field or a row of fields.

  escape_csv_field(value)    — escape one cell
  format_csv_row(values)     — format a list of cells as one CSV line
  format_iso_for_csv(dt)     — render a UTC datetime ISO-8601
  BOM_UTF8                   — leading byte-order mark for Excel

Excel formula-injection defense: leading `=`, `+`, `-`, `@` in a
cell get prefixed with a single quote. A field like `=cmd|'/c calc'`
in an exported audit row would otherwise execute when opened in
Excel — a real-world payload, not a theoretical concern.

Pure stdlib. The standard `csv` module would handle quoting but
does NOT prefix formula characters — that defense is reproduced
across every export path here.
"""

from __future__ import annotations

from datetime import UTC, datetime

# UTF-8 byte-order mark. Prepending this to the response body
# tells Excel to render the CSV as UTF-8 rather than CP1252 —
# without it, Vietnamese diacritics render as mojibake when a
# user opens the export in Excel-on-Windows.
BOM_UTF8 = "﻿"


# Cells starting with these characters are interpreted as formulas
# by Excel / Google Sheets / LibreOffice. Prefixing with a single
# quote forces text rendering. Defends against an attacker who
# controls e.g. a project name and exports an audit row.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def escape_csv_field(value: object) -> str:
    """Escape a single value as a CSV cell.

    Rules:
      * None → '' (empty cell, NOT the literal 'None').
      * Leading =/+/-/@ → prefixed with `'` (Excel formula-injection
        defense). Applied BEFORE the wrap so the prefix is inside
        the quoted region.
      * Embedded '"' → doubled to '""', whole field wrapped.
      * Embedded ',' / '\\n' / '\\r' → whole field wrapped.
      * Otherwise → returned as-is.

    Order matters: formula-prefix THEN quote-wrap. An attacker who
    smuggles `=cmd|"calc"` would otherwise bypass the prefix via
    the embedded quote.
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in _FORMULA_PREFIXES:
        text = "'" + text
    needs_quote = '"' in text or "," in text or "\n" in text or "\r" in text
    if needs_quote:
        escaped = text.replace('"', '""')
        return f'"{escaped}"'
    return text


def format_csv_row(values: list[object]) -> str:
    """Format a list of values as one CSV line (no trailing newline).

    Each value passes through `escape_csv_field`. The caller joins
    rows with `\\r\\n` per RFC 4180 (or `\\n` if Excel-on-Mac
    compatibility isn't a concern for the consumer surface).
    """
    return ",".join(escape_csv_field(v) for v in values)


def format_iso_for_csv(dt: datetime | None) -> str:
    """Format a datetime as ISO-8601 UTC for a CSV cell.

    None → ''. Naive datetimes are assumed UTC (the audit /
    webhook delivery columns are stored as tz-naive UTC per
    project convention). Aware datetimes are converted to UTC
    first.

    Format: `YYYY-MM-DDTHH:MM:SSZ` (no microseconds — operationally
    noise in a CSV that humans inspect; the second-precision
    matches the audit row plaintext export).
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        d = dt.replace(tzinfo=UTC)
    else:
        d = dt.astimezone(UTC)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")
