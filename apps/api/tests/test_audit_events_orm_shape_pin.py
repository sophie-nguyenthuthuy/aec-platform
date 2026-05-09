"""Pin the column shape of `models.audit.AuditEvent`.

Why this exists: the `audit_events` table has been touched by two
migrations (`0022_audit_events` + `0033_audit_actor_api_key`) and
the ORM model has been edited several times across recent batches.
A column-name drift between migration and ORM is one of the worst
silent failure modes:

  * **Migration adds a column the ORM doesn't know about**: every
    audit row INSERT works (NULL value for the unmapped column),
    but reads via the ORM never expose it. Compliance queries
    against the new field silently return None.

  * **ORM declares a column the migration never created**: every
    audit emission 500s with `UndefinedColumn`. Looks like a
    routing or auth bug at runtime; the actual cause (missing
    column) is invisible without DB introspection.

  * **Type drift** (e.g. ORM says `Text`, migration says `JSONB`):
    inserts work for simple values but JSONB-shaped reads
    (`row.before["status"]`) fail at runtime with the error
    "TEXT object is not subscriptable" — and the call site
    docstrings still claim it's a dict.

This test pins the ORM column shape exactly. The matching
migration shape is implicit (the ORM is what the app reads from);
a column added to the migration but not the ORM fails this test
the moment someone tries to access it through the model.

If you intentionally change AuditEvent's shape, update `EXPECTED`
below in the same PR + ship a migration that mirrors it.
"""

from __future__ import annotations

from typing import NamedTuple

from models.audit import AuditEvent


class _ColShape(NamedTuple):
    """Minimal shape we pin per column. Type is captured as the
    SQLAlchemy class name so we don't depend on the dialect-specific
    rendering (e.g. `UUID(as_uuid=True)` vs. `UUID`)."""

    type_name: str
    nullable: bool
    primary_key: bool


# Source of truth, pinned 2026-05-04. The order of entries follows
# the column-declaration order in `models/audit.py`. The dict shape
# (rather than a tuple) makes failure messages name the specific
# column that drifted.
EXPECTED_COLUMNS: dict[str, _ColShape] = {
    "id": _ColShape(type_name="UUID", nullable=False, primary_key=True),
    # Tenant scope — every audit row belongs to exactly one org.
    # Required (NOT NULL) so RLS predicates can rely on the column.
    "organization_id": _ColShape(type_name="UUID", nullable=False, primary_key=False),
    # Actor as user_id — nullable because cron / system events have
    # no human actor. Pinned shape: nullable UUID, not pk.
    "actor_user_id": _ColShape(type_name="UUID", nullable=True, primary_key=False),
    # Actor as api_key_id — added in migration 0033 to track
    # api-key callers separately from user callers (the FK to
    # users.id rejected api_keys.id values pre-migration). Same
    # nullable shape; exactly one of (user_id, api_key_id) is
    # non-NULL on a row with a known actor.
    "actor_api_key_id": _ColShape(type_name="UUID", nullable=True, primary_key=False),
    # Closed-set verb identifying what was done. TEXT (not enum)
    # so adding a new AuditAction doesn't require a migration —
    # the closed set is enforced in Python via the Literal type.
    "action": _ColShape(type_name="Text", nullable=False, primary_key=False),
    # Resource type / id — id nullable because some events
    # (cron-driven, role changes that don't target a specific row)
    # don't have a single resource_id to attribute to.
    "resource_type": _ColShape(type_name="Text", nullable=False, primary_key=False),
    "resource_id": _ColShape(type_name="UUID", nullable=True, primary_key=False),
    # Before / after JSON diffs. JSONB (NOT TEXT) so the read
    # side can do `row.before["status"]` — a drift to TEXT silently
    # breaks every consumer that does dict access.
    "before": _ColShape(type_name="JSONB", nullable=False, primary_key=False),
    "after": _ColShape(type_name="JSONB", nullable=False, primary_key=False),
    # Network metadata — captured from the request when available;
    # nullable because cron / queue-worker contexts have no request.
    "ip": _ColShape(type_name="Text", nullable=True, primary_key=False),
    "user_agent": _ColShape(type_name="Text", nullable=True, primary_key=False),
    # Append timestamp. Server-default now() so the row has a
    # canonical "when this event happened" value even when the call
    # site forgets to set one.
    "created_at": _ColShape(type_name="DateTime", nullable=False, primary_key=False),
}


def _actual_shape() -> dict[str, _ColShape]:
    """Project `AuditEvent.__table__.columns` into the same shape
    `EXPECTED_COLUMNS` uses. Type name is the SQLAlchemy class
    (e.g. "UUID", "TEXT", "JSONB", "DATETIME") — stable enough to
    pin without coupling to dialect rendering quirks.
    """
    out: dict[str, _ColShape] = {}
    for col in AuditEvent.__table__.columns:
        out[col.name] = _ColShape(
            type_name=type(col.type).__name__,
            nullable=col.nullable,
            primary_key=col.primary_key,
        )
    return out


def test_audit_events_columns_match_expected_shape():
    """Hard equality on the column dict. Asymmetric diff names
    exactly which column drifted (added / removed / type-changed)
    so the failure message points at the specific regression.
    """
    actual = _actual_shape()
    missing = EXPECTED_COLUMNS.keys() - actual.keys()
    unexpected = actual.keys() - EXPECTED_COLUMNS.keys()
    assert not missing, (
        f"AuditEvent ORM lost columns: {sorted(missing)}. "
        "If this is intentional, remove from EXPECTED_COLUMNS in the same "
        "PR + ship a migration that drops the column. Otherwise this is a "
        "drop-by-revert that will silently 500 every audit emission."
    )
    assert not unexpected, (
        f"AuditEvent ORM gained columns the pin doesn't know about: "
        f"{sorted(unexpected)}. If this is intentional, add to "
        "EXPECTED_COLUMNS in the same PR + verify the corresponding "
        "migration is in `alembic/versions/`."
    )
    drifted = [
        f"  {name}: expected {EXPECTED_COLUMNS[name]}, actual {actual[name]}"
        for name in EXPECTED_COLUMNS
        if EXPECTED_COLUMNS[name] != actual[name]
    ]
    assert not drifted, "AuditEvent column shapes drifted:\n" + "\n".join(drifted)


def test_audit_events_table_name_is_pinned():
    """The dispatcher's webhook outbox stores `event_type` strings
    that include `audit_events` references in copy / docs; renaming
    the table would silently break every reader (admin dashboards,
    direct SQL queries, S3 archive layouts). Pin the name.
    """
    assert AuditEvent.__table__.name == "audit_events"


def test_audit_events_jsonb_columns_use_jsonb_not_text():
    """Critical: `before` / `after` MUST be JSONB. A regression to
    TEXT silently breaks every consumer that does dict access on
    the read side (e.g. `audit_log/page.tsx`'s diff renderer reads
    `event.before["status"]` — TEXT row would crash the renderer
    with "TEXT object is not subscriptable").
    """
    for col_name in ("before", "after"):
        col = AuditEvent.__table__.columns[col_name]
        type_name = type(col.type).__name__
        assert type_name == "JSONB", (
            f"AuditEvent.{col_name} is {type_name!r}, expected JSONB. "
            "Dict-access readers will crash if this drifts to Text."
        )


def test_audit_events_actor_columns_are_nullable():
    """Both `actor_user_id` and `actor_api_key_id` MUST be nullable.
    Cron / queue-worker events have no actor — the row has both
    columns NULL by design. A regression to NOT NULL would 500
    every cron-driven audit emission (e.g.
    `costpulse.rfq.slots_expired` from `rfq_deadlines_cron`)."""
    for col_name in ("actor_user_id", "actor_api_key_id"):
        col = AuditEvent.__table__.columns[col_name]
        assert col.nullable is True, (
            f"AuditEvent.{col_name} is NOT NULL — would crash every "
            "cron-driven audit emission, where both actor columns are "
            "NULL by design."
        )


def test_audit_events_required_fields_are_not_null():
    """The fields that absolutely MUST be on every row: id,
    organization_id (RLS predicate), action, resource_type,
    before/after (default to {} but column NOT NULL), created_at.

    A regression flipping any of these to nullable means the audit
    row can be inserted with the column missing — losing the data
    that gives the audit log its compliance value.
    """
    for col_name in (
        "id",
        "organization_id",
        "action",
        "resource_type",
        "before",
        "after",
        "created_at",
    ):
        col = AuditEvent.__table__.columns[col_name]
        assert col.nullable is False, (
            f"AuditEvent.{col_name} is nullable — required by the "
            "compliance-data shape. NULL rows would silently land in "
            "the table with missing fields."
        )


def test_audit_events_column_count():
    """Belt-and-suspenders against silent column additions. The
    equality test above would also fail, but a count check makes
    the "schema gained N columns" failure mode louder than a
    missing/unexpected dict-key diff alone.
    """
    actual_count = len(AuditEvent.__table__.columns)
    expected_count = len(EXPECTED_COLUMNS)
    assert actual_count == expected_count, (
        f"AuditEvent has {actual_count} columns; pin expects {expected_count}. "
        "The equality test above will name which side is off."
    )
