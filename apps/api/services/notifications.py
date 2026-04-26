"""Daily activity digest builder.

Given a user + their watched projects, query the activity-feed UNION over
the last 24h and shape the result into a digest payload (sender-agnostic
— `digest_for_user` returns text+html bodies; `dispatch_daily_digests`
fans them out via the mailer).

Lives outside `services/mailer.py` to keep the latter focused on
SMTP plumbing — this file owns the *content*.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.mailer import Delivery, send_mail

logger = logging.getLogger(__name__)


# Module-name → human label used in the email body.
_MODULE_LABEL = {
    "pulse": "ProjectPulse",
    "siteeye": "SiteEye",
    "handover": "Handover",
    "winwork": "WinWork",
    "drawbridge": "Drawbridge",
    "costpulse": "CostPulse",
    "codeguard": "CodeGuard",
}


# Reuses the same UNION-ALL shape as `routers/activity.py` but scoped to
# the watched-project set + a 24h window. Dropping the `project_name`
# join here because we already have project names in hand from the
# watches list — saves one JOIN.
_DIGEST_SQL = """
WITH events AS (
    SELECT id, project_id, 'pulse'::text AS module,
           ('CO #' || number || ' — ' || title) AS title,
           created_at AS timestamp
    FROM change_orders
    WHERE organization_id = :org_id
      AND project_id = ANY(:project_ids)
      AND created_at >= :since

    UNION ALL
    SELECT id, project_id, 'pulse', ('Task done: ' || title), completed_at
    FROM tasks
    WHERE organization_id = :org_id
      AND project_id = ANY(:project_ids)
      AND completed_at IS NOT NULL AND completed_at >= :since

    UNION ALL
    SELECT id, project_id, 'siteeye',
           ('Safety incident: ' || incident_type), detected_at
    FROM safety_incidents
    WHERE organization_id = :org_id
      AND project_id = ANY(:project_ids)
      AND detected_at >= :since

    UNION ALL
    SELECT id, project_id, 'handover', ('Defect: ' || title), reported_at
    FROM defects
    WHERE organization_id = :org_id
      AND project_id = ANY(:project_ids)
      AND reported_at >= :since

    UNION ALL
    SELECT id, project_id, 'drawbridge',
           ('RFI #' || number || ' — ' || subject), created_at
    FROM rfis
    WHERE organization_id = :org_id
      AND project_id = ANY(:project_ids)
      AND created_at >= :since

    UNION ALL
    SELECT id, project_id, 'handover',
           ('Handover delivered: ' || name), delivered_at
    FROM handover_packages
    WHERE organization_id = :org_id
      AND project_id = ANY(:project_ids)
      AND delivered_at IS NOT NULL AND delivered_at >= :since
)
SELECT * FROM events
ORDER BY timestamp DESC
LIMIT 200
"""


async def digest_for_user(
    session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    user_email: str,
    project_ids_to_names: dict[UUID, str],
    since_hours: int = 24,
) -> dict[str, Any] | None:
    """Build the digest payload for one user.

    Returns ``None`` when the user has zero events in the window — caller
    should NOT email an empty digest. Otherwise returns a dict with
    `subject`, `text_body`, `html_body`, `event_count`, plus per-project
    grouped events for callers that want to log/inspect them.
    """
    if not project_ids_to_names:
        return None

    since = datetime.now(UTC) - timedelta(hours=since_hours)
    rows = (
        (
            await session.execute(
                text(_DIGEST_SQL),
                {
                    "org_id": str(organization_id),
                    "project_ids": [str(pid) for pid in project_ids_to_names],
                    "since": since,
                },
            )
        )
        .mappings()
        .all()
    )

    if not rows:
        return None

    # Group by project so the email reads project-by-project rather than
    # by raw chronological order.
    by_project: dict[UUID, list[dict]] = defaultdict(list)
    for r in rows:
        by_project[r["project_id"]].append(dict(r))

    text_body = _render_text(by_project, project_ids_to_names, since_hours)
    html_body = _render_html(by_project, project_ids_to_names, since_hours)

    return {
        "to": user_email,
        "user_id": user_id,
        "subject": f"AEC: {len(rows)} hoạt động trong 24h qua",
        "text_body": text_body,
        "html_body": html_body,
        "event_count": len(rows),
        "events_by_project": {
            str(pid): [{**e, "project_id": str(e["project_id"])} for e in events] for pid, events in by_project.items()
        },
    }


def _render_text(
    by_project: dict[UUID, list[dict]],
    names: dict[UUID, str],
    since_hours: int,
) -> str:
    """Plain-text fallback. Renders one section per watched project."""
    lines = [f"AEC Platform — hoạt động {since_hours}h qua", ""]
    for pid, events in by_project.items():
        lines.append(f"## {names.get(pid, str(pid))} ({len(events)} sự kiện)")
        for e in events:
            label = _MODULE_LABEL.get(e["module"], e["module"])
            ts = e["timestamp"].strftime("%H:%M") if e["timestamp"] else ""
            lines.append(f"  · [{label}] {e['title']}  ({ts})")
        lines.append("")
    lines.append("—")
    lines.append("Mở trang Hoạt động để xem chi tiết: /activity")
    return "\n".join(lines)


def _render_html(
    by_project: dict[UUID, list[dict]],
    names: dict[UUID, str],
    since_hours: int,
) -> str:
    """Single-string HTML — kept inline so the mailer doesn't need a
    template engine. Email clients are notoriously fussy about CSS, so
    we use only inline styles + table layout."""
    blocks = []
    for pid, events in by_project.items():
        items = "".join(
            f'<li style="margin:4px 0">'
            f"<strong>{_MODULE_LABEL.get(e['module'], e['module'])}</strong> · "
            f"{_html_escape(e['title'])} "
            f'<span style="color:#888">({e["timestamp"].strftime("%H:%M") if e["timestamp"] else ""})</span>'
            f"</li>"
            for e in events
        )
        blocks.append(
            f'<h3 style="margin:16px 0 4px;font-size:14px">'
            f"{_html_escape(names.get(pid, str(pid)))} "
            f'<span style="color:#666;font-weight:normal">({len(events)} sự kiện)</span>'
            f"</h3>"
            f'<ul style="margin:0;padding-left:20px;font-size:13px">{items}</ul>'
        )
    body = "".join(blocks)
    return (
        f'<div style="font-family:system-ui,sans-serif;color:#222;max-width:560px">'
        f'<p style="font-size:13px;color:#666">'
        f"AEC Platform — hoạt động {since_hours}h qua"
        f"</p>"
        f"{body}"
        f'<p style="margin-top:24px;font-size:12px;color:#999;border-top:1px solid #eee;padding-top:12px">'
        f"Mở trang Hoạt động để xem chi tiết."
        f"</p>"
        f"</div>"
    )


def _html_escape(s: str) -> str:
    """Inline minimal escape — `html.escape` would also work, but this
    keeps the dep surface flat and consistent with the rest of the
    inline-template pattern."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------- Cron entry point ----------


async def dispatch_daily_digests(session: AsyncSession) -> dict[str, Any]:
    """Iterate every (user, watched-projects) pair across all tenants and
    send digests for users that had events. Called from
    `workers.queue.daily_activity_digest_cron`.

    Idempotency: there's no dedupe state — we accept that running this
    twice in a day double-sends. The cron schedule (one-shot at 07:00)
    is the dedupe. If we ever need at-most-once semantics, add a
    `digest_runs (user_id, sent_at::date)` table and skip per-day.
    """
    pairs = (
        await session.execute(
            text(
                """
                SELECT
                    u.id    AS user_id,
                    u.email AS user_email,
                    pw.organization_id,
                    pw.project_id,
                    p.name  AS project_name
                FROM project_watches pw
                JOIN users    u ON u.id = pw.user_id
                JOIN projects p ON p.id = pw.project_id
                ORDER BY u.id, pw.organization_id
                """
            )
        )
    ).all()

    # Group watches by (user, org).
    grouped: dict[tuple[UUID, UUID, str], dict[UUID, str]] = defaultdict(dict)
    for r in pairs:
        grouped[(r.user_id, r.organization_id, r.user_email)][r.project_id] = r.project_name

    sent = 0
    skipped_empty = 0
    deliveries: list[Delivery] = []
    for (user_id, org_id, email), project_map in grouped.items():
        digest = await digest_for_user(
            session,
            organization_id=org_id,
            user_id=user_id,
            user_email=email,
            project_ids_to_names=project_map,
        )
        if digest is None:
            skipped_empty += 1
            continue
        d = await send_mail(
            to=digest["to"],
            subject=digest["subject"],
            text_body=digest["text_body"],
            html_body=digest["html_body"],
        )
        deliveries.append(d)
        if d.get("delivered"):
            sent += 1

    return {
        "candidates": len(grouped),
        "sent": sent,
        "skipped_no_activity": skipped_empty,
        "deliveries": [{"to": d["to"], "delivered": d["delivered"], "reason": d.get("reason")} for d in deliveries],
    }
