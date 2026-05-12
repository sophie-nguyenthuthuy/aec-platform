"""merge codeguard fixes with einvoice+greenmark feature branch

Revision ID: c16cdbca5b41
Revises: 0046_codeguard_user_usage, 0047_greenmark
Create Date: 2026-05-12 14:26:30.755757
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c16cdbca5b41'
down_revision: Union[str, None] = ('0046_codeguard_user_usage', '0047_greenmark')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
