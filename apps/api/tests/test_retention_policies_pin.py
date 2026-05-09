"""Pin every entry of `services.retention.RETENTION_POLICIES`.

Why this exists: the daily prune cron iterates this tuple and
deletes rows from each table older than `default_days`. A typo
here has compounding bad effects:

  * **Compliance shrinkage**: `audit_events: 30` instead of `365` →
    the legally-required 1-year audit log silently shortens to a
    month. Auditor asks "show me 60-day-old audit row X"; it
    doesn't exist.
  * **Premature webhook deletion**: dropping the
    `extra_where="status IN ('delivered', 'failed')"` predicate on
    `webhook_deliveries` → pending retry rows get pruned too,
    silently losing customer integrations' events.
  * **Archive miss**: flipping `archive=True` to `False` on
    `audit_events` → a customer dispute about an old change-order
    approval can't be recovered from S3 because no copy was made
    before the prune.

Each of these is invisible at runtime — the cron's logs just say
"pruned N rows from <table>" and look healthy. The legal /
recovery surface degrades silently until someone tries to query
the now-missing rows.

If you intentionally change a policy, update `EXPECTED` below in
the same PR + verify ops has reviewed the new TTL against the
matching compliance / archive requirement.
"""

from __future__ import annotations

from services.retention import RETENTION_POLICIES, RetentionPolicy

# Source of truth, pinned 2026-05-04. Each entry mirrors the
# matching `RetentionPolicy(...)` in `services.retention` exactly,
# in the same order. Order matters because the cron iterates the
# tuple in declaration order; heaviest-table-first is the
# documented strategy and a reorder shifts cap-hit dynamics.
EXPECTED: tuple[RetentionPolicy, ...] = (
    RetentionPolicy(
        table="audit_events",
        age_column="created_at",
        default_days=365,  # 1y compliance window — DO NOT shorten without legal sign-off.
        extra_where=None,
        archive=True,
    ),
    RetentionPolicy(
        table="webhook_deliveries",
        age_column="created_at",
        default_days=30,
        # Critical: keeps `pending` retry rows alive past the TTL.
        # Dropping this predicate silently prunes in-flight events.
        extra_where="status IN ('delivered', 'failed')",
        archive=False,
    ),
    RetentionPolicy(
        table="search_queries",
        age_column="created_at",
        default_days=90,
        extra_where=None,
        archive=False,
    ),
    RetentionPolicy(
        table="import_jobs",
        age_column="created_at",
        default_days=30,
        extra_where=None,
        archive=True,
    ),
    RetentionPolicy(
        table="api_key_calls",
        age_column="minute_bucket",
        default_days=30,
        extra_where=None,
        archive=False,
    ),
    RetentionPolicy(
        table="codeguard_quota_audit_log",
        age_column="occurred_at",
        default_days=730,  # 2y compliance window.
        extra_where=None,
        archive=True,
    ),
    # Cron-job invocation telemetry (`/admin/crons` dashboard).
    # Pure observability — no archive value beyond the dashboard
    # window. 30d covers a weekly cron's trend (~4-5 samples) without
    # unbounded growth from per-minute crons like webhook_drain.
    RetentionPolicy(
        table="cron_runs",
        age_column="started_at",
        default_days=30,
        extra_where=None,
        archive=False,
    ),
)


def test_retention_policies_match_expected_tuple_exactly():
    """Hard equality on the tuple (order-sensitive). Order matters
    because the cron iterates declaration order and the per-run row
    cap (`_MAX_PRUNE_ROWS_PER_RUN`) means a heavy table at the front
    can starve later ones — heaviest-first is the documented strategy.

    `RetentionPolicy` is a `frozen=True` dataclass, so equality is
    field-by-field — a typo on any single field surfaces here with
    a precise diff message.
    """
    assert RETENTION_POLICIES == EXPECTED, (
        "RETENTION_POLICIES drifted from the pinned tuple. The diff above "
        "names exactly which policy changed. If this is intentional:\n"
        "  1. Update EXPECTED in the same PR.\n"
        "  2. Confirm the new default_days against the matching compliance "
        "  requirement (audit_events legal floor is 365d; codeguard quota "
        "  audit is 730d).\n"
        "  3. If `archive` flipped, verify the S3 export side-channel is "
        "  still wired (or intentionally disabled)."
    )


def test_retention_policy_count():
    """Belt-and-suspenders for the count itself. Catches a duplicate
    (same `table` listed twice) the equality test above would also
    fail on, but with a less-targeted diff."""
    assert len(RETENTION_POLICIES) == len(EXPECTED), (
        f"RETENTION_POLICIES has {len(RETENTION_POLICIES)} entries; EXPECTED has {len(EXPECTED)}."
    )


def test_retention_policy_tables_are_unique():
    """No two policies should target the same table. A duplicate
    (e.g. `audit_events` listed with two different TTLs) would
    cause the cron to prune twice per run with the SECOND policy
    winning — silently overriding the first."""
    tables = [p.table for p in RETENTION_POLICIES]
    assert len(tables) == len(set(tables)), (
        f"RETENTION_POLICIES has duplicate `table` entries: {sorted(t for t in tables if tables.count(t) > 1)}"
    )


def test_compliance_critical_tables_have_archive_enabled():
    """The compliance-relevant tables (`audit_events`,
    `codeguard_quota_audit_log`) MUST set `archive=True` so deletes
    are recoverable from S3. A flip to False silently loses recovery
    capability — a customer dispute about an old action becomes
    unrecoverable.

    Other tables (search_queries, api_key_calls) are pure telemetry;
    archive=False is the right call there. This test is narrow on
    purpose: it doesn't enforce archive on every table, just the
    two with documented compliance bearings.
    """
    by_table = {p.table: p for p in RETENTION_POLICIES}
    for compliance_table in ("audit_events", "codeguard_quota_audit_log"):
        policy = by_table.get(compliance_table)
        assert policy is not None, (
            f"compliance-critical table {compliance_table!r} is no longer in "
            "RETENTION_POLICIES. If the table was renamed, update EXPECTED + "
            "this test together."
        )
        assert policy.archive is True, (
            f"compliance-critical table {compliance_table!r} has archive=False. "
            "Deletes for this table MUST be recoverable from S3."
        )


def test_audit_events_minimum_compliance_window():
    """`audit_events.default_days` is the legal-floor TTL. Pin a
    minimum here so a "let's reduce ops cost by tightening retention"
    refactor can't accidentally drop below the compliance threshold
    without an explicit test update.

    The actual floor (365d) is also pinned in `EXPECTED` above; this
    test surfaces the same regression with a different framing — a
    failure here points the reviewer at the compliance angle
    specifically, rather than just "the tuple drifted."
    """
    audit_policy = next((p for p in RETENTION_POLICIES if p.table == "audit_events"), None)
    assert audit_policy is not None
    # 365 (1y) is the documented floor. Any value below would need
    # explicit legal sign-off and an EXPECTED update + this floor
    # update in the same PR.
    assert audit_policy.default_days >= 365, (
        f"audit_events.default_days dropped to {audit_policy.default_days}d — "
        "below the 365d compliance floor. Legal sign-off required before "
        "shortening this window."
    )


def test_webhook_deliveries_extra_where_keeps_pending_alive():
    """`webhook_deliveries` MUST carry the
    `status IN ('delivered', 'failed')` predicate — without it,
    the prune cron would delete `pending` rows that the dispatcher
    intends to retry, silently losing customer integrations' events.

    A regression here is the canonical "looks fine but breaks
    everything" failure mode: the cron logs "pruned N rows" and
    nobody notices the events that vanished mid-retry."""
    webhook_policy = next(
        (p for p in RETENTION_POLICIES if p.table == "webhook_deliveries"),
        None,
    )
    assert webhook_policy is not None
    assert webhook_policy.extra_where is not None, (
        "webhook_deliveries policy has no extra_where predicate. The "
        "default-on prune would delete `pending` retry rows mid-flight, "
        "silently losing customer events."
    )
    # Pin the exact predicate string. Two equivalent spellings (e.g.
    # `status = 'delivered' OR status = 'failed'`) would be
    # functionally equivalent but break the SQL-cache plan stability
    # the cron relies on.
    assert webhook_policy.extra_where == "status IN ('delivered', 'failed')"
