"""Pinned audit CSV export shape (cycle W2).

Pinned seams:
  1. `PINNED_CSV_COLUMNS` is the (header, source-key) list — pin
     the order so a refactor that swaps columns silently breaks
     downstream pandas / Excel pipelines.
  2. `pin_note` is the LAST column. Compliance reviewers expect to
     see "context columns then payload columns then their own note."
  3. `shape_pinned_row` synthesises actor_kind + JSON-stringifies
     before/after — same idiom as P3's sync CSV.
  4. `_pin_note` defaults to "" (NOT "None") when the row's pin_note
     is null so Excel doesn't render the literal Python repr.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from services.audit_pin_csv import (
    PINNED_CSV_COLUMNS,
    shape_pinned_row,
    shape_pinned_row_safe,
)

# ---------- Column shape ----------


def test_pinned_csv_columns_pinned_order():
    """The header order matters — Excel's auto-detection of column
    types keys off position. Pin the exact list."""
    expected = [
        "when",
        "action",
        "resource_type",
        "resource_id",
        "actor_email",
        "actor_api_key_name",
        "actor_kind",
        "ip",
        "user_agent",
        "before",
        "after",
        "pin_note",
    ]
    actual = [h for h, _src in PINNED_CSV_COLUMNS]
    assert actual == expected


def test_pin_note_is_the_last_column():
    """Reviewer expectation: their own annotation appears at the
    far right — context columns first, then payload, then note.
    Pin so a future refactor that prepends `pin_note` flips the
    UX in a confusing way."""
    last_header, _src = PINNED_CSV_COLUMNS[-1]
    assert last_header == "pin_note"


# ---------- shape_pinned_row ----------


def _row(**overrides: object) -> dict:
    """Build a fake mappings-row dict with every key the helper
    reads. Override fields per test."""
    base = {
        "actor_user_id": uuid4(),
        "actor_api_key_id": None,
        "actor_email": "alice@example.com",
        "actor_api_key_name": None,
        "action": "pulse.change_order.approve",
        "resource_type": "change_orders",
        "resource_id": uuid4(),
        "before": {"status": "draft"},
        "after": {"status": "approved"},
        "ip": "203.0.113.7",
        "user_agent": "Mozilla/5.0",
        "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        "pin_note": "smoking gun",
    }
    base.update(overrides)
    return base


def test_shape_pinned_row_synthesises_actor_kind_user():
    out = shape_pinned_row(_row(actor_user_id=uuid4(), actor_api_key_id=None))
    assert out["_actor_kind"] == "user"


def test_shape_pinned_row_synthesises_actor_kind_api_key():
    out = shape_pinned_row(_row(actor_user_id=None, actor_api_key_id=uuid4()))
    assert out["_actor_kind"] == "api_key"


def test_shape_pinned_row_synthesises_actor_kind_system():
    out = shape_pinned_row(_row(actor_user_id=None, actor_api_key_id=None))
    assert out["_actor_kind"] == "system"


def test_shape_pinned_row_serialises_before_after_as_json():
    """before / after must be valid JSON strings — pandas
    `json.loads(row["before"])` round-trips cleanly. Pin so a
    refactor that calls str() on the dict (Python repr) doesn't
    silently break downstream consumers."""
    out = shape_pinned_row(_row())
    parsed = json.loads(out["_before_json"])
    assert parsed == {"status": "draft"}


def test_shape_pinned_row_carries_pin_note():
    """The note column threads through verbatim from the JOIN's
    `pin_note` column."""
    out = shape_pinned_row_safe(_row(pin_note="custom annotation"))
    assert out["_pin_note"] == "custom annotation"


def test_shape_pinned_row_handles_null_note_as_empty_string():
    """Pin's `note` column is nullable. Excel renders the literal
    string "None" if we pass it through unchanged — defensive
    convert to empty string."""
    out = shape_pinned_row_safe(_row(pin_note=None))
    assert out["_pin_note"] == ""


def test_shape_pinned_row_safe_handles_missing_pin_note_key():
    """If a query somehow omits the pin_note column (e.g. older
    snapshot pre-W2 join), the safe variant falls back to "" rather
    than raising KeyError. Pin the defense so a partial migration
    doesn't 500 the export."""
    row = _row()
    del row["pin_note"]
    out = shape_pinned_row_safe(row)
    assert out["_pin_note"] == ""
