"""Library-agnostic supplier-row coercion.

Given a header row + body rows (each a list of cell strings), this
module:

  1. Detects which column holds `name`, `email`, `phone`, `categories`,
     `provinces` — supports Vietnamese + English aliases. `name` is
     the only required column; everything else is optional.
  2. Coerces each body row into a `SupplierRow` ready for DB insert.
  3. Skips blank rows (empty name) silently — common when buyers leave
     spacer rows in their spreadsheet.
  4. Raises `SupplierImportError` only for unrecoverable header
     mismatches (no name column found). Bad cell values within an
     otherwise-valid row are coerced to `None` rather than failing
     the whole upload.

This split lets unit tests exercise the column-detection + coercion
logic without openpyxl or the `csv` module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class SupplierImportError(Exception):
    """Header doesn't contain a recognisable `name` column.

    Caller should surface this to the buyer with the bad header row
    rendered so they can fix their spreadsheet — a 400 with the
    `expected aliases` list works well.
    """


@dataclass
class SupplierRow:
    """One row to insert as a `Supplier`."""

    name: str
    email: str | None = None
    phone: str | None = None
    categories: list[str] = field(default_factory=list)
    provinces: list[str] = field(default_factory=list)


# Diacritics fold map — same shape as the BOQ parser. Keep in sync
# manually; centralising would couple two unrelated modules.
_DIACRITICS = str.maketrans(
    "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
    "ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ",
    "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    "AAAAAAAAAAAAAAAAAEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYYD",
)


def _fold(s: str) -> str:
    """Lower + strip diacritics + collapse whitespace. Header matching only."""
    return " ".join(s.translate(_DIACRITICS).lower().split())


# Header aliases per logical column. Ordered by priority — the first
# match wins, so longer phrases beat single-word fallbacks (e.g.
# `ten cong ty` beats `ten` if both apply to the same cell).
_NAME_ALIASES: tuple[str, ...] = (
    "ten nha cung cap",
    "ten cong ty",
    "supplier name",
    "company name",
    "nha cung cap",
    "ten",
    "name",
    "company",
)
_EMAIL_ALIASES: tuple[str, ...] = ("email", "e-mail", "thu dien tu")
_PHONE_ALIASES: tuple[str, ...] = (
    "so dien thoai",
    "dien thoai",
    "phone",
    "mobile",
    "tel",
    "sdt",
)
_CATEGORIES_ALIASES: tuple[str, ...] = (
    "danh muc",
    "loai vat tu",
    "categories",
    "category",
    "nganh hang",
)
_PROVINCES_ALIASES: tuple[str, ...] = (
    "tinh thanh",
    "tinh",
    "khu vuc",
    "provinces",
    "province",
    "region",
)


@dataclass(frozen=True)
class _ColumnMap:
    """Resolved header indices. `name` is the only required field."""

    name: int
    email: int | None
    phone: int | None
    categories: int | None
    provinces: int | None


def detect_columns(header: list[str]) -> _ColumnMap:
    """Match header cells against alias tuples.

    Raises `SupplierImportError` only when `name` is unrecognisable —
    everything else is optional. The buyer can ship a spreadsheet with
    just `name` and it'll import.
    """
    folded = [_fold(c or "") for c in header]
    name_idx = _first_match(folded, _NAME_ALIASES)
    if name_idx is None:
        raise SupplierImportError(
            f"No recognisable `name` column in the header. Expected one of: {', '.join(_NAME_ALIASES[:5])}…"
        )
    return _ColumnMap(
        name=name_idx,
        email=_first_match(folded, _EMAIL_ALIASES, exclude={name_idx}),
        phone=_first_match(folded, _PHONE_ALIASES, exclude={name_idx}),
        categories=_first_match(folded, _CATEGORIES_ALIASES, exclude={name_idx}),
        provinces=_first_match(folded, _PROVINCES_ALIASES, exclude={name_idx}),
    )


def _first_match(folded: list[str], aliases: tuple[str, ...], *, exclude: set[int] | None = None) -> int | None:
    """Return the first column index matching any alias, skipping `exclude`."""
    for alias in aliases:
        for i, cell in enumerate(folded):
            if exclude and i in exclude:
                continue
            if alias in cell:
                return i
    return None


# Lists in the categories / provinces columns can be separated by any of
# these — buyers paste from various sources, so we accept all of them.
_LIST_SEP_RE = re.compile(r"[;,|/]")


def coerce_row(cells: list[str], cols: _ColumnMap) -> SupplierRow | None:
    """Build a SupplierRow from one body row.

    Returns `None` when the name cell is blank (skip silently — buyers
    often leave spacer rows for visual grouping). Trims every text
    field; coerces categories/provinces by splitting on `;,|/`.

    Phone is kept as-is (stripped). Email is lowercased + stripped
    (case-insensitive uniqueness downstream); we do NOT validate
    deliverability — that's the buyer's call.
    """
    if cols.name >= len(cells):
        return None
    name = (cells[cols.name] or "").strip()
    if not name:
        return None

    def _cell(idx: int | None) -> str:
        if idx is None or idx >= len(cells):
            return ""
        return (cells[idx] or "").strip()

    def _list_cell(idx: int | None) -> list[str]:
        raw = _cell(idx)
        if not raw:
            return []
        return [p.strip() for p in _LIST_SEP_RE.split(raw) if p.strip()]

    email = _cell(cols.email).lower() or None
    phone = _cell(cols.phone) or None

    return SupplierRow(
        name=name,
        email=email,
        phone=phone,
        categories=_list_cell(cols.categories),
        provinces=_list_cell(cols.provinces),
    )
