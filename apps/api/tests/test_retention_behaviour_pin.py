"""Behavioural pin for `services.retention` — complementary to the
existing data-shape pin in `test_retention_policies_pin.py`.

The data pin covers WHAT'S in the registry (which tables, what TTL,
archive flag, age column). THIS file covers HOW the helper functions
behave around the registry — the source-level invariants that, if
they regress, silently break the prune semantics even with the
registry intact:

  * **`_MAX_PRUNE_ROWS_PER_RUN == 10_000`** — calibrated to keep the
    DELETE's tuple-lock under a few seconds. A regression to 1M
    would let one cron block concurrent inserts on `audit_events`
    long enough that customer-facing writes start timing out.

  * **`RetentionPolicy` frozen-dataclass posture** — runtime
    mutation of `archive` would silently break the recovery promise
    on compliance-bearing tables.

  * **`RETENTION_POLICIES` is a tuple** — a list lets import-time
    side effects mutate the registry without redeploy review.

  * **`prune_table` uses CTE + ctid join** — the idiomatic capped
    DELETE pattern. A naive `DELETE … LIMIT N` doesn't exist in PG;
    a SELECT-then-DELETE without the CTE races concurrent inserts.

  * **`run_retention_cron` per-table try/except + rollback** —
    a transient failure on one table MUST NOT skip the rest. A
    regression that let an exception propagate would leave the
    whole registry unpruned for the day.

  * **Archive-fails-but-DELETE-stands** — S3 is a recovery aid,
    not a correctness invariant. The DELETE is durable even if
    the archive write fails (logged loudly). A regression that
    rolled back on archive failure would let an S3 outage block
    every prune run platform-wide.

  * **`policy_ttl_days` env-override semantics** — Customer Success
    bumps audit retention for compliance-conscious tenants by
    setting one env var. A regression that ignored the override or
    treated 0 as valid would either lose the customisation hook OR
    let `AEC_RETENTION_AUDIT_EVENTS_DAYS=0` silently wipe the
    audit log on the next cron run.

This file is read-only — exercises pure helpers + source-grep on
the cron entrypoint. Survives reverts.
"""

from __future__ import annotations

import inspect
from dataclasses import is_dataclass

# ---------- Cap constant ----------


def test_max_prune_rows_per_run_pinned_at_10k():
    """SECURITY/AVAILABILITY pin. 10k caps lock duration to a few
    seconds at most. A regression to 1M would block concurrent
    writes on `audit_events` for tens of seconds — customer-facing
    timeouts during the nightly prune window.

    A regression downward (1k, 100) doesn't break correctness but
    means a backed-up tenant takes longer to catch up; the 10k
    number is calibrated against historical prune rates.
    """
    from services.retention import _MAX_PRUNE_ROWS_PER_RUN

    assert _MAX_PRUNE_ROWS_PER_RUN == 10_000, (
        f"_MAX_PRUNE_ROWS_PER_RUN drifted to {_MAX_PRUNE_ROWS_PER_RUN}. "
        "Lifting risks lock contention; lowering slows catch-up. "
        "Tuned against historical prune rates — re-tune deliberately."
    )


# ---------- Frozen-dataclass posture ----------


def test_retention_policy_is_frozen_dataclass():
    """SECURITY pin. `RetentionPolicy` is `@dataclass(frozen=True)`.
    A regular mutable dataclass would let runtime code (or a buggy
    admin endpoint) flip `archive=True → False` on `audit_events`,
    silently breaking the recovery promise on the next prune run.
    """
    from services.retention import RETENTION_POLICIES, RetentionPolicy

    assert is_dataclass(RetentionPolicy)

    for policy in RETENTION_POLICIES:
        # Frozen dataclasses raise FrozenInstanceError on attempted
        # mutation. We catch the broad `Exception` because the exact
        # class is implementation-detail of the dataclasses module.
        try:
            policy.archive = not policy.archive  # type: ignore[misc]
            mutated = True
        except Exception:
            mutated = False
        assert not mutated, (
            f"RetentionPolicy(table={policy.table}) is mutable. "
            "The frozen=True posture is what makes the registry "
            "tamper-resistant at runtime."
        )


def test_retention_policies_is_tuple_not_list():
    """`RETENTION_POLICIES` is a tuple. A list lets import-time side
    effects `.append()` the registry — silent registry expansion
    without going through deploy review."""
    from services.retention import RETENTION_POLICIES

    assert isinstance(RETENTION_POLICIES, tuple), (
        f"RETENTION_POLICIES is {type(RETENTION_POLICIES).__name__}; "
        "want tuple. A list lets import-time mutation past review."
    )


# ---------- prune_table source invariants ----------


def test_prune_table_uses_cte_with_ctid_pattern():
    """The DELETE uses `WITH victims AS (... LIMIT :cap) DELETE …
    USING victims … WHERE t.ctid = v.ctid`. This is the idiomatic
    "delete capped batch with RETURNING" pattern in Postgres — a
    naive `DELETE … LIMIT N` doesn't exist, and a separate SELECT-
    then-DELETE races concurrent inserts.

    Pin via source-grep so a "simplification" refactor that drops
    the CTE has to be deliberate.
    """
    import services.retention as mod

    src = inspect.getsource(mod.prune_table)
    assert "WITH victims AS" in src, (
        "prune_table no longer uses the CTE-based DELETE pattern. "
        "Without the CTE, a SELECT-then-DELETE race lets new rows "
        "slip in between the two statements."
    )
    assert "ctid" in src, (
        "prune_table no longer uses ctid joins. The ctid trick is "
        "what lets the CTE select rows-to-delete without reading "
        "every column (cheap), then DELETE by physical row ID."
    )
    assert "LIMIT :cap" in src, (
        "prune_table no longer caps the DELETE batch. Without the "
        "cap, a backed-up cron could DELETE millions of rows in "
        "one transaction."
    )


def test_prune_table_uses_returning_for_archive():
    """The DELETE returns deleted rows so the archive helper has
    them in-memory without a separate SELECT. A regression that
    SELECTed before DELETE would race concurrent inserts AND
    double the DB round trips."""
    import services.retention as mod

    src = inspect.getsource(mod.prune_table)
    assert "RETURNING" in src.upper(), (
        "prune_table's DELETE no longer uses RETURNING. Without it, "
        "the archive code would need a separate SELECT before the "
        "DELETE — race-prone and 2x round trips."
    )


def test_prune_table_archive_failure_does_not_rollback_delete():
    """The archive call is wrapped in its own try/except so an S3
    failure logs loudly but the DELETE still commits. Pin the
    documented invariant via the source-comment grep — a regression
    that rolled back would let an S3 outage block every prune run."""
    import services.retention as mod

    src = inspect.getsource(mod.prune_table)
    # The docstring/comment pattern that tells reviewers the
    # invariant is intentional. If a refactor drops both the
    # try/except AND the comment, the test fires.
    assert "rows still deleted" in src, (
        "prune_table no longer documents the 'archive fails, DELETE "
        "stands' invariant. Reviewers reading the warning need to "
        "know the rows ARE gone (replay from S3 if a prior archive "
        "succeeded)."
    )
    assert "logger.error" in src, (
        "prune_table's archive-failure path no longer logs at ERROR. Silent archive misses defeat the recovery aid."
    )


# ---------- run_retention_cron source invariants ----------


def test_run_retention_cron_per_table_try_except():
    """Per-table errors MUST be caught + logged so a failure on one
    table doesn't skip the others. A regression that let an
    exception propagate would leave the whole registry unpruned
    for the day (silent — no exception reaches the arq error log
    because the swallow is at the wrapping layer)."""
    import services.retention as mod

    src = inspect.getsource(mod.run_retention_cron)
    assert "except Exception" in src, (
        "run_retention_cron no longer has the per-table try/except. "
        "A transient failure on one table would skip every later "
        "table in the registry."
    )


def test_run_retention_cron_rollback_on_per_table_failure():
    """A failed transaction left dangling would block the next
    iteration's begin(). Pin the rollback so the cron is robust to
    transient per-table failures.
    """
    import services.retention as mod

    src = inspect.getsource(mod.run_retention_cron)
    assert "rollback" in src.lower(), (
        "run_retention_cron no longer rolls back on per-table "
        "failure. The next iteration's begin() would block on the "
        "open transaction."
    )


def test_run_retention_cron_commits_per_table():
    """Per-table commit means a partial run is durable: if
    `audit_events` succeeds and `search_queries` fails, we still
    keep the audit_events DELETE. A regression to a single
    end-of-cron commit would lose the entire run on the first
    failure."""
    import services.retention as mod

    src = inspect.getsource(mod.run_retention_cron)
    assert "session.commit()" in src, (
        "run_retention_cron no longer commits per-table. A single "
        "end-of-cron commit would discard every successful prune "
        "if any later table fails."
    )


# ---------- policy_ttl_days behaviour ----------


def test_policy_ttl_days_returns_default_when_no_override(monkeypatch):
    """Happy path — when `AEC_RETENTION_<TABLE>_DAYS` env override
    is unset, returns `policy.default_days`."""
    from core.config import get_settings
    from services.retention import RETENTION_POLICIES, policy_ttl_days

    settings = get_settings()
    audit_policy = next(p for p in RETENTION_POLICIES if p.table == "audit_events")
    # Ensure no override is set.
    monkeypatch.setattr(settings, "retention_audit_events_days", None, raising=False)

    assert policy_ttl_days(audit_policy) == 365


def test_policy_ttl_days_uses_override_when_present(monkeypatch):
    """`Settings.retention_<table>_days` env-override path. CS uses
    this to bump audit retention for compliance-conscious tenants."""
    from core.config import get_settings
    from services.retention import RETENTION_POLICIES, policy_ttl_days

    settings = get_settings()
    audit_policy = next(p for p in RETENTION_POLICIES if p.table == "audit_events")
    monkeypatch.setattr(settings, "retention_audit_events_days", 730, raising=False)

    assert policy_ttl_days(audit_policy) == 730, (
        "policy_ttl_days did not honour the env override. The CS "
        "customisation hook is broken; tenants requesting longer "
        "retention silently get the default."
    )


def test_policy_ttl_days_rejects_zero_or_negative_override(monkeypatch):
    """SECURITY pin. An override of `0` would mean "delete everything
    immediately" on the next prune run — including this morning's
    fresh audit rows. A regression that accepted `0` (or negative)
    would let `AEC_RETENTION_AUDIT_EVENTS_DAYS=0` silently wipe
    the audit log.

    The `if isinstance(override, int) and override > 0` guard is
    the defence; pin its behaviour.
    """
    from core.config import get_settings
    from services.retention import RETENTION_POLICIES, policy_ttl_days

    settings = get_settings()
    audit_policy = next(p for p in RETENTION_POLICIES if p.table == "audit_events")

    for bad_value in (0, -1, "180", 180.5, []):
        monkeypatch.setattr(settings, "retention_audit_events_days", bad_value, raising=False)
        result = policy_ttl_days(audit_policy)
        assert result == 365, (
            f"policy_ttl_days(retention_audit_events_days={bad_value!r}) "
            f"returned {result} instead of falling back to default 365. "
            "An override of 0 or negative would WIPE the audit log on "
            "the next prune run."
        )
