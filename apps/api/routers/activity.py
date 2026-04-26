"""Cross-project activity feed.

Aggregates recent events across every module into one chronological feed.
The hub endpoint (`/api/v1/projects/{id}`) answers "what's the state of my
projects"; this endpoint answers "what's changed since I last looked".

Implementation: a single `UNION ALL` query, one branch per source table.
Each branch projects into the same column shape so the result can be
ordered by timestamp and paginated as a flat stream.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import paginated
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from schemas.activity import (
    ActivityEvent,
    ActivityEventType,
    ActivityModule,
)

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


# A single UNION ALL across every event source. Each branch projects into
# the same eight columns: id, project_id, project_name, module, event_type,
# title, description, timestamp, actor_id, metadata (jsonb). Per-branch
# WHERE clauses scope by org and the rolling window.
_FEED_SQL = """
WITH events AS (
    -- ProjectPulse: change orders
    SELECT
        co.id,
        co.project_id,
        co.module,
        co.event_type,
        co.title,
        co.description,
        co.timestamp,
        co.actor_id,
        co.metadata
    FROM (
        SELECT
            id,
            project_id,
            'pulse'::text                AS module,
            'change_order_created'::text AS event_type,
            ('CO #' || number || ' — ' || title) AS title,
            description,
            created_at AS timestamp,
            approved_by AS actor_id,
            jsonb_build_object(
                'status', status,
                'initiator', initiator,
                'cost_impact_vnd', cost_impact_vnd,
                'schedule_impact_days', schedule_impact_days
            ) AS metadata
        FROM change_orders
        WHERE organization_id = :org_id
          AND created_at >= :since
    ) co

    UNION ALL

    -- ProjectPulse: tasks completed
    SELECT
        t.id,
        t.project_id,
        t.module,
        t.event_type,
        t.title,
        t.description,
        t.timestamp,
        t.actor_id,
        t.metadata
    FROM (
        SELECT
            id,
            project_id,
            'pulse'::text           AS module,
            'task_completed'::text  AS event_type,
            ('Task done: ' || title) AS title,
            description,
            completed_at AS timestamp,
            assignee_id  AS actor_id,
            jsonb_build_object(
                'status', status,
                'priority', priority,
                'phase', phase
            ) AS metadata
        FROM tasks
        WHERE organization_id = :org_id
          AND completed_at IS NOT NULL
          AND completed_at >= :since
    ) t

    UNION ALL

    -- SiteEye: safety incidents
    SELECT
        si.id,
        si.project_id,
        si.module,
        si.event_type,
        si.title,
        si.description,
        si.timestamp,
        si.actor_id,
        si.metadata
    FROM (
        SELECT
            id,
            project_id,
            'siteeye'::text                  AS module,
            'safety_incident_detected'::text AS event_type,
            ('Safety incident: ' || incident_type) AS title,
            ai_description AS description,
            detected_at    AS timestamp,
            acknowledged_by AS actor_id,
            jsonb_build_object(
                'severity', severity,
                'status',   status,
                'incident_type', incident_type
            ) AS metadata
        FROM safety_incidents
        WHERE organization_id = :org_id
          AND detected_at >= :since
    ) si

    UNION ALL

    -- Handover: defects
    SELECT
        d.id,
        d.project_id,
        d.module,
        d.event_type,
        d.title,
        d.description,
        d.timestamp,
        d.actor_id,
        d.metadata
    FROM (
        SELECT
            id,
            project_id,
            'handover'::text          AS module,
            'defect_reported'::text   AS event_type,
            ('Defect: ' || title)     AS title,
            description,
            reported_at AS timestamp,
            reported_by AS actor_id,
            jsonb_build_object(
                'priority', priority,
                'status',   status
            ) AS metadata
        FROM defects
        WHERE organization_id = :org_id
          AND reported_at >= :since
    ) d

    UNION ALL

    -- WinWork: proposals that got a response (won/lost)
    SELECT
        p.id,
        p.project_id,
        p.module,
        p.event_type,
        p.title,
        p.description,
        p.timestamp,
        p.actor_id,
        p.metadata
    FROM (
        SELECT
            id,
            project_id,
            'winwork'::text                  AS module,
            'proposal_outcome_marked'::text  AS event_type,
            ('Proposal ' || status || ': ' || title) AS title,
            NULL::text AS description,
            responded_at AS timestamp,
            created_by   AS actor_id,
            jsonb_build_object(
                'status', status,
                'total_fee_vnd', total_fee_vnd
            ) AS metadata
        FROM proposals
        WHERE organization_id = :org_id
          AND responded_at IS NOT NULL
          AND responded_at >= :since
    ) p

    UNION ALL

    -- Drawbridge: RFIs raised
    SELECT
        r.id,
        r.project_id,
        r.module,
        r.event_type,
        r.title,
        r.description,
        r.timestamp,
        r.actor_id,
        r.metadata
    FROM (
        SELECT
            id,
            project_id,
            'drawbridge'::text       AS module,
            'rfi_raised'::text       AS event_type,
            ('RFI #' || number || ' — ' || subject) AS title,
            description,
            created_at AS timestamp,
            raised_by  AS actor_id,
            jsonb_build_object(
                'status',   status,
                'priority', priority
            ) AS metadata
        FROM rfis
        WHERE organization_id = :org_id
          AND created_at >= :since
    ) r

    UNION ALL

    -- Handover: packages delivered
    SELECT
        hp.id,
        hp.project_id,
        hp.module,
        hp.event_type,
        hp.title,
        hp.description,
        hp.timestamp,
        hp.actor_id,
        hp.metadata
    FROM (
        SELECT
            id,
            project_id,
            'handover'::text                    AS module,
            'handover_package_delivered'::text  AS event_type,
            ('Handover delivered: ' || name)    AS title,
            NULL::text AS description,
            delivered_at AS timestamp,
            created_by   AS actor_id,
            jsonb_build_object('status', status) AS metadata
        FROM handover_packages
        WHERE organization_id = :org_id
          AND delivered_at IS NOT NULL
          AND delivered_at >= :since
    ) hp
)
SELECT
    e.*,
    p.name AS project_name
FROM events e
LEFT JOIN projects p ON p.id = e.project_id
WHERE
    (:project_id IS NULL OR e.project_id = :project_id)
    AND (:module     IS NULL OR e.module     = :module)
ORDER BY e.timestamp DESC
LIMIT :limit OFFSET :offset
"""

_COUNT_SQL = """
WITH events AS (
    SELECT id, project_id, 'pulse'::text AS module, created_at AS timestamp
    FROM change_orders
    WHERE organization_id = :org_id AND created_at >= :since
    UNION ALL
    SELECT id, project_id, 'pulse', completed_at
    FROM tasks
    WHERE organization_id = :org_id AND completed_at IS NOT NULL AND completed_at >= :since
    UNION ALL
    SELECT id, project_id, 'siteeye', detected_at
    FROM safety_incidents
    WHERE organization_id = :org_id AND detected_at >= :since
    UNION ALL
    SELECT id, project_id, 'handover', reported_at
    FROM defects
    WHERE organization_id = :org_id AND reported_at >= :since
    UNION ALL
    SELECT id, project_id, 'winwork', responded_at
    FROM proposals
    WHERE organization_id = :org_id AND responded_at IS NOT NULL AND responded_at >= :since
    UNION ALL
    SELECT id, project_id, 'drawbridge', created_at
    FROM rfis
    WHERE organization_id = :org_id AND created_at >= :since
    UNION ALL
    SELECT id, project_id, 'handover', delivered_at
    FROM handover_packages
    WHERE organization_id = :org_id AND delivered_at IS NOT NULL AND delivered_at >= :since
)
SELECT COUNT(*) AS n
FROM events
WHERE
    (:project_id IS NULL OR project_id = :project_id)
    AND (:module IS NULL OR module = :module)
"""


@router.get("")
async def get_activity_feed(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID | None = None,
    module: ActivityModule | None = Query(default=None),
    since_days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Chronological cross-module event feed for the caller's org.

    Returns events from the last `since_days` days across change orders,
    completed tasks, safety incidents, defects, proposal outcomes, RFIs,
    and handover deliveries. Most recent first.

    Filters: `project_id` to scope to one project; `module` to scope to
    one module. Pagination via `limit` / `offset`.
    """
    since = datetime.now(UTC) - timedelta(days=since_days)
    params = {
        "org_id": str(auth.organization_id),
        "since": since,
        "project_id": str(project_id) if project_id else None,
        "module": module.value if module else None,
        "limit": limit,
        "offset": offset,
    }

    rows = (await db.execute(text(_FEED_SQL), params)).mappings().all()
    total = (await db.execute(text(_COUNT_SQL), params)).scalar_one()

    events = [
        ActivityEvent(
            id=r["id"],
            project_id=r["project_id"],
            project_name=r["project_name"],
            module=ActivityModule(r["module"]),
            event_type=ActivityEventType(r["event_type"]),
            title=r["title"],
            description=r["description"],
            timestamp=r["timestamp"],
            actor_id=r["actor_id"],
            metadata=r["metadata"] or {},
        ).model_dump(mode="json")
        for r in rows
    ]

    page = (offset // limit) + 1 if limit else 1
    return paginated(events, page=page, per_page=limit, total=int(total or 0))
