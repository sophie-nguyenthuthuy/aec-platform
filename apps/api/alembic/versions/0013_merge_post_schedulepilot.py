"""merge parallel module heads after schedulepilot (scraper_runs, submittals)

Revision ID: 0013_merge_post_schedulepilot
Revises: 0012_scraper_runs, 0012_submittals
Create Date: 2026-04-26

Two modules landed migrations off the same parent (0011_schedulepilot)
without coordinating — same pattern as 0006_merge_heads. This empty
merge revision unifies them so `alembic upgrade head` resolves to a
single head again.
"""

from __future__ import annotations

revision = "0013_merge_post_schedulepilot"
down_revision = ("0012_scraper_runs", "0012_submittals")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op merge — both branches' DDL already applied independently."""
    pass


def downgrade() -> None:
    """No-op merge — branches downgrade through their own paths."""
    pass
