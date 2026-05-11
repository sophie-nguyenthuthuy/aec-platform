"""Pinned audit CSV export shape (cycle W2).

Pure-helper module. Builds the CSV column set + per-row dict for
the pinned-CSV export at `GET /api/v1/audit/events.csv?pinned_only=true`.

Mirrors the column shape of cycle P3's sync CSV export plus a
`pin_note` column at the end. The `pinned_only` query path joins
`audit_events` with `audit_pins` on `audit_event_id = id` AND
`pinned_by = caller's user_id`; the join's `note` column flows
into this helper as the `pin_note` field.

Why a separate column module rather than parameterising P3's
`_CSV_COLUMNS`:
  * The sync CSV's column set is pinned by a surface-snapshot test
    (P3). Adding `pin_note` conditionally would either (a) bloat
    the snapshot test to a parameterised matrix, or (b) drop it
    from the pinned export and fail this cycle's intent.
  * A separate module makes the pinned export's contract explicit:
    pinned-CSV ALWAYS carries the note column; the unfiltered
    export NEVER does. No conditional branching at the CSV writer.

Pure Python, no DB. Caller queries the rows; this helper formats
them.
"""

from __future__ import annotations

import json
from typing import Any

# Same column order as P3 + `pin_note` appended. Headers mirror
# user-friendly form (`when` not `created_at`); the source-key
# names match the SQL projection.
PINNED_CSV_COLUMNS: list[tuple[str, str]] = [
    ("when", "created_at"),
    ("action", "action"),
    ("resource_type", "resource_type"),
    ("resource_id", "resource_id"),
    ("actor_email", "actor_email"),
    ("actor_api_key_name", "actor_api_key_name"),
    ("actor_kind", "_actor_kind"),
    ("ip", "ip"),
    ("user_agent", "user_agent"),
    ("before", "_before_json"),
    ("after", "_after_json"),
    # Cycle W2 — review note carried per pinned row. NULL is
    # rendered as the empty cell rather than the literal "None"
    # string so Excel doesn't show "None" in the column.
    ("pin_note", "_pin_note"),
]


def shape_pinned_row(row: Any) -> dict[str, Any]:
    """Turn a SQLAlchemy mapping row from the pinned-rows query into
    the CSV-cell dict.

    The query MUST select the same projection as P3 plus a `pin_note`
    column from the `audit_pins` JOIN. Caller controls the SQL —
    this helper only formats the result.

    Synthesises three derived columns the same way P3's
    `_row_dict` does:
      * `_actor_kind` — "user" / "api_key" / "system" from the
        actor_user_id / actor_api_key_id presence pattern.
      * `_before_json` / `_after_json` — JSON-serialised diffs so
        the cell holds the full nested structure (Excel reads as
        string; pandas / jq round-trip via json.loads).
      * `_pin_note` — the row's `pin_note`, with None → "" so Excel
        doesn't render the literal string "None".

    Pinned row vs. P3's regular row: the only field shape difference
    is `pin_note` here. Everything else mirrors P3's `_row_dict`
    exactly, so a refactor that drifts one will fail the W2 test
    suite (same fixture as P3's test).
    """
    if row["actor_user_id"] is not None:
        actor_kind_val = "user"
    elif row["actor_api_key_id"] is not None:
        actor_kind_val = "api_key"
    else:
        actor_kind_val = "system"

    return {
        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
        "action": row["action"] or "",
        "resource_type": row["resource_type"] or "",
        "resource_id": str(row["resource_id"]) if row["resource_id"] else "",
        "actor_email": row["actor_email"] or "",
        "actor_api_key_name": row["actor_api_key_name"] or "",
        "_actor_kind": actor_kind_val,
        "ip": row["ip"] or "",
        "user_agent": row["user_agent"] or "",
        "_before_json": json.dumps(row["before"], default=str, ensure_ascii=False),
        "_after_json": json.dumps(row["after"], default=str, ensure_ascii=False),
        # NULL → "" so Excel doesn't render "None" verbatim.
        "_pin_note": row.get("pin_note") if hasattr(row, "get") else row["pin_note"] or "",
    }


def shape_pinned_row_safe(row: Any) -> dict[str, Any]:
    """Defensive wrapper — handles dict and SQLAlchemy mapping shapes.

    SQLAlchemy `mappings().all()` rows support `[]` indexing but
    NOT `.get()`. Plain dicts (e.g. from tests) support both.
    `shape_pinned_row` works with either — but if the row is
    missing the `pin_note` key (e.g. an older snapshot that pre-
    dates the JOIN), this wrapper falls back to "" instead of
    raising KeyError.
    """
    note = ""
    try:
        raw_note = row["pin_note"]
        if raw_note is not None:
            note = str(raw_note)
    except (KeyError, AttributeError):
        note = ""

    if row["actor_user_id"] is not None:
        actor_kind_val = "user"
    elif row["actor_api_key_id"] is not None:
        actor_kind_val = "api_key"
    else:
        actor_kind_val = "system"

    return {
        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
        "action": row["action"] or "",
        "resource_type": row["resource_type"] or "",
        "resource_id": str(row["resource_id"]) if row["resource_id"] else "",
        "actor_email": row["actor_email"] or "",
        "actor_api_key_name": row["actor_api_key_name"] or "",
        "_actor_kind": actor_kind_val,
        "ip": row["ip"] or "",
        "user_agent": row["user_agent"] or "",
        "_before_json": json.dumps(row["before"], default=str, ensure_ascii=False),
        "_after_json": json.dumps(row["after"], default=str, ensure_ascii=False),
        "_pin_note": note,
    }
