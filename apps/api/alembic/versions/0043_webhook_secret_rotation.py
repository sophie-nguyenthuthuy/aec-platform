"""webhook secret rotation — dual-secret with grace window

Currently `webhook_subscriptions.secret` is single-valued. Rotation
forces customers to delete + recreate, which:

  * Drops the failure_count history (auto-disable resets to 0 — fine).
  * Loses correlation in `webhook_deliveries` rows
    (subscription_id changes — operators can't trace "this customer's
    receiver was the same one before/after").
  * Creates a hard cutover with no grace — receivers verifying the
    OLD secret start failing the moment the new one ships, which
    means a customer doing a 2-step "deploy receiver with new secret
    THEN rotate" hits a window where every delivery fails.

Two new columns let the dispatcher carry BOTH secrets during a 24h
grace window:

  * `secret_previous TEXT` — the secret that was current right before
    the most recent rotation. NULL when there's never been a rotation
    (a fresh subscription) or when the grace has expired and a
    delivery has cleaned it up.

  * `secret_previous_expires_at TIMESTAMPTZ` — when the previous
    secret stops being honoured. The dispatcher reads this on every
    delivery; expired previous secrets are skipped (no second
    signature header emitted) and lazily NULLed on the next write.

The dispatcher signs every outbound POST with the CURRENT secret as
`X-AEC-Signature` and ALSO emits `X-AEC-Signature-Previous` (signed
with `secret_previous`) when the previous secret is non-null and not
expired. Receivers can verify EITHER signature during the grace —
typical flow:

    Day 0  ── customer clicks "Rotate secret" → old secret moves to
              `secret_previous`, new secret is current, expires 24h.
    Day 0  ── customer redeploys receiver to verify against the new
              secret. Receivers running on the OLD secret keep
              working because `X-AEC-Signature-Previous` still
              validates.
    Day 1  ── grace window passes. Dispatcher stops emitting the
              second signature. Old secret rejects.

Why 24h: matches the rotation grace window most receivers' deploy
pipelines fit inside (CI + manual rollout + smoke). Customers needing
longer can rotate twice — current = new, previous = old, then a
second rotation extends. v1 hardcodes 24h; a per-tenant override
goes in a follow-up `webhook_rotation_grace_hours` settings column
if a customer asks.

What this migration doesn't do:

  * No "two active secrets at all times" model. The grace is bounded —
    after expiry the dispatcher carries only the current secret,
    matching the old single-secret behaviour. Operationally simpler
    than a rolling-N model.
  * No audit trail of past rotations. The audit_events table picks
    up `webhook.secret_rotated` (added in services/audit.py) so the
    "who rotated when" question stays answerable.

Revision ID: 0043_webhook_secret_rotation
Revises: 0042_cron_runs
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_webhook_secret_rotation"
down_revision = "0042_cron_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both columns nullable from day one — every existing row has
    # never been rotated, so NULL is the natural baseline. The
    # service-level rotate_secret() is the only writer; existing
    # delivery code stays unchanged for rows where these are NULL.
    op.add_column(
        "webhook_subscriptions",
        sa.Column("secret_previous", sa.Text, nullable=True),
    )
    op.add_column(
        "webhook_subscriptions",
        sa.Column(
            "secret_previous_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # The dispatcher's WHERE filter on "previous still active" runs
    # on every delivery during a grace window. Index keeps the lookup
    # cheap even at scale (10k+ subscriptions). Partial — most
    # subscriptions in steady state have no previous secret, so a
    # full-column index would be mostly NULL bytes.
    op.create_index(
        "ix_webhook_subscriptions_secret_previous_expires_at",
        "webhook_subscriptions",
        ["secret_previous_expires_at"],
        postgresql_where=sa.text("secret_previous IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_subscriptions_secret_previous_expires_at",
        table_name="webhook_subscriptions",
    )
    op.drop_column("webhook_subscriptions", "secret_previous_expires_at")
    op.drop_column("webhook_subscriptions", "secret_previous")
