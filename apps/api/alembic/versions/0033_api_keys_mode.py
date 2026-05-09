"""api_keys.mode column — live vs test partitioning

Test-mode keys route to a synthetic-data layer instead of real tenant
data. Lets a partner build + verify their integration end-to-end
before any production data flows.

Schema rationale:

  * **Single column on `api_keys`.** No second table. The hot path
    (verify_key) already SELECTs the row, so adding `mode` to the
    SELECT is free. A separate `test_keys` table would mean two index
    lookups per request and double the CRUD surface.

  * **Default `'live'`.** Existing keys keep their behaviour without
    any data migration. Forward-compat: every new mode defaults to
    safe (live = real data; new modes opt in).

  * **CHECK constraint.** `mode IN ('live', 'test')`. Keeps drift
    out of the column even if a future migration adds a third value
    and an old worker writes the wrong literal.

What this migration DOES NOT do:
  * Create the synthetic-data fixture set. That lives in code under
    `services.sandbox`.
  * Add a "sandbox org" concept. The sandbox-org spinner is its own
    handler; it creates a real org with a 30-day expiry seeded with
    the same fixtures.

Revision ID: 0033_api_keys_mode
Revises: 0032_api_key_calls
Create Date: 2026-05-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_api_keys_mode"
down_revision = "0032_api_key_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "mode",
            sa.Text,
            nullable=False,
            server_default=sa.text("'live'"),
        ),
    )
    op.create_check_constraint(
        "ck_api_keys_mode",
        "api_keys",
        "mode IN ('live', 'test')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_api_keys_mode", "api_keys", type_="check")
    op.drop_column("api_keys", "mode")
