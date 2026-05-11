"""idempotency_records — replay cache for retried POST/PATCH/DELETE

Counterpart to the API key + rate-limit subsystem. Right now a partner
whose system retries on a network blip (`POST /projects` → ECONNRESET
mid-write → retry) double-creates the row. Industry-standard fix:
client sends `Idempotency-Key: <uuid>` header; server caches the
response for 24h keyed by `(api_key_id, key)` and replays it on
duplicate calls.

Schema rationale:

  * **`(api_key_id, key)` PK.** Idempotency is per-api-key. Two
    partners minting the same UUID by accident never collide because
    api_key_id partitions the namespace. We DON'T scope to (org, key)
    because a partner with two keys (live + test) might reuse the
    same UUID intentionally across them — that's a feature.

  * **`request_hash` for body verification.** Stripe's behaviour: same
    `Idempotency-Key` + different request body returns 422. Catches
    "I changed the body but reused the key by mistake" partner bugs
    that would otherwise silently replay the OLD response. The hash
    is sha256 of the canonicalised body bytes (we sort JSON keys
    before hashing so `{"a":1,"b":2}` and `{"b":2,"a":1}` collapse).

  * **`response_status` + `response_body` JSONB.** The cached payload
    is exactly what the original handler returned, including the
    envelope shape. Replays are byte-identical so a partner doing
    `response.id == cached_id` keeps passing.

  * **`request_path` + `request_method`.** Captured for the
    cache-hit-on-different-route case ("partner reused the key on
    POST /defects after using it on POST /projects" — different route
    → reject with 422). Without this, a same-key replay across routes
    would return a confusing wrong-resource response.

  * **24h horizon via retention cron.** Long enough to cover overnight
    retry storms; short enough that the table stays cheap. Joins the
    retention registry with `default_days=1`.

Revision ID: 0037_idempotency_records
Revises: 0036_scraper_rule_hits_by_id
Create Date: 2026-05-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037_idempotency_records"
down_revision = "0036_scraper_rule_hits_by_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.Text, nullable=False),
        # sha256-hex (64 chars) of the canonicalised request body.
        sa.Column("request_hash", sa.Text, nullable=False),
        # The HTTP method + path the original request hit. Echoing the
        # cached response on a different (method, path) is wrong — the
        # partner's intent is different even with the same key.
        sa.Column("request_method", sa.Text, nullable=False),
        sa.Column("request_path", sa.Text, nullable=False),
        sa.Column("response_status", sa.Integer, nullable=False),
        sa.Column("response_body", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("api_key_id", "key", name="pk_idempotency_records"),
        sa.CheckConstraint(
            "char_length(key) BETWEEN 1 AND 200",
            name="ck_idempotency_key_len",
        ),
        sa.CheckConstraint(
            "response_status >= 100 AND response_status < 600",
            name="ck_idempotency_status_range",
        ),
    )
    # Retention prune scans by `created_at`; covering index keeps the
    # cron's DELETE … WHERE created_at < ... LIMIT N cheap.
    op.create_index(
        "ix_idempotency_records_created",
        "idempotency_records",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_created", table_name="idempotency_records")
    op.drop_table("idempotency_records")
