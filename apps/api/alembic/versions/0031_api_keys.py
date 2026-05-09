"""api_keys — per-org credentials for programmatic API access

Counterpart to the webhooks subsystem (callbacks OUT). Customers'
systems can now call our API with a key minted at
`/settings/api-keys`, scoped to specific resource permissions.

Schema rationale:

  * **Hashed at rest.** We store `hash` (sha256 of the raw key,
    hex-encoded) — never the raw key. The plaintext is shown to the
    user exactly once at creation. This matches industry posture
    (Stripe, GitHub PATs); a DB compromise leaks names + scopes but
    not the keys themselves.

  * **`prefix` for UX.** First 8 hex chars of the raw key, stored in
    plaintext and shown in the listing UI ("aec_a1b2c3d4… · last
    used 2 hours ago"). Disambiguates keys without exposing the
    secret.

  * **`scopes` as text[].** A bounded vocabulary lives in
    `services.api_keys.SCOPES`. Postgres array makes
    `'projects:read' = ANY(scopes)` cheap and indexable. Open enum
    deliberately: adding a scope is a deploy, not a migration.

  * **`last_used_at` + `last_used_ip`.** Updated on every successful
    auth. Lets the dashboard show stale keys ("not used for 90 days
    — consider revoking") and tells operators where a key is being
    called from when something breaks.

  * **Soft delete via `revoked_at`.** The auth lookup filters
    `WHERE revoked_at IS NULL`. We keep the row for audit (who minted
    it, who revoked it, when) — small enough that deleting buys
    nothing and history matters.

  * **Per-key rate-limit override.** `rate_limit_per_minute` is
    nullable; NULL means "use the platform default" (60 rpm). A noisy
    integration partner can be bumped to 600 without a code change.

Revision ID: 0031_api_keys
Revises: 0030_codeguard_quota_thresholds
Create Date: 2026-05-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_api_keys"
down_revision = "0030_codeguard_quota_thresholds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("name", sa.Text, nullable=False),
        # SHA-256 of the raw key; hex-encoded, 64 chars. Indexed
        # because every authenticated request does a lookup-by-hash.
        sa.Column("hash", sa.Text, nullable=False, unique=True),
        # First 8 chars of the raw key (e.g. "a1b2c3d4"). Plaintext.
        # Helps users identify the right key in the listing without
        # us re-displaying the secret.
        sa.Column("prefix", sa.Text, nullable=False),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("rate_limit_per_minute", sa.Integer),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_used_ip", sa.Text),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # Optional self-imposed expiry. Most keys are open-ended;
        # short-lived ones (vendor demo, on-call script) can set this.
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "rate_limit_per_minute IS NULL OR rate_limit_per_minute > 0",
            name="ck_api_keys_rate_limit_positive",
        ),
    )

    # Auth lookup: SELECT … WHERE hash = :h AND revoked_at IS NULL.
    # Partial index keeps revoked rows out of the hot path entirely.
    op.create_index(
        "ix_api_keys_hash_active",
        "api_keys",
        ["hash"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    # Listing: show org's keys ordered by created_at DESC.
    op.create_index(
        "ix_api_keys_org_created",
        "api_keys",
        ["organization_id", sa.text("created_at DESC")],
    )

    op.execute("ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY")
    # The auth dependency bypasses RLS (auth has to read the row to
    # establish org context). The CRUD endpoints run under tenant
    # session and obey the policy.
    op.execute(
        """
        CREATE POLICY tenant_isolation_api_keys ON api_keys
            USING (organization_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_api_keys ON api_keys")
    op.drop_index("ix_api_keys_org_created", table_name="api_keys")
    op.drop_index("ix_api_keys_hash_active", table_name="api_keys")
    op.drop_table("api_keys")
