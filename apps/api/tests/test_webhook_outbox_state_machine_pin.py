"""Pin the webhook-outbox state machine + ORM column shape.

The outbox model has four moving parts that must stay in lockstep
across the model, the dispatcher cron, and (eventually) the admin
UI:

  * **Status literal values** — `pending`, `in_flight`, `delivered`,
    `failed`. The dispatcher pulls `status='pending'` rows; on
    success transitions to `delivered`; on retryable failure stays
    in `pending` with a bumped `next_retry_at`; on permanent failure
    transitions to `failed`. A literal-string typo anywhere on this
    chain (`pending` → `Pending`, `delivered` → `delivered_ok`)
    silently breaks the cron's drain query — rows get inserted but
    never sent, and ops only learns when a customer asks "where's
    my webhook."

  * **Default initial status** — `pending`. ORM default lives on the
    column. A regression that defaulted to `delivered` would mark
    every fresh row as already-sent and the dispatcher would never
    pick them up.

  * **Retry budget constants** — `_BACKOFF_MINUTES` + siblings in
    `services.webhooks`. Already pinned in
    `test_webhooks_backoff_schedule.py`. THIS pin covers the
    column shape that the cron drains.

  * **Required columns** — `subscription_id` (FK), `organization_id`
    (denormalised for RLS scoping per migration 0025), `event_type`,
    `payload` (JSONB), `status`. The admin UI `/admin/webhooks/...`
    reads every one of these by name; rename = forensic drill-down
    breaks.

This file is a read-only contract pin. Survives reverts; if any
of the columns or the documented status set drifts, this test
fires RED on the next CI run.
"""

from __future__ import annotations

# ---------- ORM column shape ----------


def test_webhook_delivery_table_name_pinned():
    """Migration `0025_webhooks` created `webhook_deliveries`; the
    ORM `__tablename__` MUST match. A rename here points the cron's
    raw-SQL UPDATE statements at a non-existent table."""
    from models.webhooks import WebhookDelivery

    assert WebhookDelivery.__tablename__ == "webhook_deliveries"


def test_webhook_delivery_columns_pinned():
    """Required columns the dispatcher + admin UI both read by name.
    The cron's `UPDATE webhook_deliveries SET status = ...` and the
    admin endpoint's row-out projection both reference these names —
    a rename has to be a deliberate cross-cut change.
    """
    from models.webhooks import WebhookDelivery

    cols = {c.name: c for c in WebhookDelivery.__table__.columns}
    expected = {
        "id",
        "subscription_id",
        "organization_id",
        "event_type",
        "payload",
        "status",
        "attempt_count",
        "next_retry_at",
        "response_status",
        "response_body_snippet",
        "error_message",
        "delivered_at",
        "created_at",
    }
    assert set(cols.keys()) == expected, f"WebhookDelivery columns drifted: have {set(cols.keys())}, want {expected}"

    # NOT NULL invariants — the dispatcher's drain query filters on
    # `status` and `next_retry_at`, and the cron groups by `org_id`
    # for the failure-rate metric. NULL in any of these = silently
    # excluded from the drain.
    for required in ("id", "subscription_id", "organization_id", "event_type", "payload", "status"):
        assert cols[required].nullable is False, (
            f"WebhookDelivery.{required} became nullable — dispatcher's WHERE clauses would silently exclude null rows."
        )

    # Optional columns — populated only after first delivery attempt.
    for optional in (
        "next_retry_at",
        "response_status",
        "response_body_snippet",
        "error_message",
        "delivered_at",
    ):
        assert cols[optional].nullable is True, (
            f"WebhookDelivery.{optional} is NOT NULL — fresh rows have "
            "no response info, every insert would now violate the constraint."
        )


def test_webhook_delivery_status_default_is_pending():
    """The ORM-level default for fresh rows. A regression that
    defaulted to `delivered` would mark every queued event as
    already-sent and the dispatcher cron would never drain them.

    The migration also asserts a server-side default of `'pending'`;
    we pin the ORM-level mirror so the Python-side instantiation
    path matches.
    """
    from models.webhooks import WebhookDelivery

    cols = {c.name: c for c in WebhookDelivery.__table__.columns}
    status_col = cols["status"]

    # SQLAlchemy stores column defaults on `.default` (a ColumnDefault
    # wrapper around the literal value). A scalar default's `.arg`
    # holds the literal.
    assert status_col.default is not None, (
        "WebhookDelivery.status lost its ORM default. Fresh rows would "
        "insert with `NULL` and the NOT NULL constraint would 500 every "
        "publish call."
    )
    default_value = getattr(status_col.default, "arg", status_col.default)
    assert default_value == "pending", (
        f"WebhookDelivery.status default drifted to {default_value!r}; "
        "must be 'pending' or the dispatcher won't drain freshly-inserted rows."
    )


def test_webhook_delivery_attempt_count_default_zero():
    """Fresh rows MUST start at `attempt_count=0`. The cron's backoff
    schedule (`_BACKOFF_MINUTES[attempt_count]`) is indexed off this;
    a regression that defaulted to 1 would skip the first retry rung
    and effectively shorten every retry budget by one attempt."""
    from models.webhooks import WebhookDelivery

    cols = {c.name: c for c in WebhookDelivery.__table__.columns}
    default = cols["attempt_count"].default
    assert default is not None, "attempt_count lost its default"
    assert getattr(default, "arg", default) == 0


# ---------- State machine literal values ----------


def test_dispatcher_status_transitions_in_source():
    """Pin the four literal status values that the dispatcher
    transitions rows through. We grep the source rather than
    importing constants because the values are inlined string
    literals in the dispatcher's raw SQL (a deliberate choice —
    raw SQL is easier to audit in isolation).

    A typo in any of these — `delivered` → `Delivered`, `failed` →
    `failure` — would silently break the dashboard's `WHERE status =
    'delivered'` queries (no rows ever match the typo'd literal).
    """
    import inspect

    import services.webhooks as webhooks_mod

    src = inspect.getsource(webhooks_mod)

    # The dispatcher must mention all four literals. If a regression
    # renamed any of them, this test fires before the next dispatch
    # cron runs.
    for status in ("'pending'", "'in_flight'", "'delivered'", "'failed'"):
        assert status in src, (
            f"services.webhooks no longer references status literal {status}. "
            f"If renamed, the dispatcher AND every admin query has to move "
            f"in lockstep — pin the literal here."
        )


def test_webhook_delivery_status_is_text_not_enum():
    """We deliberately use `Text` (not a PG enum) for `status`. The
    rationale (per migration 0025) is operational — adding a new
    state without a migration during an incident is valuable. Pin
    this so a "tighten up the schema" refactor that converts to an
    enum has to happen with an explicit migration + redeploy
    sequence rather than slipping in.
    """
    from sqlalchemy import Text

    from models.webhooks import WebhookDelivery

    cols = {c.name: c for c in WebhookDelivery.__table__.columns}
    status_col_type = cols["status"].type

    assert isinstance(status_col_type, Text), (
        f"WebhookDelivery.status type is {type(status_col_type).__name__}; "
        "want Text. Conversion to PGEnum requires a migration and would break "
        "the operational ability to add states ad-hoc during incidents."
    )


# ---------- Subscription pairing ----------


def test_webhook_subscription_columns_pinned():
    """The parent `webhook_subscriptions` table — referenced via FK
    from every delivery row. Same revert-tripwire role as the
    delivery pin."""
    from models.webhooks import WebhookSubscription

    cols = {c.name for c in WebhookSubscription.__table__.columns}
    expected = {
        "id",
        "organization_id",
        "url",
        "secret",
        "event_types",
        "enabled",
        "last_delivery_at",
        "failure_count",
        "created_by",
        "created_at",
    }
    assert cols == expected, f"WebhookSubscription columns drifted: have {cols}, want {expected}"


def test_webhook_subscription_event_types_default_empty_list():
    """Per the migration, an empty `event_types` array means
    "subscribe to all events" (the matcher treats `[]` as a wildcard).
    A default of `null` would crash the matcher (`event in null`);
    a default of `["*"]` would require special-casing everywhere.
    Pin the empty-list default."""
    from models.webhooks import WebhookSubscription

    cols = {c.name: c for c in WebhookSubscription.__table__.columns}
    default = cols["event_types"].default
    assert default is not None, "event_types lost its default"

    # SQLAlchemy wraps `default=list` as a `ColumnDefault` whose
    # `.arg` is the bare `list` class itself. The wrapper's `.is_callable`
    # flag tells us SA will invoke it; the underlying `.arg` should be
    # `list` (or any callable returning [])  — we just check both.
    arg = default.arg
    if arg is list:
        # Bare callable form: `default=list`. SQLAlchemy will call
        # this per-insert and the result is `[]`. This is the
        # documented shape per the model file.
        produced = []
    elif callable(arg):
        # Context-aware default — call with no args (some wrappers
        # accept zero-arg call); fall back to a documented-shape
        # assertion if SA's wrapper rejects it.
        try:
            produced = arg()
        except TypeError:
            # SQLAlchemy ColumnDefault wraps the callable so it
            # receives an `ExecutionContext`. Trust the source-of-
            # truth check: `default=list` in the model file.
            import inspect as _i

            from models.webhooks import WebhookSubscription as _WS

            src = _i.getsource(_WS)
            assert "default=list" in src, (
                "WebhookSubscription.event_types default isn't `default=list`. "
                "The matcher relies on `[]` as the 'all event types' wildcard."
            )
            return
    else:
        produced = arg

    assert produced == [], (
        f"event_types default drifted to {produced!r}; want [] (the wildcard sentinel for 'all event types')."
    )
