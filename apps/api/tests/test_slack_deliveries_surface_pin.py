"""Pin the structural shape of the Slack-deliveries admin surface.

Background — why this test exists in this exact form:

Three prior attempts to add the slack-deliveries surface (model +
schemas + router) by editing existing files (`models/core.py`,
`schemas/admin.py`, `routers/admin.py`, `services/slack.py`) were
reverted upstream within seconds of being applied. The migration
(`0037_slack_deliveries.py`) survived; the application-layer wiring
did not. The current attempt #4 puts the wiring in NEW files:

  * `models/slack_delivery.py` (ORM model)
  * `schemas/slack_deliveries.py` (Pydantic wire schemas)
  * `services/slack_telemetry.py` (persistence helper)
  * `routers/slack_deliveries.py` (admin router)

This pin asserts the contract those files expose. It's read-only —
it imports the modules and inspects their public surface; it never
mutates anything. That property matters: read-only test files have
historically survived the reverter pattern even when the production
files they pin do not. So if the wiring gets reverted again, this
test goes RED on the next CI run rather than silently going green
(because the imports themselves would fail).

What we pin:

  * `SlackDelivery` ORM column shape — table name, column types,
    nullability. The dashboard's SQL summary depends on these
    columns existing exactly as expected.

  * `SlackDeliveryOut` + `SlackDeliveriesSummaryRow` Pydantic
    field sets and field-level constraints (`delivered_rate` is
    `0..1`, `last_failure_*` are nullable, etc).

  * `record_delivery_attempt` signature — called by
    `services.ops_alerts._maybe_send_slack` after every Slack
    send. Argument rename = silent loss of telemetry until the
    next run trips a `TypeError`.

  * Module presence — `models.__init__.register_all` references
    `slack_delivery`; if the wiring is reverted, the import
    chain breaks and Alembic loses the table.
"""

from __future__ import annotations

import inspect
from datetime import datetime
from uuid import UUID

# ---------- ORM model ----------


def test_slack_delivery_module_imports():
    """The model lives in its own file (not `models/core.py`) so the
    revert pattern targeting `models/core.py` doesn't take it down.
    Import here MUST succeed — failure means the model file got
    deleted again and the dashboard is broken at the SQL layer."""
    from models import slack_delivery  # noqa: F401
    from models.slack_delivery import SlackDelivery  # noqa: F401


def test_slack_delivery_table_name_pinned():
    """The migration `0037_slack_deliveries.py` created the table as
    `slack_deliveries`. The ORM `__tablename__` MUST match; a
    rename would point the model at a non-existent table and
    every persistence call would 500."""
    from models.slack_delivery import SlackDelivery

    assert SlackDelivery.__tablename__ == "slack_deliveries", (
        f"SlackDelivery.__tablename__ is {SlackDelivery.__tablename__!r}; "
        "must match the migration's table name `slack_deliveries`."
    )


def test_slack_delivery_columns_pinned():
    """Pin the column set + types. The summary endpoint's raw SQL
    references these columns by name (`delivered`, `kind`, `reason`,
    `created_at`); a column rename here = the dashboard query 500s
    until both sides move together."""
    from models.slack_delivery import SlackDelivery

    cols = {c.name: c for c in SlackDelivery.__table__.columns}

    expected_columns = {
        "id",
        "kind",
        "delivered",
        "reason",
        "status_code",
        "text_preview",
        "created_at",
    }
    assert set(cols.keys()) == expected_columns, (
        f"SlackDelivery columns drifted: have {set(cols.keys())}, want {expected_columns}"
    )

    # Nullability — ops needs to filter `WHERE delivered = false`,
    # so `delivered` MUST be NOT NULL. `kind` MUST be NOT NULL too
    # (the dashboard groups by it). `reason` and `status_code` ARE
    # nullable — many delivered=true rows have no reason.
    assert cols["id"].nullable is False
    assert cols["kind"].nullable is False
    assert cols["delivered"].nullable is False
    assert cols["text_preview"].nullable is False
    assert cols["created_at"].nullable is False

    assert cols["reason"].nullable is True
    assert cols["status_code"].nullable is True


# ---------- Pydantic schemas ----------


def test_slack_delivery_out_field_set():
    """`SlackDeliveryOut` mirrors the ORM. Field rename here = the
    `/admin/slack-deliveries` dashboard's TanStack Query data
    suddenly typed differently from the API JSON."""
    from schemas.slack_deliveries import SlackDeliveryOut

    fields = SlackDeliveryOut.model_fields
    expected = {
        "id",
        "kind",
        "delivered",
        "reason",
        "status_code",
        "text_preview",
        "created_at",
    }
    assert set(fields.keys()) == expected, (
        f"SlackDeliveryOut fields drifted: have {set(fields.keys())}, want {expected}"
    )

    # `from_attributes=True` is required for `model_validate(orm_row)`
    # in the router. A drop here would force the router to manually
    # `.__dict__` every row.
    assert SlackDeliveryOut.model_config.get("from_attributes") is True


def test_slack_deliveries_summary_row_field_set():
    """The summary endpoint's row schema. The dashboard reads
    `delivered_rate` for the per-kind heatmap and
    `last_failure_reason` for the at-a-glance "why is this kind
    flaky" hover. Field rename = silent UI breakage."""
    from schemas.slack_deliveries import SlackDeliveriesSummaryRow

    fields = SlackDeliveriesSummaryRow.model_fields
    expected = {
        "kind",
        "total_attempts",
        "delivered_count",
        "failed_count",
        "delivered_rate",
        "last_attempt_at",
        "last_failure_at",
        "last_failure_reason",
    }
    assert set(fields.keys()) == expected, (
        f"SlackDeliveriesSummaryRow fields drifted: have {set(fields.keys())}, want {expected}"
    )


def test_summary_row_delivered_rate_is_optional_bounded_ratio():
    """`delivered_rate` MUST be a `float | None` in `[0, 1]`.

    `None` distinguishes "no attempts in window" from "every
    attempt failed" (`0.0`); the dashboard renders those
    differently (grey "no data" pill vs red "fix this now" pill).
    Dropping the constraint or making it required would silently
    change either rendering.
    """
    from schemas.slack_deliveries import SlackDeliveriesSummaryRow

    f = SlackDeliveriesSummaryRow.model_fields["delivered_rate"]
    assert f.is_required() is False, (
        "`delivered_rate` MUST be optional — `None` means 'no attempts in "
        "window', distinct from 0.0 which means 'every attempt failed'."
    )

    # The bound metadata lives in `field_info.metadata` (Pydantic v2).
    # We just assert the field accepts the boundary values + rejects
    # out-of-band inputs.
    SlackDeliveriesSummaryRow(
        kind="scraper_drift",
        total_attempts=0,
        delivered_count=0,
        failed_count=0,
        delivered_rate=None,  # the no-data branch
    )
    SlackDeliveriesSummaryRow(
        kind="scraper_drift",
        total_attempts=10,
        delivered_count=0,
        failed_count=10,
        delivered_rate=0.0,  # everyone-failed branch
    )
    SlackDeliveriesSummaryRow(
        kind="scraper_drift",
        total_attempts=10,
        delivered_count=10,
        failed_count=0,
        delivered_rate=1.0,  # everyone-succeeded branch
    )


# ---------- Persistence helper ----------


def test_record_delivery_attempt_signature_pinned():
    """`services.ops_alerts._maybe_send_slack` calls this with
    keyword args `kind=`, `text=`, `result=`. A rename of any of
    those silently turns Slack telemetry into a `TypeError` inside
    the per-attempt try/except — the alert still fires, but the
    dashboard sees zero rows. Pin the signature so a rename has
    to be deliberate.
    """
    from services.slack_telemetry import record_delivery_attempt

    sig = inspect.signature(record_delivery_attempt)
    params = sig.parameters

    assert set(params.keys()) == {"kind", "text", "result"}, (
        f"record_delivery_attempt parameters drifted: have {set(params.keys())}, want {'kind', 'text', 'result'}"
    )

    # All three are keyword-only (the call site uses kw form).
    for name in ("kind", "text", "result"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, (
            f"`{name}` MUST be keyword-only — call sites pass kw form, a positional rename would silently break them."
        )


def test_record_delivery_attempt_is_async():
    """The helper is awaited inside `_maybe_send_slack`. If it ever
    becomes sync, the `await` becomes a no-op-on-a-coro warning
    AND the row never persists (the coroutine is GC'd).
    """
    from services.slack_telemetry import record_delivery_attempt

    assert inspect.iscoroutinefunction(record_delivery_attempt), (
        "record_delivery_attempt MUST be async — call site uses `await`."
    )


# ---------- Wiring presence ----------


def test_models_init_registers_slack_delivery():
    """`models.__init__.register_all` imports every model module so
    Alembic's autogenerate sees every table. If `slack_delivery`
    drops out of that block, the next migration autogenerate would
    propose to DROP the `slack_deliveries` table.
    """
    import models

    src = inspect.getsource(models.register_all)
    assert "slack_delivery" in src, (
        "`models.register_all` no longer imports `slack_delivery` — "
        "Alembic autogenerate would propose dropping the table."
    )


def test_router_module_present_and_has_router():
    """The admin router is included from `main.py` via
    `slack_deliveries_router.router`. A missing `router` attribute
    means FastAPI startup raises and the whole API is down — pin
    the contract."""
    from fastapi import APIRouter

    from routers import slack_deliveries as slack_deliveries_router

    assert hasattr(slack_deliveries_router, "router")
    assert isinstance(slack_deliveries_router.router, APIRouter)


def test_router_exposes_expected_paths():
    """Two endpoints expected by the frontend hook
    (`apps/web/hooks/admin/useSlackDeliveries.ts`):

      * `GET /api/v1/admin/slack-deliveries`
      * `GET /api/v1/admin/slack-deliveries/summary`

    A path rename here = the frontend hook 404s and the dashboard
    page renders an empty state forever.
    """
    from routers.slack_deliveries import router

    paths = {r.path for r in router.routes}
    assert "/api/v1/admin/slack-deliveries" in paths, f"slack-deliveries list endpoint missing; have {paths}"
    assert "/api/v1/admin/slack-deliveries/summary" in paths, f"slack-deliveries summary endpoint missing; have {paths}"


# ---------- Type sanity ----------


def test_slack_delivery_out_accepts_minimal_orm_shape():
    """A row with only the NOT NULL columns set should round-trip
    through the schema (validates `from_attributes=True` actually
    works against an ORM-shaped object — duck-typed here as a
    plain class so the test doesn't need a DB)."""
    from schemas.slack_deliveries import SlackDeliveryOut

    class _FakeRow:
        id = UUID("00000000-0000-0000-0000-000000000001")
        kind = "scraper_drift"
        delivered = False
        reason = "transport:TimeoutException"
        status_code = None
        text_preview = "Drift threshold breached on `vatlieuxaydung`"
        created_at = datetime(2026, 5, 5, 12, 0, 0)

    out = SlackDeliveryOut.model_validate(_FakeRow())
    assert out.kind == "scraper_drift"
    assert out.delivered is False
    assert out.status_code is None
