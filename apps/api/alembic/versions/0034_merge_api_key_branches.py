"""Merge the two branches that descended from 0032_api_key_calls.

Both `0033_api_keys_mode` (live/test mode column on api_keys) and
`0033_audit_actor_api_key` (the parallel actor column on audit_events)
descended from `0032_api_key_calls` and have the same down_revision,
so the chain has two heads after either one runs. This file converges
them into a single head so `alembic upgrade head` is unambiguous and
`test_migrations_static.py::test_revision_chain_has_exactly_one_head`
stays green.

No upgrade/downgrade body — the two parents already wrote the schema;
a merge is a pure metadata operation as far as Alembic is concerned.

Reconstructed after the .py was deleted upstream while the .pyc
lingered in `__pycache__/`. The matching `.pyc` proves this exact
shape was running historically — see the comments in
`0033_audit_actor_api_key.py` ("the 0034_merge_api_key_branches
migration converges both 0033 heads") which document the intent.

Revision ID: 0034_merge_api_key_branches
Revises: 0033_api_keys_mode, 0033_audit_actor_api_key
Create Date: 2026-05-02
"""

from __future__ import annotations

revision = "0034_merge_api_key_branches"
# Two parents — merge migration. Both descended from
# 0032_api_key_calls so the post-merge chain has exactly one head.
down_revision = ("0033_api_keys_mode", "0033_audit_actor_api_key")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: each parent migration already applied its schema change.

    A merge migration only exists to declare that the two heads have
    been observed together. There's nothing additive to write here.
    """


def downgrade() -> None:
    """No-op: see `upgrade()`."""
