# CostPulse — BOQ Excel/PDF I/O

CostPulse estimates can be **imported from Excel**, **exported to Excel**, and
**exported to PDF**. The Excel paths target the same workbook shape end-to-end
so an estimator can round-trip estimate → spreadsheet → estimate without losing
columns. The PDF path is supplier-share-friendly (no internal IDs, clean
typography, A4 portrait).

This doc covers what shape is on the wire, where the column-detection logic
lives, and what to change when you want to teach the parser a new
header phrasing.

---

## 1. Surface area

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/api/v1/costpulse/estimates/{id}/boq/import` | POST | multipart `file=<xlsx>` | `EstimateDetail` (200) |
| `/api/v1/costpulse/estimates/{id}/boq/export.xlsx` | GET | — | `application/vnd.openxmlformats-…sheet` blob |
| `/api/v1/costpulse/estimates/{id}/boq/export.pdf`  | GET | — | `application/pdf` blob |

Import semantics match `PUT /boq` — wipes existing items and inserts the parsed
ones. Approved estimates are read-only (`409 CONFLICT`). The 5 MB upload cap
in `routers.costpulse._MAX_BOQ_UPLOAD_BYTES` is the OOM guard against a
misconfigured client uploading a 1 GB binary.

---

## 2. Module layout

```
apps/api/services/boq_io/
├── __init__.py    re-exports BoqRow, BoqIOError, parse/render fns
├── core.py        library-agnostic: column detection, decimal coercion,
│                  row-to-grid mapping. NO openpyxl / reportlab imports.
├── xlsx.py        thin openpyxl adapter (lazy import).
└── pdf.py         thin reportlab adapter (lazy import).
```

The split exists for two reasons:

1. **Tests** in `apps/api/tests/test_boq_io.py` exercise `core.py` without
   needing openpyxl or reportlab. Adding a new column alias or tightening the
   decimal coercion gets caught at unit-test speed.
2. **Lazy imports** of openpyxl / reportlab keep the critical request path
   (HTML estimate rendering, BOQ list endpoint) cheap on cold start. Both
   libraries pull in C extensions and PIL on first use.

---

## 3. Column detection

`core.detect_columns(header_row)` scans the header against alias tuples for
each logical column:

| Logical column | Aliases (folded, lowercased, ASCII) |
|---|---|
| `description` (mandatory) | `mo ta cong viec`, `mo ta`, `ten cong viec`, `ten vat lieu`, `description`, `item`, `name`, … |
| `code` | `ma cong viec`, `stt`, `code`, `no.`, `#` |
| `unit` | `don vi tinh`, `don vi`, `dvt`, `unit`, `uom` |
| `quantity` | `khoi luong`, `so luong`, `quantity`, `qty`, `kl` |
| `unit_price_vnd` | `don gia`, `unit price`, `rate`, `price` |
| `total_price_vnd` | `thanh tien`, `total`, `amount`, `sub total` |
| `material_code` | `ma vat lieu`, `material code`, `ma vt` |

Diacritics are stripped before matching — a spreadsheet with `Mô tả` and one
with `Mo ta` both land on the same column. Aliases are checked **in priority
order**, and `_first_match` uses substring containment (`alias in cell`) so
real headers like `Mô tả công việc (chi tiết)` still resolve.

A cell that gets claimed for `description` is excluded from later
matches via the `exclude=` parameter — keeps `Tên hàng` from sneaking in as a
second description column when the spreadsheet uses both.

**Adding a new alias**: edit the relevant `_ALIASES` tuple in `core.py`, add a
test case to `tests/test_boq_io.py::TestDetectColumns`, ship.

---

## 4. Decimal coercion

`core.coerce_decimal(cell)` handles every Vietnamese / English number format
we've seen in the wild:

| Input | Becomes |
|---|---|
| `1234`, `1234.5` (xlsx native int/float) | `Decimal("1234")` |
| `"1,234,567"` (English thousands) | `Decimal("1234567")` |
| `"1.234.567"` (Vietnamese thousands) | `Decimal("1234567")` |
| `"1.234.567,89"` (Vietnamese decimal + thousands) | `Decimal("1234567.89")` |
| `"12,500"` (3-digit grouping, no decimal) | `Decimal("12500")` (thousands) |
| `"1,5"` (short comma) | `Decimal("1.5")` (decimal) |
| `"2 000 000 đ"`, `"VND 1,234,567.50"` | currency markers stripped |
| `"—"`, `"N/A"`, `""`, `None` | `None` |

The heuristic for "3 + comma" → thousands vs. "1,5" → decimal is regex-based
(`r"-?\d{1,3}(,\d{3})+"`); ambiguous cases like `"1234,5"` get the "decimal"
branch.

---

## 5. Export shape

`core.rows_to_grid(rows)` returns `(header_cells, body_cells)` with this
canonical column order:

```
Code | Description | Unit | Quantity | Unit price (VND) | Total (VND) | Material code
```

Order matches what users expect on a printed BOQ — description first, totals
on the right. The xlsx and pdf renderers both consume this same grid, so
column-parity between the two formats is enforced in one place.

**Auto-computed totals**: when a row has `quantity` + `unit_price_vnd` but no
explicit `total_price_vnd`, `_compute_total` multiplies them. This makes
`import → export` round-trips produce a complete BOQ even when the source
spreadsheet omitted the total column.

---

## 6. The xlsx renderer (style notes)

- Header row: bold + light-grey fill (`#EEEEEE`), `freeze_panes = "A2"` so
  the header stays visible on scroll.
- Description column (`B`) is widened to 50 chars and gets `wrap_text` so
  long item descriptions don't blow out the column width.
- Numeric formats: `#,##0.##` for quantity, `#,##0` for prices.
- Sheet name comes from `_safe_sheet_name(estimate.name)` which:
  - Caps at 31 chars (Excel's hard limit)
  - Replaces illegal chars `:\\/?*[]` with hyphens
  - Falls back to `"BOQ"` when the estimate name is empty

---

## 7. The pdf renderer

- A4 portrait with 15mm margins.
- Title heading + ISO timestamp (`Heading1` / `Italic`).
- One Platypus `Table` for the full BOQ, with `repeatRows=1` so the header
  re-renders on every page break.
- Column widths chosen for an A4 width minus margins (~180mm); description
  gets the lion's share at 60mm, numerics size for VND-scale (~22mm).
- Grand-total row at the bottom — sums every row's total or
  `quantity × unit_price` when the explicit total is missing.

The renderer doesn't try to reproduce the buyer's full estimate styling
because the output is meant for sharing with suppliers / authorities, where
a clean tabular dump is more useful than a designed report.

---

## 8. Filename for exports

`_filename_for_export(estimate.name, ext="xlsx")` slugifies the estimate
name to ASCII (Vietnamese diacritics become hyphens), caps at 80 chars, and
falls back to `"boq"` when the name is empty. The simpler ASCII form
sidesteps RFC-5987 quoting compatibility issues across email clients;
visual fidelity of the download name takes a small hit in exchange for
"the link works in Outlook" reliability.

---

## 9. UI surface (web)

- `apps/web/hooks/costpulse/useEstimates.ts`:
  - `useImportBoq(id)` — multipart upload via raw fetch (apiFetch hard-codes
    JSON Content-Type; multipart needs the browser to set the boundary).
  - `useExportBoq(id)` — returns a `(format) => Promise<void>` that fetches
    the binary blob with bearer auth then synthesises a download via a
    temporary `<a download>` element. We don't open the URL directly because
    the auth header doesn't survive a top-level navigation.

- The estimate detail page (`apps/web/app/(dashboard)/costpulse/estimates/
  [id]/page.tsx`) renders three buttons next to **Approve**: `Import .xlsx`,
  `Export .xlsx`, `Export .pdf`. Inline error display for failed import or
  export. The hidden file input resets `e.target.value = ""` after change so
  picking the same file twice still fires `onChange`.

---

## 10. Adding a new format

To add CSV, ODS, JSON, or any other shape:

1. Add `services/boq_io/<format>.py` with `parse_boq_<format>(bytes) → list[BoqRow]`
   and `render_boq_<format>(rows) → bytes`.
2. Re-export from `__init__.py`.
3. Reuse `detect_columns` + `rows_to_grid` from `core.py` — the column-
   detection logic doesn't change between formats.
4. Wire two new endpoints in `routers/costpulse.py` mirroring the
   xlsx/pdf pattern.
5. Add hooks (`useImport<Format>`, …) and a button.

The lazy-import gate for the format-specific lib is the only piece that needs
care: deployed envs always have the deps, but pure-unit-test envs don't.
