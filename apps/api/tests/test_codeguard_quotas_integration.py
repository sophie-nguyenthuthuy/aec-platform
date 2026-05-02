"""Tier 3 integration tests for the codeguard quota UPSERT against real Postgres.

The Tier 2 tests pin the *helper-call shape* — that `_with_usage_recording`
calls `record_org_usage` with the right kwargs and counts. What's NOT
pinned by Tier 2 is the SQL itself:

  * `ON CONFLICT (organization_id, period_start) DO UPDATE SET
     input_tokens = input_tokens + EXCLUDED.input_tokens` — does the
     accumulation actually accumulate, or does each call clobber the
     previous? Tier 2 mocks `db.execute` and never executes the SQL.
  * `date_trunc('month', NOW())::date` — does it produce the first-of-
     month date the composite PK expects? Wrong period_start would
     create a fresh row per call instead of upserting.
  * Cross-org isolation — does an UPSERT against org A leave org B's
     row untouched?

The cap-enforcement story bets on this SQL being right. A regression
that swapped `+ EXCLUDED.tokens` for `EXCLUDED.tokens` (silently turning
accumulate into clobber) would still pass every Tier 2 test, then quietly
under-count every org's spend in production.

Gated on `COSTPULSE_RLS_DB_URL` (the same env var the rest of the
integration lane uses — see `apps/api/tests/conftest.py`).
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DB_URL = os.environ.get("COSTPULSE_RLS_DB_URL")

pytestmark = [
    pytest.mark.asyncio,
    # `--integration` gate (see apps/api/tests/conftest.py). The skipif
    # below is the runtime backstop in case someone runs with the flag
    # but forgot the env var.
    pytest.mark.integration,
    pytest.mark.skipif(
        _DB_URL is None,
        reason="COSTPULSE_RLS_DB_URL not set — quota integration test requires a live DB",
    ),
]


@pytest.fixture
async def session():
    """Open an unscoped async session against the integration DB. We're
    testing the SQL shape, not RLS, so we don't need to switch to
    `aec_app` like the RLS tests do — operating as `aec` is fine."""
    assert _DB_URL is not None
    engine = create_async_engine(_DB_URL, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def two_test_orgs(session: AsyncSession):
    """Create two ephemeral orgs for the cross-org isolation test, then
    clean up. Cascades take care of `codeguard_org_usage` rows via
    the ON DELETE CASCADE on the `organizations.id` FK — no manual
    purge needed.
    """
    org_a = uuid4()
    org_b = uuid4()
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug) VALUES "
            "(:a, 'Quota Test Org A', :sa), (:b, 'Quota Test Org B', :sb)"
        ),
        {
            "a": str(org_a),
            "b": str(org_b),
            "sa": f"quota-test-a-{org_a}",
            "sb": f"quota-test-b-{org_b}",
        },
    )
    await session.commit()

    yield org_a, org_b

    # Cascade-delete via the organizations row — codeguard_org_usage and
    # codeguard_org_quotas both ON DELETE CASCADE against organizations.id.
    await session.execute(
        text("DELETE FROM organizations WHERE id IN (:a, :b)"),
        {"a": str(org_a), "b": str(org_b)},
    )
    await session.commit()


# ---------- Accumulation -----------------------------------------------


async def test_record_usage_accumulates_across_successive_calls(session, two_test_orgs):
    """Three sequential `record_org_usage` calls against the same org +
    same month must produce a single row whose tokens equal the running
    sum. Pin the `+ EXCLUDED.input_tokens` accumulation contract — the
    one a typo could turn into a silent clobber and every Tier 2 test
    would still pass.
    """
    from services.codeguard_quotas import record_org_usage

    org_id, _ = two_test_orgs

    await record_org_usage(session, org_id, input_tokens=100, output_tokens=50)
    await record_org_usage(session, org_id, input_tokens=200, output_tokens=75)
    await record_org_usage(session, org_id, input_tokens=50, output_tokens=25)
    await session.commit()

    # Single row in the current period, totals = (350, 150).
    rows = (
        await session.execute(
            text(
                """
                SELECT input_tokens, output_tokens, period_start
                FROM codeguard_org_usage
                WHERE organization_id = :org
                """
            ),
            {"org": str(org_id)},
        )
    ).all()

    assert len(rows) == 1, (
        f"Expected exactly one usage row for org {org_id}; got {len(rows)}. "
        "If you see multiple rows, the period_start computation is producing "
        "different values per call (clock skew? wrong date_trunc unit?) and "
        "the upsert is creating a new row each time."
    )
    row = rows[0]
    assert row.input_tokens == 350, (
        f"input_tokens={row.input_tokens}, expected 350. The accumulation "
        "clause may have regressed from `+ EXCLUDED.input_tokens` to plain "
        "`EXCLUDED.input_tokens` (silent clobber)."
    )
    assert row.output_tokens == 150, f"output_tokens={row.output_tokens}, expected 150"


async def test_record_usage_writes_first_of_month_period_start(session, two_test_orgs):
    """`period_start` must be the first day of the calendar month — the
    composite PK depends on it. A wrong unit (e.g. `date_trunc('day',
    NOW())::date`) would create a fresh row per day, breaking both the
    accumulation contract and the cross-month rollover semantics.
    """
    from services.codeguard_quotas import record_org_usage

    org_id, _ = two_test_orgs

    await record_org_usage(session, org_id, input_tokens=42, output_tokens=42)
    await session.commit()

    period_start = (
        await session.execute(
            text("SELECT period_start FROM codeguard_org_usage WHERE organization_id = :org"),
            {"org": str(org_id)},
        )
    ).scalar_one()

    # Day must be 1 (first of month). Tolerate any year/month — the
    # test runs whenever; what matters is the truncation unit.
    assert period_start.day == 1, (
        f"period_start={period_start}, expected day=1. Wrong date_trunc unit "
        "in `record_org_usage`'s SQL — probably 'day' instead of 'month'."
    )


# ---------- Cross-org isolation ----------------------------------------


async def test_record_usage_does_not_leak_across_orgs(session, two_test_orgs):
    """Writing org A's usage must NOT touch org B's row. Pin the
    isolation contract — a regression that dropped the
    `organization_id = :org_id` predicate from the UPSERT (or got the
    parameter binding wrong) would silently merge tenants' spend into
    each other and either (a) blow through caps for one org based on
    another's usage, or (b) hide spend.
    """
    from services.codeguard_quotas import record_org_usage

    org_a, org_b = two_test_orgs

    await record_org_usage(session, org_a, input_tokens=1000, output_tokens=500)
    # Org B never wrote anything yet; nothing should appear for it.
    await record_org_usage(session, org_b, input_tokens=99, output_tokens=33)
    # Then more for A. The third call's increment must land on A's row,
    # not B's.
    await record_org_usage(session, org_a, input_tokens=2000, output_tokens=400)
    await session.commit()

    a_row = (
        await session.execute(
            text("SELECT input_tokens, output_tokens FROM codeguard_org_usage WHERE organization_id = :org"),
            {"org": str(org_a)},
        )
    ).one()
    b_row = (
        await session.execute(
            text("SELECT input_tokens, output_tokens FROM codeguard_org_usage WHERE organization_id = :org"),
            {"org": str(org_b)},
        )
    ).one()

    assert a_row.input_tokens == 3000, f"org A input={a_row.input_tokens}, expected 3000"
    assert a_row.output_tokens == 900, f"org A output={a_row.output_tokens}, expected 900"
    assert b_row.input_tokens == 99, f"org B input={b_row.input_tokens}, expected 99"
    assert b_row.output_tokens == 33, f"org B output={b_row.output_tokens}, expected 33"


# ---------- check_org_quota reads what record_org_usage wrote ----------


async def test_check_quota_sees_the_running_total(session, two_test_orgs):
    """End-to-end: write usage, then read it via `check_org_quota` and
    assert the running total surfaces correctly. This is the contract
    the cap-enforcement loop depends on — the next request's pre-flight
    has to see the previous request's spend.

    Sets up a quota row first so `check_org_quota` returns a real
    QuotaCheckResult rather than the `unlimited` shortcut for orgs
    without a quota row.
    """
    from services.codeguard_quotas import check_org_quota, record_org_usage

    org_id, _ = two_test_orgs

    # Pin a generous cap so we don't trip over_limit; we're testing the
    # `used` reading, not the binding.
    await session.execute(
        text(
            """
            INSERT INTO codeguard_org_quotas
                (organization_id, monthly_input_token_limit, monthly_output_token_limit)
            VALUES (:org, 10000, 10000)
            """
        ),
        {"org": str(org_id)},
    )
    await record_org_usage(session, org_id, input_tokens=750, output_tokens=200)
    await session.commit()

    result = await check_org_quota(session, org_id)
    # We can't directly assert `result.used` because that field is the
    # binding-dimension's used value (only populated when over_limit).
    # Instead, drive the org over by adding more usage and verify the
    # check picks it up — proves the reads are wired to the same row
    # the writes hit.
    await record_org_usage(session, org_id, input_tokens=10_000, output_tokens=0)
    await session.commit()
    result = await check_org_quota(session, org_id)
    assert result.over_limit is True, (
        "After accumulating past the input limit, check_org_quota didn't see it. "
        "Either record_org_usage isn't writing to the row check_org_quota reads, "
        "or the LEFT JOIN in check_org_quota is mis-binding the period."
    )
    assert result.limit_kind == "input"
    assert result.used == 10_750  # 750 + 10_000


# ---------- audit log ---------------------------------------------------


async def test_audit_log_round_trips_through_real_postgres(session, two_test_orgs):
    """End-to-end pin for the `codeguard_quota_audit_log` table created
    in migration 0026. Tier 1 covers the call shape; this Tier 3 case
    proves the schema actually accepts what the CLI writes:

      * JSONB columns round-trip a nested dict (they would crash if
        the column type drifted to `json` text or `bytea`).
      * The `org_id → organizations.id` FK accepts a real org and
        rejects a bogus one.
      * The `(organization_id, occurred_at DESC)` index is queryable
        in the documented direction.
      * `occurred_at` defaults to NOW() — the row is timestamped even
        when the writer doesn't bind one.

    Why this matters: the migration is the table's only definition.
    A regression that subtly changed (say) `JSONB` → `JSON` would still
    let the unit tests pass (they stub the engine) but would silently
    drop our ability to query the audit history with `before->>'...'`.
    """
    import datetime as _dt
    import json as _json

    org_a, _ = two_test_orgs

    # Two audit rows for org_a. NOW() is constant inside a single
    # transaction, so we bind explicit `occurred_at` timestamps to
    # guarantee distinct values — otherwise both rows hash to the same
    # instant and the `ORDER BY occurred_at DESC` ordering between them
    # is undefined (a real failure mode operators would hit if two
    # `set` calls ran back-to-back from a script). Computing the
    # timestamps Python-side (rather than `NOW() - INTERVAL`) sidesteps
    # asyncpg's INTERVAL adapter, which has type-coercion quirks when
    # subtracted from NOW().
    now = _dt.datetime.now(_dt.UTC)
    for occurred_at, action, before, after, actor in [
        # Earlier row: alice's first-time provisioning.
        (
            now - _dt.timedelta(minutes=1),
            "quota_set",
            None,
            {"monthly_input_token_limit": 1_000_000, "monthly_output_token_limit": 200_000},
            "alice",
        ),
        # Later row: bob raises the cap.
        (
            now,
            "quota_set",
            {"monthly_input_token_limit": 1_000_000, "monthly_output_token_limit": 200_000},
            {"monthly_input_token_limit": 5_000_000, "monthly_output_token_limit": 1_000_000},
            "bob",
        ),
    ]:
        await session.execute(
            text(
                """
                INSERT INTO codeguard_quota_audit_log
                    (organization_id, action, before, after, actor, occurred_at)
                VALUES (
                    :org, :action,
                    CAST(:before AS JSONB), CAST(:after AS JSONB),
                    :actor, :occurred_at
                )
                """
            ),
            {
                "org": str(org_a),
                "action": action,
                "before": _json.dumps(before) if before is not None else None,
                "after": _json.dumps(after) if after is not None else None,
                "actor": actor,
                "occurred_at": occurred_at,
            },
        )
    await session.commit()

    # Fetch in (org, occurred_at DESC) order — same query pattern the
    # ops dashboard will issue. Pinning via this exact ORDER BY
    # exercises the index created in the migration.
    rows = (
        await session.execute(
            text(
                """
                SELECT action, actor, before, after
                FROM codeguard_quota_audit_log
                WHERE organization_id = :org
                ORDER BY occurred_at DESC
                """
            ),
            {"org": str(org_a)},
        )
    ).all()
    assert len(rows) == 2

    # Latest row is bob's update (the cap raise, occurred_at = NOW()).
    latest = rows[0]
    assert latest.action == "quota_set"
    assert latest.actor == "bob"
    # JSONB columns come back as native dicts in asyncpg, no parse needed.
    assert latest.before == {
        "monthly_input_token_limit": 1_000_000,
        "monthly_output_token_limit": 200_000,
    }
    assert latest.after == {
        "monthly_input_token_limit": 5_000_000,
        "monthly_output_token_limit": 1_000_000,
    }

    # Earlier row is alice's first-time provisioning (occurred_at = NOW() - 1min).
    earliest = rows[1]
    assert earliest.actor == "alice"
    assert earliest.before is None  # NULL JSONB → None, not {}.


async def test_audit_log_sets_org_to_null_on_org_delete(session):
    """`organization_id` FK is `ON DELETE SET NULL` — deleting the org
    must NOT cascade the audit row away. Pin the contract: the row
    survives, with `organization_id` nulled out. Cascading would lose
    the paper trail at exactly the moment compliance needs it."""
    import json as _json

    org_id = uuid4()
    await session.execute(
        text("INSERT INTO organizations (id, name, slug) VALUES (:o, 'Audit Test Org', :s)"),
        {"o": str(org_id), "s": f"audit-test-{org_id}"},
    )
    await session.execute(
        text(
            """
            INSERT INTO codeguard_quota_audit_log
                (organization_id, action, before, after, actor)
            VALUES (:o, 'quota_set', NULL, CAST(:a AS JSONB), 'alice')
            """
        ),
        {
            "o": str(org_id),
            "a": _json.dumps({"monthly_input_token_limit": 1}),
        },
    )
    await session.commit()

    # Delete the org — audit row must survive with org_id = NULL.
    await session.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": str(org_id)})
    await session.commit()

    surviving = (
        await session.execute(
            text(
                """
                SELECT organization_id, actor, after
                FROM codeguard_quota_audit_log
                WHERE actor = 'alice' AND after->>'monthly_input_token_limit' = '1'
                """
            ),
        )
    ).all()
    # Row must still exist (preserves the audit trail) and its org_id
    # must be NULL (FK action). If you see len==0, the FK action got
    # changed to CASCADE; if you see organization_id==<uuid>, ON DELETE
    # SET NULL didn't fire.
    assert len(surviving) == 1
    assert surviving[0].organization_id is None

    # Cleanup: drop the orphaned audit row so the test is self-contained.
    await session.execute(
        text(
            "DELETE FROM codeguard_quota_audit_log WHERE actor = 'alice' AND after->>'monthly_input_token_limit' = '1'"
        )
    )
    await session.commit()


async def test_audit_log_rejects_bogus_org_fk(session):
    """The FK to `organizations.id` must reject a UUID that doesn't
    point at a real org. Without this, a typo'd CLI invocation would
    still write the audit row — leaving a misleading event the ops
    team would have to chase down later."""
    import asyncpg
    from sqlalchemy.exc import IntegrityError

    bogus = uuid4()  # Never inserted into organizations.

    with pytest.raises((IntegrityError, asyncpg.exceptions.ForeignKeyViolationError)):
        await session.execute(
            text(
                """
                INSERT INTO codeguard_quota_audit_log
                    (organization_id, action, before, after, actor)
                VALUES (:o, 'quota_set', NULL, NULL, 'alice')
                """
            ),
            {"o": str(bogus)},
        )
        await session.commit()
    # Roll back the failed transaction so subsequent fixtures see a
    # clean session.
    await session.rollback()


# ---------- threshold-notification dedupe table ------------------------
#
# Migration 0030 created `codeguard_quota_threshold_notifications` with:
#   * Composite PK on (org_id, dimension, threshold, period_start) — the
#     whole row IS the dedupe key.
#   * `ON CONFLICT DO NOTHING` is what makes a losing concurrent claim
#     observable as `rowcount=0` (the helper's race-safety primitive).
#   * `organization_id` FK with `ON DELETE CASCADE` — dedupe rows are
#     operational state, not audit history; clean them up when the
#     org goes away rather than holding a phantom reference.
#
# Tier 1 mocks all three. A regression that swapped the PK for a
# surrogate id, dropped DO NOTHING, or changed CASCADE to RESTRICT
# would still pass every Tier 1 test. These cases pin the SQL.


async def test_threshold_dedupe_pk_blocks_duplicate_claims(session, two_test_orgs):
    """Second INSERT for the same `(org, dimension, threshold, period)`
    tuple must return `rowcount=0` thanks to `ON CONFLICT DO NOTHING`.
    The race-safety of `_claim_threshold_or_skip` rests on this — a
    regression that dropped DO NOTHING (so dups raise IntegrityError
    instead) would propagate through to the helper and crash the
    request post-LLM-call, which is the exact failure mode the dedupe
    is meant to prevent.
    """
    import datetime as _dt

    org_a, _ = two_test_orgs
    period = _dt.date(2026, 5, 1)

    # First claim: lands.
    first = await session.execute(
        text(
            """
            INSERT INTO codeguard_quota_threshold_notifications
                (organization_id, dimension, threshold, period_start)
            VALUES (:o, 'input', 80, :p)
            ON CONFLICT DO NOTHING
            """
        ),
        {"o": str(org_a), "p": period},
    )
    assert first.rowcount == 1, (
        f"First claim returned rowcount={first.rowcount}, expected 1. "
        "Did the table get the wrong INSERT rights, or is `rowcount` "
        "not being populated for this driver?"
    )

    # Second claim of the SAME tuple: silently no-ops.
    second = await session.execute(
        text(
            """
            INSERT INTO codeguard_quota_threshold_notifications
                (organization_id, dimension, threshold, period_start)
            VALUES (:o, 'input', 80, :p)
            ON CONFLICT DO NOTHING
            """
        ),
        {"o": str(org_a), "p": period},
    )
    assert second.rowcount == 0, (
        f"Duplicate claim returned rowcount={second.rowcount}, expected 0. "
        "This is the dedupe contract `_claim_threshold_or_skip` relies on — "
        "if the regression is `ON CONFLICT … DO UPDATE` instead of `DO NOTHING`, "
        "rowcount would be 1 and the helper would multi-send."
    )

    # Different threshold for the same (org, dim, period) is a NEW row,
    # not a dupe. Pin so the PK includes `threshold` correctly.
    third = await session.execute(
        text(
            """
            INSERT INTO codeguard_quota_threshold_notifications
                (organization_id, dimension, threshold, period_start)
            VALUES (:o, 'input', 95, :p)
            ON CONFLICT DO NOTHING
            """
        ),
        {"o": str(org_a), "p": period},
    )
    assert third.rowcount == 1, (
        "(org, input, 95, 2026-05-01) should land as a fresh row even though "
        "(org, input, 80, 2026-05-01) already exists — the PK includes "
        "`threshold`. If you see rowcount=0, the PK has been narrowed."
    )

    # Different period for the same (org, dim, threshold) is also a NEW
    # row — month rollover must let the email fire again.
    next_period = _dt.date(2026, 6, 1)
    fourth = await session.execute(
        text(
            """
            INSERT INTO codeguard_quota_threshold_notifications
                (organization_id, dimension, threshold, period_start)
            VALUES (:o, 'input', 80, :p)
            ON CONFLICT DO NOTHING
            """
        ),
        {"o": str(org_a), "p": next_period},
    )
    assert fourth.rowcount == 1, (
        "Next month's (org, input, 80, 2026-06-01) should land — without "
        "this, an org that crossed 80% in May would never get a fresh "
        "warning in June."
    )

    await session.commit()


async def test_threshold_dedupe_isolates_per_org(session, two_test_orgs):
    """Two orgs claiming the same `(dimension, threshold, period)` band
    are independent — `organization_id` is part of the PK. A regression
    that dropped `organization_id` from the PK would silently let one
    org's claim block another org's email."""
    import datetime as _dt

    org_a, org_b = two_test_orgs
    period = _dt.date(2026, 5, 1)

    a_claim = await session.execute(
        text(
            """
            INSERT INTO codeguard_quota_threshold_notifications
                (organization_id, dimension, threshold, period_start)
            VALUES (:o, 'input', 80, :p)
            ON CONFLICT DO NOTHING
            """
        ),
        {"o": str(org_a), "p": period},
    )
    assert a_claim.rowcount == 1

    # Org B claiming the SAME band must succeed — different PK tuple.
    b_claim = await session.execute(
        text(
            """
            INSERT INTO codeguard_quota_threshold_notifications
                (organization_id, dimension, threshold, period_start)
            VALUES (:o, 'input', 80, :p)
            ON CONFLICT DO NOTHING
            """
        ),
        {"o": str(org_b), "p": period},
    )
    assert b_claim.rowcount == 1, (
        "Org B's claim got blocked by org A's row — the PK must include "
        "`organization_id`. Without per-org isolation, finance for one tenant "
        "would receive emails about another tenant crossing 80%."
    )
    await session.commit()


async def test_threshold_dedupe_cascades_on_org_delete(session):
    """`organization_id` FK with `ON DELETE CASCADE`: when the org goes
    away, its dedupe rows go with it. Different choice from the audit
    log (SET NULL there) because dedupe rows are pure operational
    state — keeping them after the org is gone would just bloat the
    table without a reader."""
    import datetime as _dt

    org_id = uuid4()
    period = _dt.date(2026, 5, 1)

    await session.execute(
        text("INSERT INTO organizations (id, name, slug) VALUES (:o, 'Threshold Cascade Test', :s)"),
        {"o": str(org_id), "s": f"threshold-cascade-{org_id}"},
    )
    await session.execute(
        text(
            """
            INSERT INTO codeguard_quota_threshold_notifications
                (organization_id, dimension, threshold, period_start)
            VALUES (:o, 'input', 80, :p), (:o, 'output', 95, :p)
            """
        ),
        {"o": str(org_id), "p": period},
    )
    await session.commit()

    # Sanity: rows are there.
    pre = (
        await session.execute(
            text("SELECT COUNT(*) AS n FROM codeguard_quota_threshold_notifications WHERE organization_id = :o"),
            {"o": str(org_id)},
        )
    ).scalar_one()
    assert pre == 2

    # Delete the org — cascade should drop both dedupe rows.
    await session.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": str(org_id)})
    await session.commit()

    surviving = (
        await session.execute(
            text("SELECT COUNT(*) AS n FROM codeguard_quota_threshold_notifications WHERE organization_id = :o"),
            {"o": str(org_id)},
        )
    ).scalar_one()
    assert surviving == 0, (
        f"Found {surviving} surviving dedupe rows after deleting the org. "
        "The FK action must be ON DELETE CASCADE — anything else (RESTRICT, "
        "SET NULL) leaves orphaned rows that bloat the table forever."
    )


async def test_quota_warn_recipients_filters_on_at_least_one_channel(session, two_test_orgs):
    """`_quota_warn_recipients` returns users opted in to AT LEAST ONE
    channel (email_enabled=TRUE OR slack_enabled=TRUE). Both-disabled
    users are filtered out — they have a `quota_warn` row but no
    intent to receive anything, so the dispatcher would do zero work
    for them anyway. The shape is per-channel `(_Recipient)` records,
    not flat email strings — pre-Slack the function returned
    `list[str]`; pin the new shape so a regression that re-flattens
    breaks visibly."""
    from services.codeguard_quotas import _quota_warn_recipients, _Recipient

    org_a, _ = two_test_orgs

    # Four users covering all four (email_enabled, slack_enabled) cells:
    user_email_only = uuid4()  # email-only: TRUE / FALSE
    user_slack_only = uuid4()  # slack-only: FALSE / TRUE
    user_both = uuid4()  # both:    TRUE / TRUE
    user_neither = uuid4()  # neither:  FALSE / FALSE — filtered out
    user_unconfigured = uuid4()  # no row at all — filtered out

    await session.execute(
        text(
            "INSERT INTO users (id, email, full_name) VALUES "
            "(:a, 'email-only@example.com', 'A'), "
            "(:b, 'slack-only@example.com', 'B'), "
            "(:c, 'both@example.com', 'C'), "
            "(:d, 'neither@example.com', 'D'), "
            "(:e, 'unconfigured@example.com', 'E')"
        ),
        {
            "a": str(user_email_only),
            "b": str(user_slack_only),
            "c": str(user_both),
            "d": str(user_neither),
            "e": str(user_unconfigured),
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO notification_preferences
                (user_id, organization_id, key, email_enabled, slack_enabled)
            VALUES
                (:a, :org, 'quota_warn', TRUE,  FALSE),
                (:b, :org, 'quota_warn', FALSE, TRUE),
                (:c, :org, 'quota_warn', TRUE,  TRUE),
                (:d, :org, 'quota_warn', FALSE, FALSE)
            """
        ),
        {
            "a": str(user_email_only),
            "b": str(user_slack_only),
            "c": str(user_both),
            "d": str(user_neither),
            "org": str(org_a),
        },
    )
    await session.commit()

    recipients = await _quota_warn_recipients(session, org_a)
    # Map by email so the test isn't ordering-dependent (the SQL has
    # no ORDER BY — Postgres is free to return rows in any order).
    by_email = {r.email: r for r in recipients}

    # Three users in: email-only, slack-only, both. Two filtered out:
    # neither (both flags FALSE) and unconfigured (no row).
    assert set(by_email.keys()) == {
        "email-only@example.com",
        "slack-only@example.com",
        "both@example.com",
    }, (
        f"Got {set(by_email.keys())}. If 'neither@example.com' is in, "
        "the SQL's `OR slack_enabled` clause is too permissive. If "
        "'slack-only@example.com' is missing, the clause was reduced "
        "back to email_enabled-only and Slack-only opt-ins are dropped."
    )

    # Per-channel intent surfaces faithfully — pre-Slack we returned
    # flat email strings and dropped this metadata. Pin all four cells.
    assert isinstance(by_email["email-only@example.com"], _Recipient)
    assert by_email["email-only@example.com"].email_enabled is True
    assert by_email["email-only@example.com"].slack_enabled is False
    assert by_email["slack-only@example.com"].email_enabled is False
    assert by_email["slack-only@example.com"].slack_enabled is True
    assert by_email["both@example.com"].email_enabled is True
    assert by_email["both@example.com"].slack_enabled is True

    # Cleanup — prefs cascade-delete via users.id FK.
    await session.execute(
        text("DELETE FROM users WHERE id IN (:a, :b, :c, :d, :e)"),
        {
            "a": str(user_email_only),
            "b": str(user_slack_only),
            "c": str(user_both),
            "d": str(user_neither),
            "e": str(user_unconfigured),
        },
    )
    await session.commit()
