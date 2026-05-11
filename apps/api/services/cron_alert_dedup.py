"""Dedup ratchet for cron_alerts (cycle R3).

A cron failing 5 minutes in a row would otherwise produce 5 separate
Slack messages — every watchdog tick re-discovers the failure and
re-alerts. This module's `should_emit_alert` decides whether THIS
tick should re-alert, based on a (cron_name, kind) row in the
`cron_alerts_sent` table.

Decision rule:

  * No prior alert → emit (and INSERT a row).
  * Prior alert ≥ `_REPEAT_INTERVAL_SECONDS` ago → emit (and UPDATE
    `last_alert_at` + bump `alert_count`).
  * Otherwise → suppress (no DB write, no Slack message).

The repeat schedule is a fixed sequence:
  * First alert immediately on the failure.
  * Second alert 30 minutes later (if still failing).
  * Subsequent alerts every 6 hours (if still failing).

Why a graduated schedule rather than a flat interval:

  * 5 alerts in 5 minutes is the bug we're fixing — too noisy.
  * A flat 30-min repeat would mean a 6-hour outage produces 12
    Slack messages — still too noisy past the first hour.
  * A flat 6-hour repeat would mean a real "this just started
    failing" alert sits silent for 6h on the first re-alert —
    too quiet.
  * The graduated 30m → 6h schedule says "tell me once when it
    fails, remind me after 30 minutes if I haven't fixed it,
    then back off to every 6 hours so I don't burn out on the
    same incident."

This matches PagerDuty's repeat frequency UX and the alert-cadence
recommendations in the SRE Workbook.

Why `should_emit_alert` returns AND mutates state in one call: the
cron watchdog's loop does "for each row: should I alert? if so,
record the alert." Splitting into two calls leaves a window where
two concurrent watchdog instances both pass the decision but one
doubles the alert. The helper does the UPSERT in the same call —
the database PK enforces atomicity.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from db.session import AdminSessionFactory

logger = logging.getLogger(__name__)


# First re-alert interval after the initial alert. 30 minutes —
# long enough that a flaky-once cron that recovers on its own
# retry doesn't fire a follow-up; short enough that a real
# ongoing outage gets re-surfaced on the first incident-window
# boundary.
_FIRST_REPEAT_SECONDS = 30 * 60

# Subsequent re-alert interval. 6 hours matches PagerDuty's
# default high-priority repeat cadence — operators triaging the
# incident don't need a Slack ping every 30 minutes for the
# whole outage.
_SUBSEQUENT_REPEAT_SECONDS = 6 * 60 * 60


# Closed `kind` vocabulary mirroring services.cron_alerts._KIND
# strings. Pinned by the integrator-surface snapshot — drift means
# the dedup table accumulates rows for kinds the watchdog doesn't
# recognise.
ALERT_KINDS: frozenset[str] = frozenset({"cron_failure", "cron_stuck"})


async def should_emit_alert(*, cron_name: str, kind: str) -> dict[str, Any]:
    """Atomic upsert: decide whether to alert AND record the decision.

    Returns:
        {"emit": bool, "alert_count": int, "first_alert_at": str | None}

    Branch-by-branch:
      * No prior row → emit=True, alert_count=1, INSERT a row.
      * Prior row, repeat interval reached → emit=True, alert_count
        bumped, UPDATE the row.
      * Prior row, suppressed → emit=False, alert_count = existing,
        NO DB write.

    The `_repeat_interval_for(alert_count)` helper picks the
    threshold based on how many times we've already alerted —
    30min for the second alert, 6h for subsequent.

    Concurrency: two watchdog instances racing on the same row both
    see the prior `last_alert_at`. The UPSERT-with-condition pattern
    (`UPDATE ... WHERE last_alert_at < cutoff RETURNING`) ensures
    only ONE of them flips the row + emits the alert. The loser
    sees zero rows returned and short-circuits to suppress.
    """
    if kind not in ALERT_KINDS:
        # Defensive — caller's bug, not silently log + emit.
        raise ValueError(f"unknown alert kind: {kind!r}")

    async with AdminSessionFactory() as session:
        # Step 1: load existing row to compute the threshold for THIS
        # cron's next-alert window. We can't compute the threshold
        # purely in SQL because it depends on `alert_count` (different
        # cron has different cadence at different points in its
        # alert lifecycle).
        existing = (
            (
                await session.execute(
                    text(
                        """
                        SELECT alert_count, last_alert_at, first_alert_at
                        FROM cron_alerts_sent
                        WHERE cron_name = :cron_name AND kind = :kind
                        """
                    ),
                    {"cron_name": cron_name, "kind": kind},
                )
            )
            .mappings()
            .first()
        )

        if existing is None:
            # No prior alert — INSERT and emit. ON CONFLICT DO NOTHING
            # so a concurrent watchdog instance racing on the same
            # cron_name doesn't double-insert; the loser's RETURNING
            # is empty and we know to suppress.
            result = await session.execute(
                text(
                    """
                    INSERT INTO cron_alerts_sent
                      (cron_name, kind, alert_count, first_alert_at, last_alert_at)
                    VALUES (:cron_name, :kind, 1, NOW(), NOW())
                    ON CONFLICT (cron_name, kind) DO NOTHING
                    RETURNING alert_count, first_alert_at
                    """
                ),
                {"cron_name": cron_name, "kind": kind},
            )
            row = result.mappings().first()
            await session.commit()
            if row is None:
                # Concurrent insert won. We didn't emit.
                logger.debug(
                    "cron_alert_dedup: %s/%s lost concurrent insert race",
                    cron_name,
                    kind,
                )
                return {"emit": False, "alert_count": 0, "first_alert_at": None}
            return {
                "emit": True,
                "alert_count": int(row["alert_count"]),
                "first_alert_at": row["first_alert_at"].isoformat() if row["first_alert_at"] else None,
            }

        # Prior row exists. Compute the threshold based on its
        # alert_count + use a conditional UPDATE so two racing
        # watchdogs don't both pass.
        threshold_seconds = _repeat_interval_for(int(existing["alert_count"]))
        result = await session.execute(
            text(
                f"""
                UPDATE cron_alerts_sent
                SET last_alert_at = NOW(),
                    alert_count = alert_count + 1
                WHERE cron_name = :cron_name
                  AND kind = :kind
                  AND last_alert_at < NOW() - make_interval(secs => {threshold_seconds})
                RETURNING alert_count, first_alert_at
                """
            ),
            {"cron_name": cron_name, "kind": kind},
        )
        row = result.mappings().first()
        await session.commit()
        if row is None:
            # Within suppress window OR another watchdog beat us to it.
            return {
                "emit": False,
                "alert_count": int(existing["alert_count"]),
                "first_alert_at": existing["first_alert_at"].isoformat() if existing["first_alert_at"] else None,
            }
        return {
            "emit": True,
            "alert_count": int(row["alert_count"]),
            "first_alert_at": row["first_alert_at"].isoformat() if row["first_alert_at"] else None,
        }


def _repeat_interval_for(alert_count: int) -> int:
    """How long to wait before the next alert, given how many we've
    already sent.

    alert_count = 1 → next alert in 30 minutes.
    alert_count ≥ 2 → next alert in 6 hours.

    The graduated cadence matches the SRE Workbook's "remind me
    early, then back off" recommendation. See module docstring.
    """
    if alert_count <= 1:
        return _FIRST_REPEAT_SECONDS
    return _SUBSEQUENT_REPEAT_SECONDS


async def get_dedup_state(*, cron_name: str) -> list[dict[str, Any]]:
    """Read the dedup ratchet rows for one cron — used by the
    `/admin/crons/[name]` drilldown page (cycle S1).

    Returns one entry per `kind` that has an outstanding alert
    (cron_failure / cron_stuck). Includes the seconds-until-next-
    alert so the UI can render "next alert in 14m" without
    re-deriving the 30min/6h schedule client-side.

    Empty list = no outstanding alerts (the cron is healthy or
    was manually cleared).
    """
    sql = text(
        """
        SELECT
            cron_name,
            kind,
            alert_count,
            first_alert_at,
            last_alert_at,
            EXTRACT(EPOCH FROM (NOW() - first_alert_at))::int AS first_alert_age_seconds,
            EXTRACT(EPOCH FROM (NOW() - last_alert_at))::int  AS last_alert_age_seconds
        FROM cron_alerts_sent
        WHERE cron_name = :cron_name
        ORDER BY first_alert_at ASC
        """
    )
    async with AdminSessionFactory() as session:
        rows = (await session.execute(sql, {"cron_name": cron_name})).mappings().all()

    out: list[dict[str, Any]] = []
    for r in rows:
        # Compute seconds-until-next-alert from the graduated cadence.
        # The watchdog uses the same `_repeat_interval_for(alert_count)`
        # to decide when to re-emit; surfacing the same number here
        # means the UI shows the operator-true answer.
        next_at_seconds = _repeat_interval_for(int(r["alert_count"])) - int(r["last_alert_age_seconds"])
        out.append(
            {
                "cron_name": r["cron_name"],
                "kind": r["kind"],
                "alert_count": int(r["alert_count"]),
                "first_alert_at": r["first_alert_at"].isoformat() if r["first_alert_at"] else None,
                "last_alert_at": r["last_alert_at"].isoformat() if r["last_alert_at"] else None,
                "first_alert_age_seconds": int(r["first_alert_age_seconds"]),
                # `seconds_until_next_alert` can go negative when the
                # next-alert window has already opened but the cron is
                # no longer triggering the watchdog (the cron stopped
                # failing). Frontend renders negatives as "due now"
                # rather than a misleading countdown.
                "seconds_until_next_alert": next_at_seconds,
            }
        )
    return out


async def clear_alert(*, cron_name: str, kind: str) -> bool:
    """Manual reset — drop the dedup row so the next failure
    re-alerts fresh. Returns True if a row was deleted, False if
    none existed.

    Useful when an operator has acknowledged the failure and wants
    a fresh alert if it recurs (rather than waiting for the next
    repeat-interval boundary). Not currently exposed via UI; admin
    helpers can call this from a Python REPL.

    Cleared rows ARE preserved in the cleanup sweep below — this
    is the deliberate-clear path, not the time-based prune.
    """
    if kind not in ALERT_KINDS:
        raise ValueError(f"unknown alert kind: {kind!r}")
    async with AdminSessionFactory() as session:
        result = await session.execute(
            text(
                """
                DELETE FROM cron_alerts_sent
                WHERE cron_name = :cron_name AND kind = :kind
                """
            ),
            {"cron_name": cron_name, "kind": kind},
        )
        await session.commit()
        return int(result.rowcount or 0) > 0


__all__ = [
    "ALERT_KINDS",
    "clear_alert",
    "get_dedup_state",
    "should_emit_alert",
]
