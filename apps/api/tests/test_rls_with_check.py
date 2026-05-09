"""Integration test for the WITH CHECK RLS hardening (migration 0021).

Audit pre-fix: of 58 tenant-isolation policies, only 3 had `WITH CHECK`.
The remaining 55 enforced read isolation but accepted INSERTs / UPDATEs
that wrote rows belonging to *another* tenant. The inserter couldn't
SELECT those rows back (USING blocks that), but the rows existed in
the target tenant's data, surfacing in their dashboards / count
queries / cron jobs.

This test pins the fix as a *negative* contract: we open a session
scoped to org A, attempt to INSERT a `tasks` row carrying org B's
UUID, and expect Postgres to raise the standard RLS violation. Pick
`tasks` because it's a vanilla tenant-scoped table whose RLS policy
shape is the most common (`organization_id = current_setting(...)::uuid`)
— if the fix works for tasks, it works for the other 56.

The same body also asserts the *positive* path (org A inserting an org
A row succeeds), so the test catches a future migration that
accidentally over-tightens the policy and breaks legitimate writes.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_APP_URL = os.environ.get("COSTPULSE_RLS_APP_URL")
_ADMIN_URL = os.environ.get("COSTPULSE_RLS_ADMIN_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        not (_APP_URL and _ADMIN_URL),
        reason=(
            "Set COSTPULSE_RLS_APP_URL (aec_app) and COSTPULSE_RLS_ADMIN_URL "
            "(aec) to a live DB at migration head to run this."
        ),
    ),
]


@pytest.fixture
async def two_orgs():
    """Seed two synthetic orgs + one user that's a member of org A.

    The cleanup phase removes everything created — including any row
    the test successfully inserted via the positive path.
    """
    assert _ADMIN_URL is not None
    admin_engine = create_async_engine(_ADMIN_URL, future=True)
    factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    org_a = uuid4()
    org_b = uuid4()
    user_id = uuid4()
    project_a = uuid4()

    async with factory() as s:
        await s.execute(
            text(
                "INSERT INTO organizations (id, name, slug) VALUES "
                "(:a, 'WITH CHECK org A', :sa), (:b, 'WITH CHECK org B', :sb)"
            ),
            {
                "a": str(org_a),
                "b": str(org_b),
                "sa": f"with-check-a-{org_a}",
                "sb": f"with-check-b-{org_b}",
            },
        )
        await s.execute(
            text("INSERT INTO users (id, email) VALUES (:u, :e)"),
            {"u": str(user_id), "e": f"with-check-{user_id}@test.local"},
        )
        await s.execute(
            text(
                "INSERT INTO org_members (id, organization_id, user_id, role) "
                "VALUES (gen_random_uuid(), :org, :u, 'admin')"
            ),
            {"org": str(org_a), "u": str(user_id)},
        )
        # Project A — needed because tasks have a NOT NULL FK to projects.
        await s.execute(
            text("INSERT INTO projects (id, organization_id, name) VALUES (:pid, :org, 'WITH CHECK project A')"),
            {"pid": str(project_a), "org": str(org_a)},
        )
        await s.commit()

    yield {"org_a": org_a, "org_b": org_b, "user_id": user_id, "project_a": project_a}

    async with factory() as s:
        await s.execute(
            text("DELETE FROM tasks WHERE organization_id IN (:a, :b)"),
            {"a": str(org_a), "b": str(org_b)},
        )
        await s.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": str(project_a)})
        await s.execute(
            text("DELETE FROM org_members WHERE user_id = :u"),
            {"u": str(user_id)},
        )
        await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": str(user_id)})
        await s.execute(
            text("DELETE FROM organizations WHERE id IN (:a, :b)"),
            {"a": str(org_a), "b": str(org_b)},
        )
        await s.commit()
    await admin_engine.dispose()


async def test_with_check_blocks_cross_tenant_insert(two_orgs):
    """The exploit pre-0021: an authenticated session scoped to org A
    INSERTs a row carrying org B's UUID. After the fix, this must raise
    `new row violates row-level security policy` from Postgres."""
    assert _APP_URL is not None
    engine = create_async_engine(_APP_URL, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as s:
            await s.execute(
                text("SELECT set_config('app.current_org_id', :org, false)"),
                {"org": str(two_orgs["org_a"])},
            )
            with pytest.raises(ProgrammingError) as exc_info:
                await s.execute(
                    text(
                        """
                        INSERT INTO tasks (
                            id, organization_id, project_id, title, status, priority, created_at
                        ) VALUES (
                            gen_random_uuid(), :other_org, :pid,
                            'cross-tenant attempt', 'todo', 'normal', NOW()
                        )
                        """
                    ),
                    {
                        "other_org": str(two_orgs["org_b"]),
                        "pid": str(two_orgs["project_a"]),
                    },
                )
                await s.commit()
            # Postgres surfaces the policy violation as InsufficientPrivilege
            # / FeatureNotSupported depending on driver. The error message
            # is the stable contract.
            assert "row-level security" in str(exc_info.value).lower()
    finally:
        await engine.dispose()


async def test_with_check_allows_same_tenant_insert(two_orgs):
    """Positive control: an org-A session inserting into org A still
    works. Catches a future over-tightening that breaks legitimate writes."""
    assert _APP_URL is not None
    engine = create_async_engine(_APP_URL, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as s:
            await s.execute(
                text("SELECT set_config('app.current_org_id', :org, false)"),
                {"org": str(two_orgs["org_a"])},
            )
            await s.execute(
                text(
                    """
                    INSERT INTO tasks (
                        id, organization_id, project_id, title, status, priority, created_at
                    ) VALUES (
                        gen_random_uuid(), :org, :pid,
                        'same-tenant insert', 'todo', 'normal', NOW()
                    )
                    """
                ),
                {
                    "org": str(two_orgs["org_a"]),
                    "pid": str(two_orgs["project_a"]),
                },
            )
            await s.commit()

            count = (
                await s.execute(
                    text("SELECT count(*) FROM tasks WHERE project_id = :pid AND title = 'same-tenant insert'"),
                    {"pid": str(two_orgs["project_a"])},
                )
            ).scalar_one()
            assert count == 1
    finally:
        await engine.dispose()
