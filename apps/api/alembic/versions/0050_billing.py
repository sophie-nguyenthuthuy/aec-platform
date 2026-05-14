"""Billing — subscriptions + invoices.

Two tables:

  * `subscriptions` — one row per org. Tracks the active plan, the
    billing source (`stripe` or `vietqr`), period dates, and the
    provider's customer/subscription IDs for reconciliation. Stored
    1:1 with `organizations` so a `LEFT JOIN organizations` always
    succeeds (no missing-row surprises in plan-gate code).

  * `invoices` — one row per payment attempt. We track both successful
    and failed attempts so the audit trail covers chargebacks and
    bank-transfer disputes. `amount_vnd` is the canonical figure;
    Stripe payments in USD/EUR are recorded with their original
    `currency` + amount so we can reconcile FX at month-end.

The plan column on `organizations` is kept as the read-fast path
(every plan-gate check does `SELECT plan FROM organizations`). The
`subscriptions` row is the source of truth — its plan is mirrored
to the org row via the application layer when a webhook fires.

Revision ID: 0050_billing
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0050_billing"
down_revision: Union[str, None] = "0049_workforce"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # ---------- subscriptions ----------
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # starter | pro | enterprise
        sa.Column("plan", sa.Text, nullable=False, server_default="starter"),
        # active | past_due | cancelled | pending_payment
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        # stripe | vietqr | manual
        sa.Column("billing_source", sa.Text, nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        # Stripe-specific identifiers (NULL for vietqr/manual orgs)
        sa.Column("stripe_customer_id", sa.Text, nullable=True),
        sa.Column("stripe_subscription_id", sa.Text, nullable=True, unique=True),
        # VietQR-specific. The reference is the human-readable string
        # embedded in the QR code (e.g. "AEC-PRO-2026-05-ORG12345"). When
        # a bank transfer hits the company account with this in the memo,
        # an ops admin clicks "confirm" in /settings/billing and the row
        # flips to status=active + period_end pushed out.
        sa.Column("vietqr_reference", sa.Text, nullable=True, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "plan IN ('starter', 'pro', 'enterprise')",
            name="ck_subscriptions_plan",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'past_due', 'cancelled', 'pending_payment')",
            name="ck_subscriptions_status",
        ),
        sa.CheckConstraint(
            "billing_source IS NULL OR billing_source IN ('stripe', 'vietqr', 'manual')",
            name="ck_subscriptions_billing_source",
        ),
    )
    op.create_index("ix_subscriptions_org", "subscriptions", ["organization_id"])
    op.create_index(
        "ix_subscriptions_status_period_end",
        "subscriptions",
        ["status", "period_end"],
    )

    # Seed: every existing org gets a starter subscription row, so the
    # plan-gate code can rely on the LEFT JOIN never being NULL.
    op.execute(
        """
        INSERT INTO subscriptions (id, organization_id, plan, status, billing_source)
        SELECT gen_random_uuid(), o.id, o.plan, 'active', 'manual'
        FROM organizations o
        ON CONFLICT (organization_id) DO NOTHING
        """
    )

    # ---------- invoices ----------
    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_vnd", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default="VND"),
        sa.Column("amount_original", sa.BigInteger, nullable=True),
        # paid | failed | pending | refunded
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("provider_ref", sa.Text, nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('paid', 'failed', 'pending', 'refunded')",
            name="ck_invoices_status",
        ),
        sa.CheckConstraint(
            "provider IN ('stripe', 'vietqr', 'manual')",
            name="ck_invoices_provider",
        ),
    )
    op.create_index("ix_invoices_org_created", "invoices", ["organization_id", "created_at"])
    op.create_index("ix_invoices_provider_ref", "invoices", ["provider", "provider_ref"])


def downgrade() -> None:
    op.drop_table("invoices")
    op.drop_table("subscriptions")
