"""api_key_calls — minute-bucketed call counts for usage observability

Counterpart to api_keys (0031). Right now we know `last_used_at` but
not "how many calls per minute / hour / day". A per-call audit row
would balloon (a busy partner pulls 1000s of rows/min); the rollup is
one row per (api_key_id, minute, success_bucket) so 60 rpm sustained
costs 1 INSERT/min instead of 60.

Schema rationale:

  * **(api_key_id, minute_bucket, success)** as the natural key with a
    UNIQUE constraint. The auth-dependency writer does
    `INSERT … ON CONFLICT (...) DO UPDATE SET count = count + 1` —
    one round trip, no race.

  * **`success` boolean.** Splits 2xx/3xx (success=true) from 4xx/5xx
    (success=false). The dashboard surfaces an error rate without a
    second query. Status code itself isn't persisted — too high
    cardinality for a rollup; deep-dive lookups go through audit_events
    instead.

  * **No organization_id.** The api_key FK already pins it; carrying
    a denormalised copy doesn't help the admin-page queries (they JOIN
    to api_keys for the name + scopes anyway). Skipping the column +
    RLS makes the writer cheaper.

  * **Retention.** This table joins the four already on the registry;
    `services.retention.RETENTION_POLICIES` gets a new entry default
    30d. JSONB-blob row size is small (~70 bytes), but a busy org can
    still produce 1500 rows/key/day → cap at 30d to keep the table
    bounded.

  * **Indexes.** PK is `(api_key_id, minute_bucket, success)`.
    Listings group by api_key_id over a window so the leading column
    of the PK already covers them. A separate `(minute_bucket DESC)`
    index helps the cross-key admin view ("top keys this hour").

Revision ID: 0032_api_key_calls
Revises: 0031_api_keys
Create Date: 2026-05-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032_api_key_calls"
down_revision = "0031_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_key_calls",
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Truncated-to-the-minute UTC timestamp. Postgres
        # `date_trunc('minute', NOW())` produces this value; the
        # writer does the same in Python before binding so both
        # paths agree to the second.
        sa.Column("minute_bucket", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint(
            "api_key_id",
            "minute_bucket",
            "success",
            name="pk_api_key_calls",
        ),
        sa.CheckConstraint("count >= 0", name="ck_api_key_calls_count_nonneg"),
    )
    # For the cross-key "top keys this hour" admin view.
    op.create_index(
        "ix_api_key_calls_bucket_desc",
        "api_key_calls",
        [sa.text("minute_bucket DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_api_key_calls_bucket_desc", table_name="api_key_calls")
    op.drop_table("api_key_calls")
