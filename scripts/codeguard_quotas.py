#!/usr/bin/env python3
"""Manage per-org CODEGUARD token quotas from the command line.

Five subcommands cover the full ops loop:

    # Set or update an org's monthly cap. Either limit can be omitted
    # (NULL = unlimited on that dimension); both omitted = unlimited.
    python scripts/codeguard_quotas.py set <org-uuid> \\
      --input-limit 5000000 --output-limit 1000000

    # Show an org's quota row + current-month usage with percent-of-cap.
    python scripts/codeguard_quotas.py get <org-uuid>

    # List orgs by usage; --over-pct filters to "at risk" entries.
    python scripts/codeguard_quotas.py list --over-pct 80

    # Zero an org's current-month usage row. Use for billing disputes,
    # contract changes, or cleaning up after a load test.
    python scripts/codeguard_quotas.py reset <org-uuid> --confirm

    # Read the audit log for one org. Surfaces what `set` / `reset`
    # did, by whom, and when — closes the loop on the audit table.
    python scripts/codeguard_quotas.py audit <org-uuid> \\
      --since 2026-04-01 --action quota_set

The script imports `services.codeguard_quotas` so the SQL stays in
exactly one place — drift between the CLI's INSERT and the route
layer's pre-flight check would silently let an org bypass its cap. The
`set` subcommand uses an UPSERT (matching the route layer's pattern)
so re-running with new numbers updates the existing row.

Connection comes from `DATABASE_URL` (asyncpg form) — same env var
that the API server uses, so an ops engineer running this script
locally hits the same DB their pod will read.

Output is human-readable by default; `--json` flips every subcommand
to a machine-readable shape that scripts can pipe into `jq` or feed
to a dashboard.

Mutations (`set`, `reset`) write a row to `codeguard_quota_audit_log`
in the same transaction as the operation. Drift is impossible: either
both land or neither does. The audit row captures `before` / `after`
JSONB snapshots and the actor (OS username, or whatever `--actor`
overrides to). Reads (`get`, `list`) don't touch the audit table.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from collections.abc import Sequence
from typing import Any
from uuid import UUID

# When invoked from the repo root, `apps/api` and `apps/ml` aren't on
# sys.path — but `services.codeguard_quotas` lives at `apps/api/services/
# codeguard_quotas.py`. Add `apps/api` so the import resolves the same
# way it does inside the API container.
_APP_API = os.path.join(os.path.dirname(__file__), "..", "apps", "api")
if os.path.isdir(_APP_API) and _APP_API not in sys.path:
    sys.path.insert(0, os.path.abspath(_APP_API))


# ---------- DB helpers ---------------------------------------------------


async def _engine_factory():
    """Build an async engine from `DATABASE_URL`. Errors with a clear
    message if the var isn't set — easier to triage than a SQLAlchemy
    connection-refused ten frames deep."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit(
            "DATABASE_URL not set — point it at the codeguard DB "
            "(e.g. postgresql+asyncpg://aec:aec@localhost:5438/aec)."
        )
    engine = create_async_engine(url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


def _resolve_actor(explicit: str | None) -> str:
    """Pick the audit `actor` string. Explicit `--actor` wins (service
    accounts, CI runners that share a Unix user); otherwise the OS
    username. Falls back to `"unknown"` only when even `getpass` can't
    resolve a name — never silently writes an empty string, which would
    defeat the point of the audit."""
    if explicit:
        return explicit
    try:
        name = getpass.getuser()
    except Exception:
        # `getuser()` can raise on systems where neither $USER, $LOGNAME,
        # nor pwd is available (rare, but happens in some sandboxed CI
        # images). Better to record "unknown" than crash the operation.
        name = ""
    return name or "unknown"


# `before` / `after` are JSONB; each helper here renders the relevant
# row to a plain dict (None when no row existed) so the audit log
# captures the exact state on either side of the mutation. Kept separate
# so a future "set memo" or "set rate-limit" mutation can build its own
# snapshot without overloading these.


def _quota_row_to_snapshot(row: Any) -> dict[str, Any] | None:
    """Render a `codeguard_org_quotas` row to a JSON-friendly dict, or
    None if the row doesn't exist yet (a `set` against a fresh org)."""
    if row is None:
        return None
    return {
        "monthly_input_token_limit": row.in_lim,
        "monthly_output_token_limit": row.out_lim,
    }


def _usage_row_to_snapshot(row: Any) -> dict[str, Any] | None:
    """Render a `codeguard_org_usage` row to a JSON-friendly dict. None
    when the org has no usage row for the current period — a reset of
    a no-op state still gets logged so we have evidence the operator
    intended to act.
    """
    if row is None:
        return None
    return {
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
    }


async def _write_audit_row(
    session: Any,
    *,
    org_id: UUID,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    actor: str,
) -> None:
    """Insert a row into `codeguard_quota_audit_log`. Caller is
    responsible for committing — the audit insert MUST live in the
    same transaction as the underlying mutation, otherwise a crash
    between the two leaves the log either ahead of or behind reality.

    JSON serialization happens here (with `default=str` for any odd
    types like `Decimal` or `date`) so callers don't have to think
    about it. The columns are JSONB; psycopg/asyncpg accept either a
    native dict or a JSON string, but we go through `json.dumps` to
    guarantee identical encoding regardless of driver.
    """
    from sqlalchemy import text

    await session.execute(
        text(
            """
            INSERT INTO codeguard_quota_audit_log
                (organization_id, action, before, after, actor)
            VALUES
                (:org, :action, CAST(:before AS JSONB), CAST(:after AS JSONB), :actor)
            """
        ),
        {
            "org": str(org_id),
            "action": action,
            "before": json.dumps(before, default=str) if before is not None else None,
            "after": json.dumps(after, default=str) if after is not None else None,
            "actor": actor,
        },
    )


# ---------- `set` --------------------------------------------------------


async def cmd_set(
    org_id: UUID,
    *,
    input_limit: int | None,
    output_limit: int | None,
    actor: str | None = None,
) -> dict[str, Any]:
    """UPSERT the quota row for `org_id`. Mirrors the API server's
    pattern: existing row's other fields untouched, only the limit
    columns set from this call. NULL on either dimension = unlimited
    on that dimension only.

    Records a `quota_set` audit row in the same transaction. The
    `before` snapshot captures the pre-existing quota row (or NULL if
    this is the first `set` for the org); `after` captures the new
    values. A single commit covers both — drift impossible.

    After commit, fires `check_and_notify_thresholds`. Reasoning: the
    in-app `record_org_usage` path is the normal trigger, but if ops
    *lowers* an org's cap (1M → 500k while they're sitting at 600k),
    the org is instantly past 100% and nothing in the usage path runs
    until the org's next LLM call — which could be hours. Firing the
    check from `set` closes that window. The dedupe table protects
    against double-firing if the org happens to also hit the threshold
    via usage in the same period — same `(org, dim, threshold, period)`
    PK, no matter which trigger landed first.
    """
    from sqlalchemy import text

    actor_name = _resolve_actor(actor)
    engine, factory = await _engine_factory()
    notify_summaries: list[dict[str, Any]] = []
    try:
        async with factory() as session:
            # Read current state BEFORE the upsert so the audit `before`
            # snapshot is honest. SELECT FOR UPDATE so a concurrent
            # `set` against the same org can't squeeze in between this
            # read and the UPSERT — without the lock the audit log
            # could record the wrong predecessor.
            before_row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          monthly_input_token_limit  AS in_lim,
                          monthly_output_token_limit AS out_lim
                        FROM codeguard_org_quotas
                        WHERE organization_id = :org
                        FOR UPDATE
                        """
                    ),
                    {"org": str(org_id)},
                )
            ).first()

            await session.execute(
                text(
                    """
                    INSERT INTO codeguard_org_quotas
                        (organization_id,
                         monthly_input_token_limit,
                         monthly_output_token_limit,
                         created_at, updated_at)
                    VALUES (:org, :in_lim, :out_lim, NOW(), NOW())
                    ON CONFLICT (organization_id) DO UPDATE SET
                      monthly_input_token_limit  = EXCLUDED.monthly_input_token_limit,
                      monthly_output_token_limit = EXCLUDED.monthly_output_token_limit,
                      updated_at                 = NOW()
                    """
                ),
                {
                    "org": str(org_id),
                    "in_lim": input_limit,
                    "out_lim": output_limit,
                },
            )

            await _write_audit_row(
                session,
                org_id=org_id,
                action="quota_set",
                before=_quota_row_to_snapshot(before_row),
                after={
                    "monthly_input_token_limit": input_limit,
                    "monthly_output_token_limit": output_limit,
                },
                actor=actor_name,
            )

            await session.commit()

            # Threshold check runs AFTER commit so the dedupe row +
            # notification email reference the post-set state, not the
            # in-flight UPSERT. Wrapped in its own try/except — the
            # cap is already updated and the audit row is already
            # committed; an SMTP outage or a notification-prefs
            # query failure must NOT roll those back. Same posture as
            # the route-layer hook in `_with_usage_recording`.
            try:
                from services import codeguard_quotas as _q

                notify_summaries = await _q.check_and_notify_thresholds(session, org_id)
            except Exception as exc:
                # Surface to stderr so the operator sees something went
                # wrong with notifications — but don't propagate, the
                # set itself succeeded and that's the load-bearing part.
                sys.stderr.write(
                    f"warning: check_and_notify_thresholds failed for org={org_id}: {exc}\n"
                )
                notify_summaries = []
    finally:
        await engine.dispose()
    return {
        "org_id": str(org_id),
        "monthly_input_token_limit": input_limit,
        "monthly_output_token_limit": output_limit,
        "actor": actor_name,
        "notifications": notify_summaries,
    }


# ---------- `reset` ------------------------------------------------------


async def cmd_reset(
    org_id: UUID,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """Zero the current-period usage row for `org_id`. The quota row
    (the *limits*) is untouched — `reset` only affects accumulated
    usage. Useful for billing disputes ("we were charged for traffic
    that never reached us"), contract changes mid-month, or cleaning
    up after a load test that polluted real numbers.

    If no usage row exists for the current period, the operation is
    a no-op on the data side but STILL writes an audit row (with
    `before=null`) — that way an operator running `reset` against an
    org with no usage gets evidence they tried, which matters when
    debugging "why didn't this work" later.
    """
    from sqlalchemy import text

    actor_name = _resolve_actor(actor)
    engine, factory = await _engine_factory()
    try:
        async with factory() as session:
            # Capture the pre-reset row for the audit `before` snapshot.
            # FOR UPDATE so we hold the row lock through the UPDATE.
            before_row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          input_tokens,
                          output_tokens,
                          period_start
                        FROM codeguard_org_usage
                        WHERE organization_id = :org
                          AND period_start = date_trunc('month', NOW())::date
                        FOR UPDATE
                        """
                    ),
                    {"org": str(org_id)},
                )
            ).first()

            # The actual reset: zero both counters for the current
            # period. We do NOT delete the row — the next `record_usage`
            # call would just recreate it via UPSERT, but keeping it
            # preserves any other columns (e.g. `updated_at`) so we
            # can answer "when was this last touched."
            await session.execute(
                text(
                    """
                    UPDATE codeguard_org_usage
                       SET input_tokens  = 0,
                           output_tokens = 0,
                           updated_at    = NOW()
                     WHERE organization_id = :org
                       AND period_start = date_trunc('month', NOW())::date
                    """
                ),
                {"org": str(org_id)},
            )

            after_snapshot: dict[str, Any] | None
            if before_row is None:
                # No row existed → nothing to reset. Audit `after` is
                # also NULL; the audit row alone records the attempt.
                after_snapshot = None
            else:
                after_snapshot = {
                    "period_start": (
                        before_row.period_start.isoformat() if before_row.period_start else None
                    ),
                    "input_tokens": 0,
                    "output_tokens": 0,
                }

            await _write_audit_row(
                session,
                org_id=org_id,
                action="quota_reset",
                before=_usage_row_to_snapshot(before_row),
                after=after_snapshot,
                actor=actor_name,
            )

            await session.commit()
    finally:
        await engine.dispose()

    return {
        "org_id": str(org_id),
        "before": _usage_row_to_snapshot(before_row),
        "after": after_snapshot,
        "actor": actor_name,
    }


# ---------- `get` --------------------------------------------------------


async def cmd_get(org_id: UUID) -> dict[str, Any]:
    """Read the quota row + current-period usage for one org. Returns a
    dict with `quota`, `usage`, and `percent_of_cap` (per dimension).
    Percent is None when the corresponding limit is NULL (unlimited).
    """
    from sqlalchemy import text

    engine, factory = await _engine_factory()
    try:
        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          q.monthly_input_token_limit  AS in_lim,
                          q.monthly_output_token_limit AS out_lim,
                          COALESCE(u.input_tokens, 0)  AS in_used,
                          COALESCE(u.output_tokens, 0) AS out_used,
                          u.period_start
                        FROM codeguard_org_quotas q
                        LEFT JOIN codeguard_org_usage u
                          ON u.organization_id = q.organization_id
                          AND u.period_start = date_trunc('month', NOW())::date
                        WHERE q.organization_id = :org
                        """
                    ),
                    {"org": str(org_id)},
                )
            ).first()
    finally:
        await engine.dispose()

    if row is None:
        return {
            "org_id": str(org_id),
            "quota": None,
            "usage": None,
            "note": "No quota row — this org is unlimited.",
        }

    in_pct = round(100.0 * row.in_used / row.in_lim, 1) if row.in_lim and row.in_lim > 0 else None
    out_pct = (
        round(100.0 * row.out_used / row.out_lim, 1) if row.out_lim and row.out_lim > 0 else None
    )
    return {
        "org_id": str(org_id),
        "quota": {
            "monthly_input_token_limit": row.in_lim,
            "monthly_output_token_limit": row.out_lim,
        },
        "usage": {
            "period_start": row.period_start.isoformat() if row.period_start else None,
            "input_tokens": row.in_used,
            "output_tokens": row.out_used,
        },
        "percent_of_cap": {"input": in_pct, "output": out_pct},
    }


# ---------- `list` -------------------------------------------------------


async def cmd_list(*, over_pct: float | None) -> list[dict[str, Any]]:
    """Return all orgs with a quota row, sorted by max(input%, output%).
    `over_pct` filters to entries whose binding dimension is at or above
    that percent — the "at risk" cohort an ops dashboard cares about.
    """
    from sqlalchemy import text

    engine, factory = await _engine_factory()
    try:
        async with factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                          q.organization_id            AS org_id,
                          q.monthly_input_token_limit  AS in_lim,
                          q.monthly_output_token_limit AS out_lim,
                          COALESCE(u.input_tokens, 0)  AS in_used,
                          COALESCE(u.output_tokens, 0) AS out_used
                        FROM codeguard_org_quotas q
                        LEFT JOIN codeguard_org_usage u
                          ON u.organization_id = q.organization_id
                          AND u.period_start = date_trunc('month', NOW())::date
                        """
                    )
                )
            ).all()
    finally:
        await engine.dispose()

    out: list[dict[str, Any]] = []
    for r in rows:
        in_pct = 100.0 * r.in_used / r.in_lim if r.in_lim and r.in_lim > 0 else None
        out_pct_val = 100.0 * r.out_used / r.out_lim if r.out_lim and r.out_lim > 0 else None
        # Binding percent = the higher of the two configured dimensions.
        # If both are unlimited, binding is None (org can never bind).
        candidates = [p for p in (in_pct, out_pct_val) if p is not None]
        binding_pct = max(candidates) if candidates else None
        if over_pct is not None and (binding_pct is None or binding_pct < over_pct):
            continue
        out.append(
            {
                "org_id": str(r.org_id),
                "input_used": r.in_used,
                "input_limit": r.in_lim,
                "input_pct": round(in_pct, 1) if in_pct is not None else None,
                "output_used": r.out_used,
                "output_limit": r.out_lim,
                "output_pct": (round(out_pct_val, 1) if out_pct_val is not None else None),
                "binding_pct": (round(binding_pct, 1) if binding_pct is not None else None),
            }
        )
    # Sort by binding_pct descending; orgs with no binding (both
    # unlimited) sort to the end so the "at risk" cohort is at the top.
    out.sort(key=lambda r: (r["binding_pct"] is None, -(r["binding_pct"] or 0.0)))
    return out


# ---------- `audit` ------------------------------------------------------


async def cmd_audit(
    org_id: UUID,
    *,
    limit: int = 50,
    since: str | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    """Read the `codeguard_quota_audit_log` for one org, most-recent first.

    Closes the loop on the audit table the `set`/`reset` mutations
    write to — without this subcommand, compliance asking "who raised
    this org's cap last week" still requires opening psql and writing
    JSONB queries by hand. The CLI knows which columns matter; ops
    shouldn't have to.

    Filters compose with AND:
      * `limit`  — hard cap on rows returned (defaults to 50, the
                   typical "show me the recent activity" window).
      * `since`  — ISO date (YYYY-MM-DD); only rows at or after this
                   day are included. Omit for "everything we have."
      * `action` — restrict to one action string (e.g. "quota_set").

    Returns a list of dicts with `occurred_at`, `actor`, `action`, and
    the raw `before` / `after` JSONB snapshots. The formatter renders a
    one-line summary; `--json` exposes the full snapshots for richer
    downstream tooling.
    """
    from sqlalchemy import text

    # Build the WHERE clause incrementally so we don't bind unused
    # parameters. Doing this with f-string interpolation of column
    # names is safe (we're not concatenating user input into SQL),
    # and it keeps the active filters visible in the assembled query.
    where_clauses: list[str] = ["organization_id = :org"]
    params: dict[str, Any] = {"org": str(org_id), "limit": int(limit)}
    if since is not None:
        where_clauses.append("occurred_at >= CAST(:since AS DATE)")
        params["since"] = since
    if action is not None:
        where_clauses.append("action = :action")
        params["action"] = action

    sql = f"""
        SELECT id, occurred_at, actor, action, before, after
        FROM codeguard_quota_audit_log
        WHERE {" AND ".join(where_clauses)}
        ORDER BY occurred_at DESC, id DESC
        LIMIT :limit
    """
    # ORDER BY also includes `id DESC` so two rows with the same
    # `occurred_at` (NOW() inside one transaction) sort deterministically.
    # Without that tiebreaker, the same rows can appear in different
    # order across runs, which trips up integration tests and confuses
    # operators reading scrollback.

    engine, factory = await _engine_factory()
    try:
        async with factory() as session:
            rows = (await session.execute(text(sql), params)).all()
    finally:
        await engine.dispose()

    return [
        {
            "id": str(r.id),
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "actor": r.actor,
            "action": r.action,
            "before": r.before,
            "after": r.after,
        }
        for r in rows
    ]


# ---------- Output formatting -------------------------------------------


def format_get(data: dict[str, Any]) -> str:
    if data.get("quota") is None:
        return f"{data['org_id']}\n  {data['note']}\n"
    q = data["quota"]
    u = data["usage"]
    pct = data["percent_of_cap"]
    lines = [
        f"org_id:        {data['org_id']}",
        f"period_start:  {u['period_start']}",
        "  input:   "
        + f"{u['input_tokens']:>10,} / "
        + (
            f"{q['monthly_input_token_limit']:>10,}"
            if q["monthly_input_token_limit"] is not None
            else "  unlimited"
        )
        + (f"  ({pct['input']:.1f}%)" if pct["input"] is not None else ""),
        "  output:  "
        + f"{u['output_tokens']:>10,} / "
        + (
            f"{q['monthly_output_token_limit']:>10,}"
            if q["monthly_output_token_limit"] is not None
            else "  unlimited"
        )
        + (f"  ({pct['output']:.1f}%)" if pct["output"] is not None else ""),
    ]
    return "\n".join(lines) + "\n"


def format_audit(rows: list[dict[str, Any]]) -> str:
    """Render audit rows as a compact table:

        2026-05-01T12:00Z  alice            quota_set     input 1M→5M, output 200k→1M
        2026-04-15T09:30Z  bob              quota_reset   input 850k→0, output 120k→0

    The summary column compresses the JSONB snapshots into the diff
    operators care about ("what changed"). For complex / future actions
    where the diff doesn't compress cleanly, the formatter falls back
    to a "see --json for details" hint rather than truncating fields
    silently.
    """
    if not rows:
        return "No audit entries match the filter.\n"
    # Fixed columns: time (20), actor (16), action (14), summary (rest).
    # Widths chosen so an actor like "oncall-engineer" (15) fits without
    # wrapping and the action column accommodates `quota_reset` (12).
    header = f"{'occurred_at':<20}  {'actor':<16}  {'action':<14}  summary"
    lines = [header, "-" * (len(header) + 40)]
    for r in rows:
        lines.append(
            f"{(r.get('occurred_at') or '')[:19]:<20}  "
            f"{(r.get('actor') or '')[:16]:<16}  "
            f"{(r.get('action') or '')[:14]:<14}  "
            f"{_summarize_audit_diff(r)}"
        )
    return "\n".join(lines) + "\n"


def _summarize_audit_diff(row: dict[str, Any]) -> str:
    """Compress an audit row's before/after into a one-line diff."""
    before = row.get("before")
    after = row.get("after")
    action = row.get("action") or ""

    # quota_set: surface the limit columns (the only fields that can
    # change). "1M→5M" reads better than "1000000 → 5000000" in a
    # terminal — use the same suffix shorthand `format_get` uses.
    if action == "quota_set":
        b_in = (before or {}).get("monthly_input_token_limit")
        b_out = (before or {}).get("monthly_output_token_limit")
        a_in = (after or {}).get("monthly_input_token_limit")
        a_out = (after or {}).get("monthly_output_token_limit")
        return (
            f"input {_short_num(b_in)}→{_short_num(a_in)}, "
            f"output {_short_num(b_out)}→{_short_num(a_out)}"
        )

    # quota_reset: before/after are usage rows; show the totals zeroed.
    if action == "quota_reset":
        if before is None:
            return "(no usage row — nothing to zero)"
        return (
            f"input {_short_num(before.get('input_tokens'))}→0, "
            f"output {_short_num(before.get('output_tokens'))}→0"
        )

    # Unknown action — don't lie about the diff shape. Hint at --json.
    return "(see --json for details)"


def _short_num(n: Any) -> str:
    """Format a token count compactly: 1234567 → '1.2M'. Used by the
    audit table where horizontal space matters more than precision."""
    if n is None:
        return "∞"  # NULL limit = unlimited
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def format_set(data: dict[str, Any]) -> str:
    """Human-readable summary of a `set` result. Echoes the bound
    limits + the actor so the operator can confirm what the audit log
    just recorded — the same numbers they'll see if they `get` the
    org afterwards."""
    in_lim = data.get("monthly_input_token_limit")
    out_lim = data.get("monthly_output_token_limit")
    return (
        f"org_id: {data['org_id']}\n"
        f"  monthly_input_token_limit:  "
        f"{f'{in_lim:,}' if in_lim is not None else 'unlimited'}\n"
        f"  monthly_output_token_limit: "
        f"{f'{out_lim:,}' if out_lim is not None else 'unlimited'}\n"
        f"  actor: {data.get('actor', 'unknown')}\n"
    )


def format_reset(data: dict[str, Any]) -> str:
    """Human-readable summary of a `reset` result. Surfaces what was
    zeroed (the `before` totals) so the operator can sanity-check the
    blast radius of the command they just ran."""
    org_id = data["org_id"]
    before = data.get("before")
    actor = data.get("actor", "unknown")
    if before is None:
        return (
            f"org_id: {org_id}\n"
            f"  No current-period usage row — nothing to reset. "
            f"Audit row recorded.\n"
            f"  actor: {actor}\n"
        )
    return (
        f"org_id: {org_id}\n"
        f"  period_start:  {before.get('period_start')}\n"
        f"  zeroed:        input={before.get('input_tokens'):,} → 0, "
        f"output={before.get('output_tokens'):,} → 0\n"
        f"  actor: {actor}\n"
    )


def format_list(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No orgs match the filter.\n"
    header = (
        f"{'org_id':<38}  {'in_used':>10}  {'in%':>6}  {'out_used':>10}  {'out%':>6}  {'bind%':>6}"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        in_pct = f"{r['input_pct']:.1f}" if r["input_pct"] is not None else "-"
        out_pct = f"{r['output_pct']:.1f}" if r["output_pct"] is not None else "-"
        bind_pct = f"{r['binding_pct']:.1f}" if r["binding_pct"] is not None else "-"
        lines.append(
            f"{r['org_id']:<38}  {r['input_used']:>10,}  {in_pct:>6}  "
            f"{r['output_used']:>10,}  {out_pct:>6}  {bind_pct:>6}"
        )
    return "\n".join(lines) + "\n"


# ---------- `routes` (operator visibility into ROUTE_WEIGHTS) -----------


def cmd_routes() -> list[dict[str, Any]]:
    """Return the current per-route weight policy as a list of dicts.

    Read-only, doesn't touch the DB — `ROUTE_WEIGHTS` is a Python
    constant in `services/codeguard_quota_attribution.py`. The CLI
    reads it through the import boundary so a future refactor that
    relocates the dict (e.g. into a config file) doesn't require
    re-syncing this script — the import name is the contract.

    Why a CLI subcommand for a constant: ops engineers regularly
    need to answer "what's the /scan multiplier in production?" or
    "did we ship the long-context premium yet?" without reading
    Python. A `quotas routes` invocation gives them the same answer
    `grep ROUTE_WEIGHTS` would, but as part of the same tool they're
    already using for `quotas set` / `quotas list` — one less context
    switch.
    """
    # Lazy import — the script doesn't otherwise need the apps/api
    # path at import time. The sys.path setup at module top makes
    # the apps/api package importable.
    from services.codeguard_quota_attribution import ROUTE_WEIGHTS

    # Sort by weight DESC, ties broken by route_key for stability.
    # The "heaviest first" order matches the operator question
    # ("which route is most expensive?") and the format_routes table
    # below renders top-down.
    items = [{"route_key": k, "weight": float(v)} for k, v in ROUTE_WEIGHTS.items()]
    items.sort(key=lambda r: (-r["weight"], r["route_key"]))
    return items


def format_routes(rows: list[dict[str, Any]]) -> str:
    """Pretty-print the route weights table. Two columns: route_key
    and the multiplier. Pinned formatting so an ops grep against
    output ("scan.*5") stays stable across refactors.
    """
    if not rows:
        return "No routes registered.\n"
    header = f"{'route_key':<24}  {'weight':>7}"
    lines = [header, "-" * len(header)]
    for r in rows:
        # `:.2f` so weight=1.0 reads as "1.00" — distinguishes the
        # default from a deliberate 1.0 (some future fractional weight
        # like 1.5 would render unambiguously).
        lines.append(f"{r['route_key']:<24}  {r['weight']:>7.2f}")
    return "\n".join(lines) + "\n"


# ---------- `usage-by-route` (per-user × per-route drill-down) ----------


async def cmd_usage_by_route(org_id: UUID, *, limit: int = 10) -> dict[str, Any]:
    """Read `codeguard_user_usage_by_route` for one org's CURRENT
    period — the same data `/quota/top-users?breakdown=true` exposes
    over HTTP, but available to ops without a JWT or curl.

    Returns a dict with `org_id`, `period_start`, and a sorted
    `users` list — each user carries their aggregate totals plus a
    `routes` array. Mirrors the route's response shape so an
    operator who's seen the dashboard sees the same numbers here.

    Why a CLI: the breakdown is the answer to "who's spending and
    on what?" — a high-frequency ops question that needs a one-liner,
    not "open the web app, log in, navigate, expand each row." The
    HTTP route stays as the authoritative read; the CLI is convenience.

    `limit` clamps 1..50 (matches the route's clamp). Operators
    occasionally want top-50 not top-10 when triaging a heavy month.
    """
    from sqlalchemy import text as sql_text

    bounded_limit = max(1, min(int(limit), 50))

    engine, factory = await _engine_factory()
    try:
        async with factory() as session:
            # Top users by aggregate spend — same query shape as
            # `/quota/top-users` (no breakdown). The LEFT JOIN on
            # `users` preserves attribution for deleted users.
            user_rows = (
                await session.execute(
                    sql_text(
                        """
                        SELECT
                            u.user_id,
                            COALESCE(usr.email, '')        AS email,
                            u.input_tokens                 AS input_tokens,
                            u.output_tokens                AS output_tokens,
                            (u.input_tokens + u.output_tokens) AS total_tokens
                        FROM codeguard_user_usage u
                        LEFT JOIN users usr ON usr.id = u.user_id
                        WHERE u.organization_id = :org_id
                          AND u.period_start    = date_trunc('month', NOW())::date
                        ORDER BY total_tokens DESC, u.user_id
                        LIMIT :limit
                        """
                    ),
                    {"org_id": str(org_id), "limit": bounded_limit},
                )
            ).all()

            breakdown_by_user: dict[str, list[dict[str, Any]]] = {}
            if user_rows:
                # Pull every (user, route) row for the top-N users in a
                # single query — same N+1-avoidance the HTTP route does.
                user_ids = [str(r.user_id) for r in user_rows]
                br_rows = (
                    await session.execute(
                        sql_text(
                            """
                            SELECT user_id, route_key, input_tokens, output_tokens
                            FROM codeguard_user_usage_by_route
                            WHERE organization_id = :org_id
                              AND period_start    = date_trunc('month', NOW())::date
                              AND user_id = ANY(CAST(:user_ids AS UUID[]))
                            ORDER BY user_id, (input_tokens + output_tokens) DESC
                            """
                        ),
                        {"org_id": str(org_id), "user_ids": user_ids},
                    )
                ).all()
                for br in br_rows:
                    breakdown_by_user.setdefault(str(br.user_id), []).append(
                        {
                            "route_key": br.route_key,
                            "input_tokens": int(br.input_tokens),
                            "output_tokens": int(br.output_tokens),
                            "total_tokens": int(br.input_tokens) + int(br.output_tokens),
                        }
                    )

            users = [
                {
                    "user_id": str(r.user_id),
                    "email": r.email or "",
                    "input_tokens": int(r.input_tokens),
                    "output_tokens": int(r.output_tokens),
                    "total_tokens": int(r.total_tokens),
                    "routes": breakdown_by_user.get(str(r.user_id), []),
                }
                for r in user_rows
            ]
    finally:
        await engine.dispose()

    return {
        "org_id": str(org_id),
        "limit": bounded_limit,
        "users": users,
    }


def format_usage_by_route(data: dict[str, Any]) -> str:
    """Pretty-print the usage-by-route drill-down. Outer rows are
    users; each user's `routes` render as an indented sub-block.

    Format choices:
      * Outer table is fixed-width so `quotas usage-by-route ... |
        grep alice` returns a useful line.
      * Sub-block prefixes routes with `  /` so a grep on `/scan`
        works across the whole output regardless of which user owns
        the row.
      * vi-VN dot-grouping for readability of large numbers.
    """
    users = data.get("users") or []
    if not users:
        return "No usage rows for this org in the current period.\n"
    lines: list[str] = []
    header = f"{'user':<40}  {'in':>12}  {'out':>12}  {'total':>12}"
    lines.append(header)
    lines.append("-" * len(header))
    for u in users:
        # Empty email = user deleted between spend and read; render
        # with an 8-char user_id stub so the row stays legible.
        email = u["email"] or f"(deleted:{u['user_id'][:8]})"
        lines.append(
            f"{email[:40]:<40}  "
            f"{_format_vi_int(u['input_tokens']):>12}  "
            f"{_format_vi_int(u['output_tokens']):>12}  "
            f"{_format_vi_int(u['total_tokens']):>12}"
        )
        for r in u.get("routes") or []:
            # `  /` indented prefix for greppability — `grep '/scan'`
            # finds every scan row across all users in one pass.
            lines.append(
                f"  /{r['route_key']:<37}  "
                f"{_format_vi_int(r['input_tokens']):>12}  "
                f"{_format_vi_int(r['output_tokens']):>12}  "
                f"{_format_vi_int(r['total_tokens']):>12}"
            )
    return "\n".join(lines) + "\n"


def _format_vi_int(n: int | None) -> str:
    """vi-VN dot-grouped integer formatting. Pulled out as a private
    helper so both `format_usage_by_route` and any future ops command
    use the same formatting — keeps grep patterns stable across
    subcommands."""
    if n is None:
        return "—"
    return f"{n:,}".replace(",", ".")


# ---------- main --------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage per-org CODEGUARD token quotas.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a formatted table.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    set_p = sub.add_parser("set", help="Upsert an org's monthly quota row.")
    set_p.add_argument("org_id", type=UUID, help="Organization UUID.")
    set_p.add_argument(
        "--input-limit",
        type=int,
        default=None,
        help="Monthly input-token cap. Omit for unlimited.",
    )
    set_p.add_argument(
        "--output-limit",
        type=int,
        default=None,
        help="Monthly output-token cap. Omit for unlimited.",
    )
    # Actor override only applies to mutating subcommands. Reads
    # (`get`, `list`) don't write the audit log, so the flag would be
    # confusing noise there.
    set_p.add_argument(
        "--actor",
        type=str,
        default=None,
        help="Override the audit `actor` (default: $USER). Useful when "
        "running under a shared service account.",
    )

    get_p = sub.add_parser("get", help="Show one org's quota + current usage.")
    get_p.add_argument("org_id", type=UUID, help="Organization UUID.")

    list_p = sub.add_parser("list", help="List all orgs with quotas, sorted by usage.")
    list_p.add_argument(
        "--over-pct",
        type=float,
        default=None,
        help="Only include orgs whose binding dimension is >= this percent.",
    )

    reset_p = sub.add_parser(
        "reset",
        help="Zero an org's current-month usage row (does not change limits).",
    )
    reset_p.add_argument("org_id", type=UUID, help="Organization UUID.")
    # `--confirm` is a guard rail: `reset` clobbers data the API server
    # is actively writing to. Make the operator say so explicitly so a
    # fat-fingered command in shell history can't zero a customer's
    # spend by accident.
    reset_p.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Acknowledges that this clears the running usage row.",
    )
    reset_p.add_argument(
        "--actor",
        type=str,
        default=None,
        help="Override the audit `actor` (default: $USER).",
    )

    audit_p = sub.add_parser(
        "audit",
        help="Show audit log entries for an org's quota mutations.",
    )
    audit_p.add_argument("org_id", type=UUID, help="Organization UUID.")
    audit_p.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max rows to return (default 50). The table is append-only "
        "and unbounded; the limit keeps an `audit` against an old org "
        "from spilling thousands of rows into the terminal.",
    )
    audit_p.add_argument(
        "--since",
        type=str,
        default=None,
        help="ISO date (YYYY-MM-DD); show only entries at or after that "
        'day. Example: --since 2026-04-01 for "this month and later."',
    )
    audit_p.add_argument(
        "--action",
        type=str,
        default=None,
        choices=("quota_set", "quota_reset"),
        help="Filter to one action type. Useful when chasing down a "
        "specific category of change (e.g. only the `reset` events).",
    )

    # `routes` — read-only operator inspection of ROUTE_WEIGHTS. No
    # args; just `python scripts/codeguard_quotas.py routes` to dump
    # the table. JSON via the global `--json` flag.
    sub.add_parser(
        "routes",
        help="Print the per-route weight policy (ROUTE_WEIGHTS) as a "
        "table. Read-only — doesn't touch the DB.",
    )

    # `usage-by-route` — drill into one org's per-user × per-route
    # spend for the current period. Same data the
    # `/quota/top-users?breakdown=true` route returns, but available
    # to ops without HTTP / JWT. Hyphen in name (matches `quota-history`
    # convention) → translated to `usage_by_route` arg attribute by
    # argparse.
    ubr_p = sub.add_parser(
        "usage-by-route",
        help="Drill into one org's per-user × per-route spend for the "
        "current period (top consumers + their per-route breakdown).",
    )
    ubr_p.add_argument("org_id", type=UUID, help="Organization UUID.")
    ubr_p.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max users to include (server-clamped 1..50). Default 10 "
        "matches the dashboard's top-N panel; bump to 50 when triaging "
        "a heavy month.",
    )

    args = parser.parse_args(argv)

    if args.cmd == "set":
        result = asyncio.run(
            cmd_set(
                args.org_id,
                input_limit=args.input_limit,
                output_limit=args.output_limit,
                actor=args.actor,
            )
        )
        if args.json:
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(format_set(result))
            sys.stdout.write("OK\n")
    elif args.cmd == "get":
        result = asyncio.run(cmd_get(args.org_id))
        if args.json:
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(format_get(result))
    elif args.cmd == "list":
        rows = asyncio.run(cmd_list(over_pct=args.over_pct))
        if args.json:
            json.dump(rows, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(format_list(rows))
    elif args.cmd == "audit":
        rows = asyncio.run(
            cmd_audit(
                args.org_id,
                limit=args.limit,
                since=args.since,
                action=args.action,
            )
        )
        if args.json:
            json.dump(rows, sys.stdout, indent=2, default=str)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(format_audit(rows))
    elif args.cmd == "reset":
        if not args.confirm:
            # Refuse without `--confirm` rather than silently zeroing
            # the row. Exit 2 (argparse's "usage error" exit code) so
            # CI scripts can distinguish "user error" from "DB error".
            sys.stderr.write(
                "reset: refusing without --confirm. This zeros the org's "
                "current-month usage row; pass --confirm to proceed.\n"
            )
            return 2
        result = asyncio.run(cmd_reset(args.org_id, actor=args.actor))
        if args.json:
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(format_reset(result))
    elif args.cmd == "routes":
        # No async — just reads the in-process Python constant.
        rows = cmd_routes()
        if args.json:
            json.dump(rows, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(format_routes(rows))
    elif args.cmd == "usage-by-route":
        result = asyncio.run(cmd_usage_by_route(args.org_id, limit=args.limit))
        if args.json:
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(format_usage_by_route(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
