"""Integration tests for the two-factory split in db.session.

The whole point of migration 0010_app_role + AdminSessionFactory is:

  * `SessionFactory` binds to DATABASE_URL (aec_app, NOBYPASSRLS). Regular
    request handlers use this. RLS policies are enforced.
  * `AdminSessionFactory` binds to DATABASE_URL_ADMIN (aec, BYPASSRLS).
    Background jobs that legitimately need cross-tenant visibility
    (price alerts, bidradar scrape, weekly report discovery) use this.

This suite asserts the invariant directly: with two orgs, a query that
sees one org's data under SessionFactory must see *both* orgs' data
under AdminSessionFactory. If the docker-compose env ever drifts
(e.g. DATABASE_URL_ADMIN accidentally points at aec_app), this test
catches it before the cron silently does nothing in prod.

Skipped unless COSTPULSE_RLS_DB_URL + COSTPULSE_RLS_ADMIN_URL are set
to asyncpg URLs for a live DB at migration head.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_APP_URL = os.environ.get("COSTPULSE_RLS_APP_URL")  # aec_app (NOBYPASSRLS)
_ADMIN_URL = os.environ.get("COSTPULSE_RLS_ADMIN_URL")  # aec (BYPASSRLS)

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
async def engines():
    assert _APP_URL and _ADMIN_URL
    app_engine = create_async_engine(_APP_URL, future=True)
    admin_engine = create_async_engine(_ADMIN_URL, future=True)
    yield app_engine, admin_engine
    await app_engine.dispose()
    await admin_engine.dispose()


@pytest.fixture
async def two_price_alerts(engines):
    """Seed one price alert for each of two synthetic orgs."""
    _, admin_engine = engines
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    org_a = uuid4()
    org_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    alert_a = uuid4()
    alert_b = uuid4()

    async with admin_factory() as s:
        await s.execute(text(
            "INSERT INTO organizations (id, name, slug) VALUES "
            "(:a, 'A (admin-test)', :sa), (:b, 'B (admin-test)', :sb)"
        ), {"a": str(org_a), "b": str(org_b),
            "sa": f"admin-a-{org_a}", "sb": f"admin-b-{org_b}"})
        await s.execute(text(
            "INSERT INTO users (id, email) VALUES (:a, :ea), (:b, :eb)"
        ), {"a": str(user_a), "b": str(user_b),
            "ea": f"admin-a-{user_a}@test.local",
            "eb": f"admin-b-{user_b}@test.local"})
        await s.execute(text(
            "INSERT INTO price_alerts "
            "(id, organization_id, user_id, material_code, threshold_pct) "
            "VALUES (:ia, :oa, :ua, 'CONC_C30', 5), "
            "       (:ib, :ob, :ub, 'CONC_C30', 5)"
        ), {
            "ia": str(alert_a), "oa": str(org_a), "ua": str(user_a),
            "ib": str(alert_b), "ob": str(org_b), "ub": str(user_b),
        })
        await s.commit()

    yield {"alert_a": alert_a, "alert_b": alert_b,
           "org_a": org_a, "org_b": org_b,
           "user_a": user_a, "user_b": user_b}

    async with admin_factory() as s:
        await s.execute(text("DELETE FROM price_alerts WHERE id IN (:a, :b)"),
                        {"a": str(alert_a), "b": str(alert_b)})
        await s.execute(text("DELETE FROM users WHERE id IN (:a, :b)"),
                        {"a": str(user_a), "b": str(user_b)})
        await s.execute(text("DELETE FROM organizations WHERE id IN (:a, :b)"),
                        {"a": str(org_a), "b": str(org_b)})
        await s.commit()


async def test_admin_factory_sees_both_orgs_app_factory_sees_zero(
    engines, two_price_alerts
):
    """Without app.current_org_id, aec_app sees 0 alerts, aec sees all.

    This is the whole load-bearing contract. If it ever flips, one of:
      * 0010_app_role didn't run
      * DATABASE_URL_ADMIN points at the wrong role
      * price_alerts lost its RLS policy
    …and whoever broke it will get a loud, unambiguous test failure
    rather than a silent cron that processes zero alerts.
    """
    app_engine, admin_engine = engines
    app_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    ids = [str(two_price_alerts["alert_a"]), str(two_price_alerts["alert_b"])]

    # aec_app, no `SET app.current_org_id` — RLS blocks everything.
    async with app_factory() as s:
        rows = (await s.execute(
            text("SELECT id FROM price_alerts WHERE id = ANY(:ids)"),
            {"ids": ids},
        )).all()
        assert rows == [], (
            "aec_app saw cross-tenant rows without app.current_org_id — "
            "either price_alerts lost its RLS policy or the role has BYPASSRLS"
        )

    # aec superuser — BYPASSRLS should let us see both.
    async with admin_factory() as s:
        rows = (await s.execute(
            text("SELECT id FROM price_alerts WHERE id = ANY(:ids)"),
            {"ids": ids},
        )).all()
        got = {r[0] for r in rows}
        assert two_price_alerts["alert_a"] in got
        assert two_price_alerts["alert_b"] in got


async def test_app_factory_with_org_scope_sees_only_that_org(
    engines, two_price_alerts
):
    """With app.current_org_id=A, aec_app sees A's alert but not B's."""
    app_engine, _ = engines
    app_factory = async_sessionmaker(app_engine, expire_on_commit=False)

    async with app_factory() as s:
        await s.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"),
            {"org": str(two_price_alerts["org_a"])},
        )
        ids = [str(two_price_alerts["alert_a"]), str(two_price_alerts["alert_b"])]
        rows = (await s.execute(
            text("SELECT id FROM price_alerts WHERE id = ANY(:ids)"),
            {"ids": ids},
        )).all()
        got = {r[0] for r in rows}
        assert two_price_alerts["alert_a"] in got
        assert two_price_alerts["alert_b"] not in got, (
            "RLS leak: aec_app scoped to org A saw org B's alert"
        )
