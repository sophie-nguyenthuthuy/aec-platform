#!/usr/bin/env python3
"""Manage per-org CODEGUARD token quotas from the command line.

Four subcommands cover the full ops loop:

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
    """
    from sqlalchemy import text

    actor_name = _resolve_actor(actor)
    engine, factory = await _engine_factory()
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
    finally:
        await engine.dispose()
    return {
        "org_id": str(org_id),
        "monthly_input_token_limit": input_limit,
        "monthly_output_token_limit": output_limit,
        "actor": actor_name,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
