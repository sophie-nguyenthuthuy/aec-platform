"""merge parallel module heads (codeguard, drawbridge, handover)

Revision ID: 0006_merge_heads
Revises: 0005_codeguard, 0004_drawbridge, 0004_handover
Create Date: 2026-04-23
"""
from __future__ import annotations

revision = "0006_merge_heads"
down_revision = ("0005_codeguard", "0004_drawbridge", "0004_handover")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
