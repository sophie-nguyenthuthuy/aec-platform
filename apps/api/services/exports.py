"""Tabular data export — CSV / XLSX download for tenant data.

Counterpart of `services.imports`. The import path takes a CSV from
the customer; the export path hands one back. Together they make
"can I get my data out" a one-clicker, which buyers ask about within
the first 10 minutes of evaluating any SaaS.

Design choices:

  * **Per-entity column allowlist.** We render only the columns we
    explicitly list — never `SELECT *`. Two reasons: (1) JSONB blobs
    like `metadata_`, `ai_analysis` would leak fields the UI never
    surfaces, and (2) renaming an internal column would silently
    break a customer's CSV pipeline. Allowlists make the contract
    obvious.

  * **Streaming CSV.** Python's `csv.writer` over a generator that
    yields one row at a time. The router wraps that in a
    `StreamingResponse` so a 50k-row export doesn't buffer in worker
    memory — the client sees bytes as fast as Postgres yields rows.

  * **Buffered XLSX.** openpyxl can't stream the way CSV can — the
    .xlsx zip wrapper is finalised after the last row is written. We
    cap XLSX exports at 50k rows and buffer in a `BytesIO`. CSV path
    is unbounded (within reason; the streaming generator never
    materialises the full file).

  * **Filters live in code, not in a generic builder.** Every
    `EXPORT_CONFIGS` entry maps filter-name → SQL fragment +
    parameter coercion. Cheaper to read than a JSON-schema-driven
    dispatcher, and SQL injection-safe because filter names go
    through a fixed dict before they touch the query.

What we DON'T export:

  * Cross-org data — `TenantAwareSession` + the org-id in the WHERE
    clause keep RLS belt-and-suspenders.
  * Authentication tokens, webhook secrets, or PII not on the
    object's own row (no joins to `users.email` for example —
    `reported_by` becomes the user UUID, not the email).
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Cap the XLSX path at 50k rows. Beyond that the BytesIO buffer
# crosses ~25MB and we'd rather force the customer to use CSV (which
# is genuinely streaming and unbounded). The CSV path also has a
# safety cap — same 50k — to keep a misclick from monopolising a
# worker for minutes.
_MAX_XLSX_ROWS = 50_000
_MAX_CSV_ROWS = 50_000


# ---------- Per-entity config ----------


@dataclass(frozen=True)
class ColumnSpec:
    """One output column. `header` is what the spreadsheet shows;
    `select` is the SQL projection that produces the value (often
    just the bare column name, but join-aliased columns or COALESCEs
    sit here too)."""

    header: str
    select: str


@dataclass(frozen=True)
class FilterSpec:
    """One bind-safe filter. `sql_fragment` uses a `:param` placeholder;
    `coerce` converts the raw query-string value to the right Python
    type before binding (UUIDs, dates, ints — Postgres asyncpg won't
    coerce strings on its own)."""

    sql_fragment: str
    coerce: Any  # callable str -> Any


@dataclass(frozen=True)
class ExportConfig:
    """One row per allowed entity. `from_clause` includes any joins
    (e.g. defects → projects for the project_name column). The org-id
    WHERE is appended by the runner — config files don't repeat it."""

    table_alias: str  # primary table alias, used in WHERE
    from_clause: str
    columns: tuple[ColumnSpec, ...]
    filters: dict[str, FilterSpec]
    order_by: str  # added verbatim — keep simple expressions only


def _coerce_uuid(v: str) -> UUID:
    return UUID(v)


def _coerce_date(v: str) -> date:
    return date.fromisoformat(v)


def _coerce_str(v: str) -> str:
    return v


def _coerce_bool(v: str) -> bool:
    return v.lower() in {"1", "true", "yes", "y"}


# Per-entity definitions. Adding an entity = one entry here + one
# admin-page tab on the frontend; no other code changes needed.
EXPORT_CONFIGS: dict[str, ExportConfig] = {
    "projects": ExportConfig(
        table_alias="p",
        from_clause="projects p",
        columns=(
            ColumnSpec("id", "p.id"),
            ColumnSpec("external_id", "p.external_id"),
            ColumnSpec("name", "p.name"),
            ColumnSpec("type", "p.type"),
            ColumnSpec("status", "p.status"),
            ColumnSpec("city", "p.address->>'city'"),
            ColumnSpec("district", "p.address->>'district'"),
            ColumnSpec("area_sqm", "p.area_sqm"),
            ColumnSpec("budget_vnd", "p.budget_vnd"),
            ColumnSpec("floors", "p.floors"),
            ColumnSpec("start_date", "p.start_date"),
            ColumnSpec("end_date", "p.end_date"),
            ColumnSpec("created_at", "p.created_at"),
        ),
        filters={
            "status": FilterSpec("p.status = :status", _coerce_str),
            "type": FilterSpec("p.type = :type", _coerce_str),
        },
        order_by="p.created_at DESC",
    ),
    "suppliers": ExportConfig(
        table_alias="s",
        from_clause="suppliers s",
        columns=(
            ColumnSpec("id", "s.id"),
            ColumnSpec("external_id", "s.external_id"),
            ColumnSpec("name", "s.name"),
            # Arrays joined with a comma — matches the format the
            # import path's `_split_csv` accepts on the way back in.
            ColumnSpec("categories", "array_to_string(s.categories, ', ')"),
            ColumnSpec("provinces", "array_to_string(s.provinces, ', ')"),
            ColumnSpec("phone", "s.contact->>'phone'"),
            ColumnSpec("email", "s.contact->>'email'"),
            ColumnSpec("address", "s.contact->>'address'"),
            ColumnSpec("verified", "s.verified"),
            ColumnSpec("rating", "s.rating"),
            ColumnSpec("created_at", "s.created_at"),
        ),
        filters={
            "verified": FilterSpec("s.verified = :verified", _coerce_bool),
            "province": FilterSpec(":province = ANY(s.provinces)", _coerce_str),
        },
        order_by="s.name ASC",
    ),
    "defects": ExportConfig(
        table_alias="d",
        from_clause="defects d LEFT JOIN projects pj ON pj.id = d.project_id",
        columns=(
            ColumnSpec("id", "d.id"),
            ColumnSpec("project_id", "d.project_id"),
            ColumnSpec("project_name", "pj.name"),
            ColumnSpec("title", "d.title"),
            ColumnSpec("description", "d.description"),
            ColumnSpec("priority", "d.priority"),
            ColumnSpec("status", "d.status"),
            ColumnSpec("reported_at", "d.reported_at"),
            ColumnSpec("resolved_at", "d.resolved_at"),
            ColumnSpec("resolution_notes", "d.resolution_notes"),
        ),
        filters={
            "project_id": FilterSpec("d.project_id = :project_id", _coerce_uuid),
            "status": FilterSpec("d.status = :status", _coerce_str),
            "priority": FilterSpec("d.priority = :priority", _coerce_str),
            "since": FilterSpec("d.reported_at >= :since", _coerce_date),
        },
        order_by="d.reported_at DESC",
    ),
    "change_orders": ExportConfig(
        table_alias="co",
        from_clause="change_orders co LEFT JOIN projects pj ON pj.id = co.project_id",
        columns=(
            ColumnSpec("id", "co.id"),
            ColumnSpec("project_id", "co.project_id"),
            ColumnSpec("project_name", "pj.name"),
            ColumnSpec("number", "co.number"),
            ColumnSpec("title", "co.title"),
            ColumnSpec("description", "co.description"),
            ColumnSpec("status", "co.status"),
            ColumnSpec("initiator", "co.initiator"),
            ColumnSpec("cost_impact_vnd", "co.cost_impact_vnd"),
            ColumnSpec("schedule_impact_days", "co.schedule_impact_days"),
            ColumnSpec("submitted_at", "co.submitted_at"),
            ColumnSpec("approved_at", "co.approved_at"),
            ColumnSpec("created_at", "co.created_at"),
        ),
        filters={
            "project_id": FilterSpec("co.project_id = :project_id", _coerce_uuid),
            "status": FilterSpec("co.status = :status", _coerce_str),
            "since": FilterSpec("co.created_at >= :since", _coerce_date),
        },
        order_by="co.created_at DESC",
    ),
    "rfis": ExportConfig(
        table_alias="r",
        from_clause="rfis r LEFT JOIN projects pj ON pj.id = r.project_id",
        columns=(
            ColumnSpec("id", "r.id"),
            ColumnSpec("project_id", "r.project_id"),
            ColumnSpec("project_name", "pj.name"),
            ColumnSpec("number", "r.number"),
            ColumnSpec("subject", "r.subject"),
            ColumnSpec("description", "r.description"),
            ColumnSpec("status", "r.status"),
            ColumnSpec("priority", "r.priority"),
            ColumnSpec("due_date", "r.due_date"),
            ColumnSpec("response", "r.response"),
            ColumnSpec("created_at", "r.created_at"),
        ),
        filters={
            "project_id": FilterSpec("r.project_id = :project_id", _coerce_uuid),
            "status": FilterSpec("r.status = :status", _coerce_str),
            "since": FilterSpec("r.created_at >= :since", _coerce_date),
        },
        order_by="r.created_at DESC",
    ),
}


# ---------- Query builder ----------


def build_select(
    *,
    config: ExportConfig,
    filters: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    """Compose the SELECT for a given (entity, filter set).

    Returns `(sql, bound_params)`. Filter keys NOT in
    `config.filters` are silently dropped — that's how the router
    surfaces a clean 422 (`Query()` declares the allowed names) while
    the service stays defensive in depth.

    The org-id filter is bound by the caller with `org_id` — this
    function only assembles the entity-specific clauses.
    """
    selects = ", ".join(f"{c.select} AS {c.header}" for c in config.columns)
    where_parts = [f"{config.table_alias}.organization_id = :org_id"]
    params: dict[str, Any] = {}
    for name, raw in filters.items():
        spec = config.filters.get(name)
        if spec is None or raw is None or raw == "":
            continue
        try:
            params[name] = spec.coerce(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid {name}: {exc}") from exc
        where_parts.append(spec.sql_fragment)
    sql = f"SELECT {selects} FROM {config.from_clause} WHERE {' AND '.join(where_parts)} ORDER BY {config.order_by}"
    return sql, params


# ---------- Row streaming ----------


async def stream_rows(
    *,
    session: AsyncSession,
    organization_id: UUID,
    entity: str,
    filters: dict[str, str],
    cap: int,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding one dict per row, capped at `cap`.

    `execute(...).mappings()` materialises the whole result set in
    memory — fine for the 50k cap but worth noting if we ever raise
    it. To genuinely stream beyond memory we'd need
    `connection.execution_options(yield_per=N)`, but that requires a
    sync iter wrapper from asyncpg and isn't worth the complexity at
    50k.
    """
    config = EXPORT_CONFIGS[entity]
    sql, params = build_select(config=config, filters=filters)
    params["org_id"] = str(organization_id)
    result = await session.execute(text(sql), params)
    # ruff: SIM113 wants `enumerate(result.mappings())` here, but result
    # mappings only iterate once — wrapping them in enumerate adds a
    # pointless adapter layer. The manual counter is clearer.
    yielded = 0
    for row in result.mappings():
        if yielded >= cap:
            break
        yielded += 1  # noqa: SIM113
        yield dict(row)


# ---------- CSV serialiser ----------


def write_csv_lines(
    rows: Iterable[dict[str, Any]],
    *,
    headers: list[str],
) -> Iterable[bytes]:
    """Yield encoded CSV lines, one chunk per source row plus the
    header. `csv.writer` doesn't accept bytes destinations, so we
    write to a per-call StringIO and encode each line — small but
    bounded overhead, and lets the upstream `StreamingResponse`
    push bytes to the wire incrementally.

    All cells are coerced via `_csv_cell` so datetimes round-trip as
    ISO-8601 (re-importable) and None becomes empty string (cleaner
    than the literal "None" Python's str() would produce).
    """
    # Header line
    sio = io.StringIO()
    writer = csv.writer(sio, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    yield sio.getvalue().encode("utf-8")

    for row in rows:
        sio = io.StringIO()
        writer = csv.writer(sio, quoting=csv.QUOTE_MINIMAL)
        writer.writerow([_csv_cell(row.get(h)) for h in headers])
        yield sio.getvalue().encode("utf-8")


def _csv_cell(v: Any) -> str:
    """Stringify one cell value for CSV/XLSX output.

    * None → empty string. Matters because csv would otherwise emit
      "" but XLSX would emit a literal `None` cell.
    * datetimes → ISO-8601. Same shape the import validator
      understands, closing the round-trip.
    * UUIDs → str()-cast (their str repr is the canonical hex form).
    * everything else → str().
    """
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# ---------- XLSX serialiser ----------


def build_xlsx_bytes(
    rows: Iterable[dict[str, Any]],
    *,
    headers: list[str],
    sheet_title: str = "Sheet1",
) -> bytes:
    """Build a complete XLSX in memory and return its bytes.

    Uses openpyxl's `write_only` workbook + `WriteOnlyCell` so we
    don't accumulate the full row index in RAM (write_only flushes
    finished rows to the underlying zip on the fly). Still bounded by
    `_MAX_XLSX_ROWS` to keep buffer size predictable.
    """
    from openpyxl import Workbook  # heavy import; lazy.

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title=sheet_title)
    ws.append(headers)
    for row in rows:
        ws.append([_csv_cell(row.get(h)) for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_cap() -> int:
    return _MAX_CSV_ROWS


def xlsx_cap() -> int:
    return _MAX_XLSX_ROWS
