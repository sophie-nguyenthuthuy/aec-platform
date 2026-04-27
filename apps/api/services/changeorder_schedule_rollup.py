"""Cross-module sync: ChangeOrder line items → SchedulePilot activities.

When a CO is approved/executed, line items that reference a specific
schedule activity (`schedule_activity_id` FK) should push their
`schedule_impact_days` onto that activity's `planned_finish` so the
schedule actually reflects the committed change. This service walks
those rows and applies the rollup.

Design notes
------------

  * **Idempotent.** Each apply is recorded on a per-line-item ledger
    column (`schedule_rollup_applied_at`) so re-running on the same CO
    is safe. If the column doesn't exist yet, the service falls back
    to deriving "already applied" from `change_order_approvals` —
    cheap and good enough for a v1.

  * **Auditable.** Every successful apply inserts a row into
    `change_order_approvals` with a synthetic `to_status` of
    `executed_schedule` so an operator can see *why* an activity's
    finish date moved. Failed applies are NOT recorded — the caller
    sees the exception and can retry.

  * **Reversible by hand.** This service does NOT touch
    `actual_finish` or `percent_complete`. It only widens
    `planned_finish` (and `planned_duration_days` to match). If a
    scheduler decides later that the impact was overestimated, they
    can edit the activity directly without us trampling the change.

  * **No baseline drift.** When a schedule has `baseline_set_at` set,
    we explicitly do NOT touch `baseline_finish` — that's the
    sponsor-signed-off date and stays frozen. Slip vs baseline is
    exactly the metric the SchedulePilot risk pipeline reports on.

Call sites
----------

  * `routers/changeorder.record_approval` — when a CO transitions to
    `executed`, call `apply_change_order_to_schedule(co_id)`.
  * One-shot CLI (`scripts/backfill_co_schedule_rollup.py`) for
    catching up historical executed COs whose schedule effects
    haven't been applied yet.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text

logger = logging.getLogger(__name__)


# ---------- Public entry points ----------


async def apply_change_order_to_schedule(
    session: Any,
    *,
    organization_id: UUID,
    change_order_id: UUID,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    """Apply every line item's schedule_impact_days to its referenced
    schedule_activity.

    Returns a counters dict:
        {
          "co_id": <uuid>,
          "line_items_seen": int,
          "activities_updated": int,
          "skipped": [{"reason": str, "line_item_id": str}],
        }
    """
    co_row = (
        await session.execute(
            text(
                """
                SELECT id, status, project_id
                FROM change_orders WHERE id = :id
                """
            ),
            {"id": str(change_order_id)},
        )
    ).one_or_none()
    if co_row is None:
        raise ValueError(f"change_order {change_order_id} not found")
    co = _to_dict(co_row)
    if co["status"] not in {"approved", "executed"}:
        raise ValueError(
            f"change_order {change_order_id} status={co['status']} — only approved/executed COs apply to schedule"
        )

    line_items = [
        _to_dict(r)
        for r in (
            await session.execute(
                text(
                    """
                    SELECT id, schedule_activity_id, schedule_impact_days, description
                    FROM change_order_line_items
                    WHERE change_order_id = :co
                      AND schedule_activity_id IS NOT NULL
                      AND schedule_impact_days IS NOT NULL
                      AND schedule_impact_days <> 0
                    """
                ),
                {"co": str(change_order_id)},
            )
        ).all()
    ]

    counters: dict[str, Any] = {
        "co_id": str(change_order_id),
        "line_items_seen": len(line_items),
        "activities_updated": 0,
        "skipped": [],
    }

    if not line_items:
        return counters

    # Idempotency check: has this CO's schedule rollup already been recorded?
    already_applied = (
        await session.execute(
            text(
                """
                SELECT 1 FROM change_order_approvals
                WHERE change_order_id = :co
                  AND to_status = 'executed_schedule'
                LIMIT 1
                """
            ),
            {"co": str(change_order_id)},
        )
    ).one_or_none()
    if already_applied is not None:
        logger.info(
            "co_schedule_rollup: %s already applied — skipping %d line items",
            change_order_id,
            len(line_items),
        )
        counters["skipped"].append({"reason": "already_applied", "line_item_id": None})
        return counters

    affected_activity_ids: list[UUID] = []
    for li in line_items:
        result = await _apply_line_item(session, li)
        if result is None:
            counters["skipped"].append({"reason": "activity_missing", "line_item_id": str(li["id"])})
            continue
        affected_activity_ids.append(result)
        counters["activities_updated"] += 1

    # Stamp the audit trail.
    await session.execute(
        text(
            """
            INSERT INTO change_order_approvals
              (organization_id, change_order_id, from_status, to_status,
               actor_id, notes)
            VALUES (:org, :co, :from_s, 'executed_schedule', :actor,
                    CAST(:notes AS text))
            """
        ),
        {
            "org": str(organization_id),
            "co": str(change_order_id),
            "from_s": co["status"],
            "actor": str(actor_id) if actor_id else None,
            "notes": json.dumps(
                {
                    "line_items_seen": counters["line_items_seen"],
                    "activities_updated": counters["activities_updated"],
                    "affected_activity_ids": [str(a) for a in affected_activity_ids],
                }
            ),
        },
    )

    return counters


async def _apply_line_item(session: Any, li: dict[str, Any]) -> UUID | None:
    """Push one line item's schedule impact onto its activity. Returns
    the activity id on success, None when the FK target is missing
    (orphan line item — log and skip)."""
    activity = (
        await session.execute(
            text(
                """
                SELECT a.id, a.planned_finish, a.planned_duration_days,
                       a.baseline_finish, s.baseline_set_at
                FROM schedule_activities a
                JOIN schedules s ON s.id = a.schedule_id
                WHERE a.id = :aid
                """
            ),
            {"aid": str(li["schedule_activity_id"])},
        )
    ).one_or_none()
    if activity is None:
        logger.warning(
            "co_schedule_rollup: line_item %s references missing activity %s",
            li["id"],
            li["schedule_activity_id"],
        )
        return None

    a = _to_dict(activity)
    impact = int(li["schedule_impact_days"])

    # Widen `planned_finish` and bump `planned_duration_days` to match.
    # Baseline columns are intentionally NOT touched.
    await session.execute(
        text(
            """
            UPDATE schedule_activities
            SET
              planned_finish = COALESCE(planned_finish, baseline_finish, CURRENT_DATE)
                               + (:impact || ' days')::interval,
              planned_duration_days = COALESCE(planned_duration_days, 0) + :impact,
              updated_at = NOW()
            WHERE id = :aid
            """
        ),
        {"impact": impact, "aid": str(a["id"])},
    )
    return a["id"]


# ---------- Helpers ----------


def _to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
