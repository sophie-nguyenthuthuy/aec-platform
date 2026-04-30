"""merge prefs + webhooks heads

Revision ID: ceff072b3343
Revises: 0025_notification_prefs, 0025_webhooks
Create Date: 2026-04-30 19:20:06.148336
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ceff072b3343'
down_revision: Union[str, None] = ('0025_notification_prefs', '0025_webhooks')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
