"""rfqs.accepted_supplier_id + accepted_at — buyer "pick a winner" trail

Closes the supplier-portal decision loop. When the buyer accepts a
supplier's quote (`POST /api/v1/costpulse/rfq/{id}/accept`), we stamp
who they picked and when, and the per-RFQ status flips to `closed`.

Choosing two columns rather than rolling this into the JSONB
`responses[]` blob:

  * `accepted_supplier_id` is queryable for analytics ("who's our
    most-picked supplier?") without unrolling JSON.
  * Foreign-key constraint to `suppliers.id` — a malformed UUID can't
    sneak in.
  * `ON DELETE SET NULL` because deleting a supplier shouldn't cascade
    away the historical decision; it should just orphan the reference.

Revision ID: 0024_rfq_acceptance
Revises: 0023_codeguard_quotas
Create Date: 2026-04-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0024_rfq_acceptance"
down_revision = "0023_codeguard_quotas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rfqs",
        sa.Column(
            "accepted_supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "rfqs",
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("rfqs", "accepted_at")
    op.drop_column("rfqs", "accepted_supplier_id")
