"""invitations: tighten RLS — add WITH CHECK + canonical UUID cast

The original `0017_invitations.py` migration enabled RLS but with two
gaps vs. every other tenant-scoped table on the platform:

  1. **No `WITH CHECK` clause.** The `USING` predicate filters which
     rows a query can SEE, but `WITH CHECK` is what blocks INSERTs /
     UPDATEs from writing rows whose `organization_id` doesn't match
     the caller's GUC. Without it, an authenticated user could insert
     an invitation row with someone else's `organization_id` and the
     row would be created (the SELECT-after-INSERT would still hide it
     from them, but the row exists and the invitee could redeem the
     leaked token to gain access to a tenant the inviter has no right
     to invite into).

  2. **`organization_id::text = current_setting(...)` cast.** Every
     other policy on the platform uses
     `organization_id = current_setting('app.current_org_id', true)::uuid`.
     The `text` form works at correctness but breaks if the GUC isn't
     set (`current_setting('...')` returns the empty string, and
     `'' = 'cafe-uuid'` is FALSE, but `'' = ''` is TRUE — meaning a
     row whose `organization_id::text` happens to be `''` would leak.
     Postgres won't actually let UUIDs be empty strings, but the
     pattern is brittle and inconsistent with the codebase.

This migration drops the old policy and recreates it with `USING` +
`WITH CHECK`, both using the canonical `::uuid` cast.

Revision ID: 0018_invitations_rls_with_check
Revises: 0017_invitations
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op

revision = "0018_invitations_rls_with_check"
down_revision = "0017_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS invitations_org_isolation ON invitations")
    op.execute(
        """
        CREATE POLICY invitations_org_isolation ON invitations
            USING (organization_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS invitations_org_isolation ON invitations")
    op.execute(
        """
        CREATE POLICY invitations_org_isolation ON invitations
          FOR ALL
          USING (organization_id::text = current_setting('app.current_org_id', true))
        """
    )
