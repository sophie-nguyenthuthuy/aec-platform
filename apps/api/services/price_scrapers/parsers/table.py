"""Library-agnostic price-table extraction.

Given a list of rows (each row a list of cell strings) this module:

  1. Detects the header row by looking for Vietnamese / English column
     names ("Tên", "Đơn vị", "Giá", …). Provinces vary in phrasing so we
     match against a set of aliases per column.
  2. Maps subsequent rows to `ScrapedPrice` using the detected column
     indices.
  3. Skips rows whose price cell isn't parseable or whose name is blank
     (section headers / footer notes) — logs at DEBUG so a silent drop
     still leaves breadcrumbs.

The `effective_date` is extracted from a sibling `text` parameter
(typically the document's full text) — bulletins title themselves
"Thông báo giá tháng MM/YYYY" and the date lives above the table, not
in it.

This module has no external dependencies, so every piece of extraction
logic can be exercised with plain list-of-lists input.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from ..base import ScrapedPrice

logger = logging.getLogger(__name__)


# ---------- Column detection ----------

# Vietnamese column aliases. Lower-cased and ASCII-folded (diacritics
# stripped) before matching. Listed in priority order — the first alias
# hit wins, so "đơn giá" beats the more general "giá" when both appear.
_NAME_ALIASES: tuple[str, ...] = (
    "ten vat lieu", "ten vat tu", "ten vat", "mo ta",
    "ten hang", "chung loai", "danh muc", "vat lieu",
    "material", "description", "item",
    # Bare "Tên" — listed last (lowest priority) so longer variants win
    # when both are present. Bulletins do occasionally just say "Tên".
    "ten",
)

_UNIT_ALIASES: tuple[str, ...] = (
    "don vi tinh", "don vi", "dvt", "dv tinh",
    "unit", "uom",
)

_PRICE_ALIASES: tuple[str, ...] = (
    "don gia truoc thue", "don gia", "gia (vnd)", "gia vnd",
    "gia", "don-gia",
    "price", "unit price",
)


_DIACRITICS = str.maketrans(
    "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
    "ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ",
    "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    "AAAAAAAAAAAAAAAAAEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYYD",
)


def _fold(s: str) -> str:
    """Lower + strip diacritics + collapse whitespace. Used for header matching only."""
    return " ".join(s.translate(_DIACRITICS).lower().split())


@dataclass(frozen=True)
class ColumnMap:
    """Resolved column indices for the three fields we care about."""

    name: int
    unit: int
    price: int

    def as_dict(self) -> dict[str, int]:
        return {"name": self.name, "unit": self.unit, "price": self.price}


def detect_columns(header_row: list[str]) -> ColumnMap | None:
    """Return indices for name / unit / price in `header_row`.

    Returns `None` if any of the three is missing — caller should treat
    that as "not the header row yet" and keep scanning.
    """
    folded = [_fold(c) for c in header_row]

    name_idx = _first_match(folded, _NAME_ALIASES)
    unit_idx = _first_match(folded, _UNIT_ALIASES)
    price_idx = _first_match(folded, _PRICE_ALIASES)

    if name_idx is None or unit_idx is None or price_idx is None:
        return None
    # All three must be distinct — defensive against mis-headers like
    # ("Tên", "Giá", "Giá") where one of them would shadow the other.
    if len({name_idx, unit_idx, price_idx}) != 3:
        return None
    return ColumnMap(name=name_idx, unit=unit_idx, price=price_idx)


def _first_match(folded_headers: list[str], aliases: tuple[str, ...]) -> int | None:
    """Return the column index whose folded header contains any of `aliases`."""
    for alias in aliases:
        for idx, cell in enumerate(folded_headers):
            # `in` not `==` — real-world headers often include extra text
            # like "ĐVT (đơn vị tính)" or "Đơn giá (VND, chưa thuế)".
            if alias in cell:
                return idx
    return None


# ---------- Row extraction ----------


def extract_prices_from_table(
    rows: list[list[str]],
    *,
    effective_date: date,
    source_url: str | None,
    province: str,
) -> list[ScrapedPrice]:
    """Scan `rows` for a header, then yield one ScrapedPrice per data row.

    `rows` is whatever the upstream adapter produced — a DOCX table, a
    PDF page-table, etc. Each inner list is a row; each entry a cell
    as a plain string.
    """
    header_idx: int | None = None
    cols: ColumnMap | None = None

    for i, row in enumerate(rows):
        cols = detect_columns(row)
        if cols is not None:
            header_idx = i
            break

    if cols is None or header_idx is None:
        logger.info(
            "parser.table: no header row found in %d rows (province=%s)",
            len(rows), province,
        )
        return []

    scraped: list[ScrapedPrice] = []
    max_idx = max(cols.name, cols.unit, cols.price)

    for row in rows[header_idx + 1:]:
        # Skip ragged rows (merged cells / section separators).
        if len(row) <= max_idx:
            continue

        raw_name = (row[cols.name] or "").strip()
        raw_unit = (row[cols.unit] or "").strip()
        price_cell = (row[cols.price] or "").strip()

        if not raw_name or not price_cell:
            continue

        try:
            price = _parse_vnd(price_cell)
        except InvalidOperation:
            logger.debug(
                "parser.table: unparseable price %r for %r (province=%s)",
                price_cell, raw_name, province,
            )
            continue

        if price <= 0:
            continue

        scraped.append(
            ScrapedPrice(
                raw_name=raw_name,
                raw_unit=raw_unit,
                price_vnd=price,
                effective_date=effective_date,
                province=province,
                source_url=source_url,
            )
        )

    logger.info(
        "parser.table: extracted %d rows (province=%s, header_row=%d)",
        len(scraped), province, header_idx,
    )
    return scraped


_VND_CLEAN_RE = re.compile(r"[^\d]")


def _parse_vnd(s: str) -> Decimal:
    """'1.234.567', '1,234,567', '2 000 000 đ' → Decimal. Raises InvalidOperation on no digits."""
    cleaned = _VND_CLEAN_RE.sub("", s)
    if not cleaned:
        raise InvalidOperation(f"no digits in {s!r}")
    return Decimal(cleaned)


# ---------- Effective date ----------

# "Thông báo giá tháng 03/2026", "Công bố giá Q2/2025", "tháng 12/2025" etc.
_MONTH_YEAR_RE = re.compile(r"(?:tháng|thang|month)?\s*(\d{1,2})\s*[-/]\s*(\d{4})", re.IGNORECASE)


def extract_effective_date(text: str) -> date | None:
    """Find 'tháng MM/YYYY' or 'MM/YYYY' in `text`. Returns None if none valid."""
    match = _MONTH_YEAR_RE.search(text or "")
    if match is None:
        return None
    try:
        m, y = int(match.group(1)), int(match.group(2))
    except ValueError:
        return None
    if not (1 <= m <= 12):
        return None
    # Plausible bulletin-year window — we ingest historical and the odd
    # "next month" bulletin, but not 1970 or 3000.
    if not (2015 <= y <= date.today().year + 1):
        return None
    return date(y, m, 1)
