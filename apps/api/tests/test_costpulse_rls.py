"""End-to-end RLS isolation test for CostPulse tenant scoping.

Runs against a real Postgres (not the FakeAsyncSession). Skipped unless
`COSTPULSE_RLS_DB_URL` is set to an asyncpg URL pointing at a live DB
with the migrations applied. Locally:

    export COSTPULSE_RLS_DB_URL=postgresql+asyncpg://aec:aec@localhost:55432/aec
    pytest tests/test_costpulse_rls.py

Important: the dev role (`aec`) is a superuser with BYPASSRLS, so RLS
policies are silently skipped under it. Migration 0010_app_role
provisions `aec_app` as NOBYPASSRLS — the role the API + workers
actually use at runtime. These tests `SET LOCAL ROLE aec_app` so the
policies fire against the same role that serves production traffic.
If this test regresses, RLS is broken for real users — not just for a
synthetic test role.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DB_URL = os.environ.get("COSTPULSE_RLS_DB_URL")

# Must match migration 0010_app_role and docker-compose.yml. Keeping this a
# constant (rather than an env var) intentionally: drift between the role
# the app uses and the role the test exercises would silently re-open the
# BYPASSRLS hole this suite exists to prevent.
_APP_ROLE = "aec_app"

pytestmark = [
    pytest.mark.asyncio,
    # `integration` is gated by `--integration` (see apps/api/tests/conftest.py).
    # The skipif below is a runtime backstop for the case where someone runs
    # with `--integration` but forgot the env var.
    pytest.mark.integration,
    pytest.mark.skipif(
        _DB_URL is None,
        reason="COSTPULSE_RLS_DB_URL not set — integration test requires a live DB",
    ),
]


@pytest.fixture
async def engine():
    assert _DB_URL is not None
    engine = create_async_engine(_DB_URL, future=True)

    # Sanity-check that migration 0010_app_role has run. If an operator
    # points the test at a DB that predates it, we want to fail loudly
    # with a clear message rather than reporting "policy didn't fire".
    async with engine.connect() as conn:
        exists = (
            await conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
                {"r": _APP_ROLE},
            )
        ).scalar()
        if not exists:
            pytest.skip(
                f"role {_APP_ROLE!r} missing — run `alembic upgrade head` so migration 0010_app_role provisions it."
            )

    yield engine
    await engine.dispose()


@pytest.fixture
async def unscoped_session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s


@pytest.fixture
async def two_orgs(unscoped_session: AsyncSession):
    """Create two fresh orgs + one user each + one estimate each."""
    org_a = uuid4()
    org_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    estimate_a = uuid4()
    estimate_b = uuid4()

    await unscoped_session.execute(
        text(
            "INSERT INTO organizations (id, name, slug) VALUES "
            "(:a, 'Org A (rls-test)', :sa), (:b, 'Org B (rls-test)', :sb)"
        ),
        {"a": str(org_a), "b": str(org_b), "sa": f"rls-a-{org_a}", "sb": f"rls-b-{org_b}"},
    )
    await unscoped_session.execute(
        text("INSERT INTO users (id, email) VALUES (:a, :ea), (:b, :eb)"),
        {"a": str(user_a), "b": str(user_b), "ea": f"rls-a-{user_a}@test.local", "eb": f"rls-b-{user_b}@test.local"},
    )
    await unscoped_session.execute(
        text(
            "INSERT INTO estimates (id, organization_id, name, version, status, created_by) "
            "VALUES (:id, :org, 'A estimate', 1, 'draft', :u)"
        ),
        {"id": str(estimate_a), "org": str(org_a), "u": str(user_a)},
    )
    await unscoped_session.execute(
        text(
            "INSERT INTO estimates (id, organization_id, name, version, status, created_by) "
            "VALUES (:id, :org, 'B estimate', 1, 'draft', :u)"
        ),
        {"id": str(estimate_b), "org": str(org_b), "u": str(user_b)},
    )
    await unscoped_session.commit()

    yield {
        "org_a": org_a,
        "org_b": org_b,
        "user_a": user_a,
        "user_b": user_b,
        "estimate_a": estimate_a,
        "estimate_b": estimate_b,
    }

    # Cleanup in FK-safe order.
    await unscoped_session.execute(
        text("DELETE FROM boq_items WHERE estimate_id IN (:a, :b)"),
        {"a": str(estimate_a), "b": str(estimate_b)},
    )
    await unscoped_session.execute(
        text("DELETE FROM estimates WHERE id IN (:a, :b)"),
        {"a": str(estimate_a), "b": str(estimate_b)},
    )
    await unscoped_session.execute(
        text("DELETE FROM users WHERE id IN (:a, :b)"),
        {"a": str(user_a), "b": str(user_b)},
    )
    await unscoped_session.execute(
        text("DELETE FROM organizations WHERE id IN (:a, :b)"),
        {"a": str(org_a), "b": str(org_b)},
    )
    await unscoped_session.commit()


async def _enter_rls_scope(session: AsyncSession, org_id) -> None:
    """Drop to the non-BYPASSRLS app role and set the tenant org id.

    This mirrors what the real request-scoped dependency does in
    apps/api/db/session.py — set_config('app.current_org_id', ...) on
    every session checkout. The `SET LOCAL ROLE` is the test-only piece
    that simulates production: in prod the connection *starts* as
    aec_app (via DATABASE_URL), while this test uses the superuser
    connection for setup + then drops to aec_app inside the transaction.
    """
    await session.execute(text(f"SET LOCAL ROLE {_APP_ROLE}"))
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org, true)"),
        {"org": str(org_id)},
    )


async def test_rls_blocks_cross_org_estimate_read(engine, two_orgs):
    """With `app.current_org_id = A` and no BYPASSRLS, cannot see org B's estimate."""
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        await s.begin()
        await _enter_rls_scope(s, two_orgs["org_a"])

        rows = (
            await s.execute(
                text("SELECT id, organization_id FROM estimates WHERE id IN (:a, :b)"),
                {
                    "a": str(two_orgs["estimate_a"]),
                    "b": str(two_orgs["estimate_b"]),
                },
            )
        ).all()

        visible_ids = {r[0] for r in rows}
        assert two_orgs["estimate_a"] in visible_ids
        assert two_orgs["estimate_b"] not in visible_ids, "RLS leak: scoped to org A but saw org B's estimate"
        await s.rollback()


async def test_rls_blocks_cross_org_boq_read(engine, two_orgs):
    """boq_items uses a join-based policy — isolation must still hold."""
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    boq_a = uuid4()
    boq_b = uuid4()
    async with factory() as s:
        await s.execute(
            text(
                "INSERT INTO boq_items (id, estimate_id, description) VALUES (:ia, :ea, 'A item'), (:ib, :eb, 'B item')"
            ),
            {
                "ia": str(boq_a),
                "ea": str(two_orgs["estimate_a"]),
                "ib": str(boq_b),
                "eb": str(two_orgs["estimate_b"]),
            },
        )
        await s.commit()

    try:
        async with factory() as s:
            await s.begin()
            await _enter_rls_scope(s, two_orgs["org_a"])
            rows = (
                await s.execute(
                    text("SELECT id FROM boq_items WHERE id IN (:a, :b)"), {"a": str(boq_a), "b": str(boq_b)}
                )
            ).all()
            ids = {r[0] for r in rows}
            assert boq_a in ids
            assert boq_b not in ids
            await s.rollback()
    finally:
        async with factory() as s:
            await s.execute(text("DELETE FROM boq_items WHERE id IN (:a, :b)"), {"a": str(boq_a), "b": str(boq_b)})
            await s.commit()


async def test_rls_org_switch_flips_visibility(engine, two_orgs):
    """Sanity: scoping to org B shows B's estimate and hides A's."""
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        await s.begin()
        await _enter_rls_scope(s, two_orgs["org_b"])
        rows = (
            await s.execute(
                text("SELECT id FROM estimates WHERE id IN (:a, :b)"),
                {
                    "a": str(two_orgs["estimate_a"]),
                    "b": str(two_orgs["estimate_b"]),
                },
            )
        ).all()
        ids = {r[0] for r in rows}
        assert two_orgs["estimate_b"] in ids
        assert two_orgs["estimate_a"] not in ids
        await s.rollback()
