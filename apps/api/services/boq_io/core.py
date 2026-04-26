"""Library-agnostic BOQ I/O core.

Three responsibilities:

  1. `BoqRow` — the row shape we exchange across the import/export
     boundary. Mirrors `schemas.BoqItemIn` minus the Pydantic baggage,
     so the parser core has no FastAPI / Pydantic import cost.
  2. `detect_columns(header_row)` — given a list of header cells from
     the first row of a user-uploaded xlsx, figure out which column
     index holds description / unit / quantity / unit_price / total /
     code / material_code. Vietnamese + English aliases supported,
     diacritics-insensitive matching.
  3. `rows_to_grid(rows)` — given a list of `BoqRow`, produce a
     header + body 2D array that the xlsx and pdf renderers both
     consume. Keeping this in one place means the two formats
     guarantee column-parity.

This module has no third-party deps — it can be exercised with plain
list-of-list input, no Excel/PDF libraries needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class BoqIOError(Exception):
    """Raised when an upload can't be parsed (no recognisable header,
    corrupt file, etc.). Routers turn this into a 400."""


# ---------- Row shape ----------


@dataclass(frozen=True)
class BoqRow:
    """One BOQ line — the import/export interchange format.

    `code` is the user-facing line number ("1.2.3"); `material_code`
    matches our internal catalogue (e.g. `CONC_C30`). They're separate
    columns because users sometimes provide just one.
    """

    description: str
    code: str | None = None
    unit: str | None = None
    quantity: Decimal | None = None
    unit_price_vnd: Decimal | None = None
    total_price_vnd: Decimal | None = None
    material_code: str | None = None
    sort_order: int = 0


# ---------- Column detection ----------

# Folded (lower + ASCII) aliases per logical column. Order = priority;
# `_first_match` returns the first cell whose folded text *contains*
# any alias, so put the most specific phrases first.
_DESC_ALIASES: tuple[str, ...] = (
    "mo ta cong viec",
    "mo ta",
    "ten cong viec",
    "ten vat lieu",
    "ten vat",
    "ten hang",
    "noi dung",
    "description",
    "item",
    "name",
)
_CODE_ALIASES: tuple[str, ...] = (
    "ma cong viec",
    "stt",  # vietnamese "số thứ tự" / line-number
    "code",
    "no.",
    "no ",
    "#",
)
_UNIT_ALIASES: tuple[str, ...] = (
    "don vi tinh",
    "don vi",
    "dvt",
    "unit",
    "uom",
)
_QTY_ALIASES: tuple[str, ...] = (
    "khoi luong",
    "so luong",
    "quantity",
    "qty",
    "kl",
)
_UNIT_PRICE_ALIASES: tuple[str, ...] = (
    "don gia",
    "unit price",
    "rate",
    "price",
)
_TOTAL_ALIASES: tuple[str, ...] = (
    "thanh tien",
    "total",
    "amount",
    "sub total",
)
_MATERIAL_CODE_ALIASES: tuple[str, ...] = (
    "ma vat lieu",
    "material code",
    "ma vt",
)


_DIACRITICS = str.maketrans(
    "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
    "ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ",
    "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    "AAAAAAAAAAAAAAAAAEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYYD",
)


def _fold(s: str) -> str:
    """Lower + strip diacritics + collapse whitespace. Header-match only."""
    return " ".join(s.translate(_DIACRITICS).lower().split())


@dataclass(frozen=True)
class ColumnMap:
    """Resolved header indices.

    `description` is the only mandatory column; everything else is
    optional. A spreadsheet with just descriptions still imports —
    pricing can be filled in later.
    """

    description: int
    code: int | None = None
    unit: int | None = None
    quantity: int | None = None
    unit_price_vnd: int | None = None
    total_price_vnd: int | None = None
    material_code: int | None = None


def detect_columns(header_row: list[object]) -> ColumnMap | None:
    """Return a ColumnMap, or None if `description` can't be located.

    `header_row` cells may be any type (xlsx returns str / int / None
    depending on cell formatting); we coerce to str defensively.
    """
    folded = [_fold(str(c)) if c is not None else "" for c in header_row]

    desc_idx = _first_match(folded, _DESC_ALIASES)
    if desc_idx is None:
        return None

    return ColumnMap(
        description=desc_idx,
        code=_first_match(folded, _CODE_ALIASES, exclude=[desc_idx]),
        unit=_first_match(folded, _UNIT_ALIASES, exclude=[desc_idx]),
        quantity=_first_match(folded, _QTY_ALIASES, exclude=[desc_idx]),
        unit_price_vnd=_first_match(folded, _UNIT_PRICE_ALIASES, exclude=[desc_idx]),
        total_price_vnd=_first_match(folded, _TOTAL_ALIASES, exclude=[desc_idx]),
        material_code=_first_match(folded, _MATERIAL_CODE_ALIASES, exclude=[desc_idx]),
    )


def _first_match(
    folded_headers: list[str],
    aliases: tuple[str, ...],
    *,
    exclude: list[int] | None = None,
) -> int | None:
    """First column whose folded header contains any alias, skipping `exclude`.

    `exclude` lets the caller prevent the same physical column being
    claimed twice — e.g. the description-column header "Tên / Mô tả"
    contains "mo ta" AND "ten" and could otherwise match both
    description and the (less-specific) name aliases.
    """
    skip = set(exclude or [])
    for alias in aliases:
        for idx, cell in enumerate(folded_headers):
            if idx in skip:
                continue
            if alias in cell:
                return idx
    return None


# ---------- Row → grid (export) ----------


# Canonical column order for export. Matches the order users expect on
# a printed BOQ — description first, then quantity / unit / price /
# total. Code and material_code come last because they're metadata.
_EXPORT_HEADERS: tuple[str, ...] = (
    "Code",
    "Description",
    "Unit",
    "Quantity",
    "Unit price (VND)",
    "Total (VND)",
    "Material code",
)


def rows_to_grid(rows: list[BoqRow]) -> tuple[list[str], list[list[object]]]:
    """Produce (header_cells, body_rows) for the renderers.

    Body cells are typed: numbers as `float` (xlsx then formats them);
    strings remain strings; missing values are empty strings (not None)
    so renderers don't have to handle the None-vs-empty distinction.
    """
    header = list(_EXPORT_HEADERS)
    body: list[list[object]] = []
    for r in rows:
        body.append(
            [
                r.code or "",
                r.description,
                r.unit or "",
                _decimal_to_float(r.quantity),
                _decimal_to_float(r.unit_price_vnd),
                _decimal_to_float(r.total_price_vnd or _compute_total(r)),
                r.material_code or "",
            ]
        )
    return header, body


def _decimal_to_float(d: Decimal | None) -> object:
    """Decimals → floats for xlsx (which doesn't accept Decimal). None → ''."""
    if d is None:
        return ""
    try:
        return float(d)
    except (TypeError, ValueError):
        return ""


def _compute_total(row: BoqRow) -> Decimal | None:
    """Multiply qty × unit_price when both are set and total isn't.

    Lots of imports come without a `total_price_vnd` column — we still
    want the export to show the total. Compute on the fly so the round
    trip "import → export" produces a complete BOQ.
    """
    if row.quantity is None or row.unit_price_vnd is None:
        return None
    try:
        return row.quantity * row.unit_price_vnd
    except (InvalidOperation, ArithmeticError):
        return None


# ---------- Cell coercion (import) ----------


_NUM_CLEAN_RE = re.compile(r"[^\d\-.,]")


def coerce_decimal(cell: object) -> Decimal | None:
    """Coerce a spreadsheet cell to Decimal; return None on empty/garbage.

    Excel cells arrive as `int`, `float`, `str`, or `None` depending on
    the original formatting. Strings often have currency markers ("VND",
    "đ"), thousand separators, and stray whitespace — we strip them
    rather than rejecting the row.
    """
    if cell is None:
        return None
    if isinstance(cell, (int, float)):
        return Decimal(str(cell))
    if isinstance(cell, Decimal):
        return cell
    s = str(cell).strip()
    if not s:
        return None
    cleaned = _NUM_CLEAN_RE.sub("", s)
    # Normalise decimal separator: Vietnamese spreadsheets often use
    # `1.234.567,89`. If we see both `.` and `,`, treat the LAST one
    # as the decimal point and strip the others as thousands.
    if cleaned.count(",") and cleaned.count("."):
        decimal_marker = max(cleaned.rfind(","), cleaned.rfind("."))
        # Remove every separator except the chosen decimal marker.
        cleaned = (
            cleaned[:decimal_marker].replace(",", "").replace(".", "")
            + "."
            + cleaned[decimal_marker + 1 :].replace(",", "").replace(".", "")
        )
    elif cleaned.count(",") and not cleaned.count("."):
        # Pure-comma form — could be thousands ("1,234") or decimal
        # ("1,5"). Heuristic: 3-digit grouping after every comma →
        # thousands; otherwise decimal.
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", cleaned):
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1:
        # Multiple dots, no commas → vietnamese thousands ("1.234.567").
        cleaned = cleaned.replace(".", "")
    if not cleaned or cleaned in ("-", ".", "-."):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def coerce_str(cell: object) -> str | None:
    """Coerce a cell to a stripped str; None for empty."""
    if cell is None:
        return None
    s = str(cell).strip()
    return s or None
