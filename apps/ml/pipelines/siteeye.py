"""SiteEye AI pipeline — photo analysis + weekly report generation.

Built on LangGraph for the per-photo parallel analysis graph and LangChain
for the structured-LLM calls. Safety detections come from a Ray Serve
deployment exposing a fine-tuned YOLOv8m model; vision reasoning calls
use GPT-4o via the OpenAI SDK.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from core.config import get_settings
from db.session import TenantAwareSession
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from PIL import ExifTags, Image
from schemas.siteeye import (
    ConstructionPhase,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    PhotoAIAnalysis,
    PhotoDetection,
    ReportAttachment,
    ReportContent,
    ReportKPIs,
    SafetyStatus,
    WeeklyReport,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
_settings = get_settings()

# Strong refs for fire-and-forget asyncio tasks — without this set the GC
# can collect the Task before it finishes; see Python 3.11 release notes.
_BG_TASKS: set[asyncio.Task[None]] = set()

# ---------- Constants ----------

MAX_EDGE_PX = 1024
SAFETY_INCIDENT_CLASSES = {
    "no_hard_hat": (IncidentType.no_ppe, IncidentSeverity.high, "Worker without hard hat detected"),
    "no_vest": (
        IncidentType.no_ppe,
        IncidentSeverity.medium,
        "Worker without safety vest detected",
    ),
    "scaffold_unsafe": (
        IncidentType.unsafe_scaffold,
        IncidentSeverity.high,
        "Unsafe scaffold condition",
    ),
    "open_trench": (IncidentType.open_trench, IncidentSeverity.high, "Unprotected open trench"),
    "fire_hazard": (IncidentType.fire_hazard, IncidentSeverity.critical, "Fire hazard detected"),
    "electrical_hazard": (
        IncidentType.electrical_hazard,
        IncidentSeverity.high,
        "Exposed electrical hazard",
    ),
}
PPE_POSITIVE_CLASSES = {"hard_hat", "safety_vest", "harness", "safety_boots"}

PROGRESS_TAGS = ["foundation", "slab", "walls", "roof", "mep", "finishes", "exterior", "site_prep"]


# ---------- State ----------


@dataclass
class PhotoState:
    organization_id: UUID
    project_id: UUID
    photo_id: UUID
    file_id: UUID | None = None
    storage_key: str | None = None
    image_bytes: bytes | None = None
    exif_taken_at: datetime | None = None
    exif_location: dict[str, float] | None = None
    safety_detections: list[PhotoDetection] = field(default_factory=list)
    progress: dict[str, Any] = field(default_factory=dict)
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    phase: ConstructionPhase | None = None
    completion_hint: float | None = None
    safety_status: SafetyStatus = SafetyStatus.clear


# ---------- Public entry points ----------


async def enqueue_photo_analysis(
    *,
    organization_id: UUID,
    project_id: UUID,
    photo_ids: list[UUID],
) -> UUID:
    """Persist an ai_jobs row and kick the graph per photo (fire and forget)."""
    job_id = uuid4()
    async with TenantAwareSession(organization_id) as session:
        await session.execute(
            text(
                """
                INSERT INTO ai_jobs (id, organization_id, module, job_type, status, input, started_at)
                VALUES (:id, :org, 'siteeye', 'photo_analysis', 'running', CAST(:input AS jsonb), NOW())
                """
            ),
            {
                "id": str(job_id),
                "org": str(organization_id),
                "input": json.dumps(
                    {"photo_ids": [str(p) for p in photo_ids], "project_id": str(project_id)}
                ),
            },
        )

    async def _runner() -> None:
        try:
            await asyncio.gather(
                *(
                    run_photo_analysis(
                        organization_id=organization_id, project_id=project_id, photo_id=pid
                    )
                    for pid in photo_ids
                ),
                return_exceptions=True,
            )
            await _aggregate_progress(organization_id=organization_id, project_id=project_id)
            await _mark_job(job_id, organization_id, status_="completed")
        except Exception as exc:
            logger.exception("photo analysis job failed")
            await _mark_job(job_id, organization_id, status_="failed", error=str(exc))

    _BG_TASKS.add(task := asyncio.create_task(_runner()))
    task.add_done_callback(_BG_TASKS.discard)
    return job_id


async def run_photo_analysis(
    *, organization_id: UUID, project_id: UUID, photo_id: UUID
) -> PhotoState:
    state = PhotoState(organization_id=organization_id, project_id=project_id, photo_id=photo_id)
    graph = _build_photo_graph()
    result: PhotoState = await graph.ainvoke(state)  # type: ignore[assignment]
    await _persist_photo_analysis(result)
    return result


# ---------- LangGraph: photo analysis ----------


def _build_photo_graph():
    g = StateGraph(PhotoState)
    g.add_node("preprocess", _node_preprocess)
    g.add_node("safety", _node_safety)
    g.add_node("progress", _node_progress)
    g.add_node("describe", _node_describe)
    g.add_node("merge", _node_merge)
    g.add_edge(START, "preprocess")
    # Fan-out: three analyzers run in parallel off preprocess.
    g.add_edge("preprocess", "safety")
    g.add_edge("preprocess", "progress")
    g.add_edge("preprocess", "describe")
    g.add_edge("safety", "merge")
    g.add_edge("progress", "merge")
    g.add_edge("describe", "merge")
    g.add_edge("merge", END)
    return g.compile()


async def _node_preprocess(state: PhotoState) -> PhotoState:
    async with TenantAwareSession(state.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT p.file_id, f.storage_key
                    FROM site_photos p
                    LEFT JOIN files f ON f.id = p.file_id
                    WHERE p.id = :id AND p.organization_id = :org
                    """
                    ),
                    {"id": str(state.photo_id), "org": str(state.organization_id)},
                )
            )
            .mappings()
            .first()
        )
    if not row:
        raise LookupError(f"photo {state.photo_id} not found")
    state.file_id = row["file_id"]
    state.storage_key = row["storage_key"]

    raw = await _s3_get(state.storage_key) if state.storage_key else None
    if raw is None:
        return state

    img = Image.open(io.BytesIO(raw))
    state.exif_taken_at, state.exif_location = _extract_exif(img)
    img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    state.image_bytes = buf.getvalue()

    compressed_key = f"{state.storage_key}.1024.jpg"
    await _s3_put(compressed_key, state.image_bytes, content_type="image/jpeg")
    return state


async def _node_safety(state: PhotoState) -> PhotoState:
    if not state.image_bytes:
        return state
    detections = await _call_yolo_safety(state.image_bytes)
    state.safety_detections = detections

    violations = [
        d for d in detections if d.label in SAFETY_INCIDENT_CLASSES and d.confidence >= 0.5
    ]
    if violations:
        max(violations, key=lambda d: SAFETY_INCIDENT_CLASSES[d.label][1].value == "critical")
        state.safety_status = (
            SafetyStatus.critical
            if any(
                SAFETY_INCIDENT_CLASSES[v.label][1]
                in (IncidentSeverity.critical, IncidentSeverity.high)
                for v in violations
            )
            else SafetyStatus.warning
        )
        await _create_safety_incidents(state, violations)
    return state


async def _node_progress(state: PhotoState) -> PhotoState:
    if not state.image_bytes:
        return state
    llm = _vision_llm()
    prompt = (
        "You are a construction progress inspector. Analyze this site photo. "
        "Identify: what construction elements are visible, their completion state, "
        "and any quality or coordination issues. "
        "Return ONLY valid JSON with this shape: "
        '{"elements": [{"name": str, "state": "not_started|in_progress|complete", "confidence": 0..1}], '
        '"completion_indicators": [str], "quality_notes": [str], '
        '"phase": "site_prep|foundation|structure|envelope|mep|finishes|exterior|handover", '
        '"overall_completion_hint": 0..1}'
    )
    parser = JsonOutputParser()
    msg = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _data_url(state.image_bytes)}},
        ]
    )
    resp = await llm.ainvoke([msg])
    try:
        parsed = parser.parse(resp.content if isinstance(resp.content, str) else str(resp.content))
    except Exception:
        parsed = {}
    state.progress = parsed
    try:
        state.phase = ConstructionPhase(parsed.get("phase")) if parsed.get("phase") else None
    except ValueError:
        state.phase = None
    if isinstance(parsed.get("overall_completion_hint"), int | float):
        state.completion_hint = float(parsed["overall_completion_hint"])
    return state


async def _node_describe(state: PhotoState) -> PhotoState:
    if not state.image_bytes:
        return state
    llm = _vision_llm(temperature=0.3)
    system = SystemMessage(
        content=(
            "You describe construction site photos in two concise sentences "
            "for a Vietnamese construction PM. After the description, return a "
            "comma-separated list of 1-5 tags from this set: "
            + ", ".join(PROGRESS_TAGS)
            + ". Format: <description>\\nTAGS: tag1, tag2"
        )
    )
    user = HumanMessage(
        content=[
            {"type": "text", "text": "Describe this site photo and tag it."},
            {"type": "image_url", "image_url": {"url": _data_url(state.image_bytes)}},
        ]
    )
    resp = await llm.ainvoke([system, user])
    text_out = resp.content if isinstance(resp.content, str) else str(resp.content)
    desc, _, tag_line = text_out.partition("TAGS:")
    state.description = desc.strip() or None
    tags = [t.strip().lower() for t in tag_line.split(",") if t.strip()]
    state.tags = [t for t in tags if t in PROGRESS_TAGS]
    return state


async def _node_merge(state: PhotoState) -> PhotoState:
    # Nothing to do: each branch mutated independent fields. This node exists
    # so LangGraph has a single join point before END.
    return state


# ---------- Persistence ----------


async def _persist_photo_analysis(state: PhotoState) -> None:
    analysis = PhotoAIAnalysis(
        description=state.description,
        detected_elements=[
            e.get("name") for e in (state.progress.get("elements") or []) if e.get("name")
        ],
        safety_flags=state.safety_detections,
        progress_indicators={
            "completion_indicators": state.progress.get("completion_indicators", []),
            "quality_notes": state.progress.get("quality_notes", []),
            "elements": state.progress.get("elements", []),
        },
        phase=state.phase,
        completion_hint=state.completion_hint,
    )
    async with TenantAwareSession(state.organization_id) as session:
        await session.execute(
            text(
                """
                UPDATE site_photos
                SET ai_analysis = CAST(:analysis AS jsonb),
                    tags = :tags,
                    safety_status = :safety_status,
                    taken_at = COALESCE(taken_at, :taken_at),
                    location = COALESCE(location, CAST(:location AS jsonb))
                WHERE id = :id AND organization_id = :org
                """
            ),
            {
                "analysis": analysis.model_dump_json(),
                "tags": state.tags,
                "safety_status": state.safety_status.value,
                "taken_at": state.exif_taken_at,
                "location": json.dumps(state.exif_location) if state.exif_location else None,
                "id": str(state.photo_id),
                "org": str(state.organization_id),
            },
        )


async def _create_safety_incidents(state: PhotoState, violations: list[PhotoDetection]) -> None:
    """Persist each detected violation as a `safety_incidents` row, then mirror
    each into the project's daily log so the field team sees it in one place.

    The dailylog mirror is best-effort: a failure (missing migration, schema
    drift) MUST NOT prevent the incident itself from being recorded — that's
    the safety-critical write.
    """
    import logging

    log = logging.getLogger(__name__)
    now = datetime.now(UTC)
    async with TenantAwareSession(state.organization_id) as session:
        for v in violations:
            incident_type, severity, description = SAFETY_INCIDENT_CLASSES[v.label]
            row = (
                await session.execute(
                    text(
                        """
                    INSERT INTO safety_incidents
                      (organization_id, project_id, detected_at, incident_type, severity,
                       photo_id, detection_box, ai_description, status)
                    VALUES
                      (:org, :project_id, :now, :incident_type, :severity,
                       :photo_id, CAST(:box AS jsonb), :description, :status)
                    RETURNING id, project_id, detected_at, severity, incident_type,
                              ai_description
                    """
                    ),
                    {
                        "org": str(state.organization_id),
                        "project_id": str(state.project_id),
                        "now": now,
                        "incident_type": incident_type.value,
                        "severity": severity.value,
                        "photo_id": str(state.photo_id),
                        "box": json.dumps(
                            {"bbox": v.bbox, "confidence": v.confidence, "label": v.label}
                        ),
                        "description": description,
                        "status": IncidentStatus.open.value,
                    },
                )
            ).one()

            try:
                from services.dailylog_sync import sync_incident_to_dailylog

                await sync_incident_to_dailylog(
                    session,
                    organization_id=state.organization_id,
                    incident=row,
                )
            except Exception as exc:
                log.warning(
                    "siteeye.create_incident: dailylog sync failed for incident_id=%s: %s",
                    getattr(row, "id", None)
                    if hasattr(row, "id")
                    else (row._mapping.get("id") if hasattr(row, "_mapping") else None),
                    exc,
                )


# ---------- Progress aggregator ----------


async def _aggregate_progress(*, organization_id: UUID, project_id: UUID) -> None:
    """Roll up per-photo phase completion into a progress_snapshot for today."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    async with TenantAwareSession(organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, ai_analysis
                    FROM site_photos
                    WHERE organization_id = :org
                      AND project_id = :project_id
                      AND taken_at >= :week_start
                      AND ai_analysis IS NOT NULL
                    """
                    ),
                    {
                        "org": str(organization_id),
                        "project_id": str(project_id),
                        "week_start": week_start,
                    },
                )
            )
            .mappings()
            .all()
        )

        phase_totals: dict[str, list[float]] = {}
        photo_ids: list[str] = []
        for r in rows:
            ai = r["ai_analysis"] or {}
            phase = ai.get("phase")
            hint = ai.get("completion_hint")
            if phase and isinstance(hint, int | float):
                phase_totals.setdefault(phase, []).append(float(hint))
            photo_ids.append(str(r["id"]))

        phase_progress = {k: round(100 * sum(v) / len(v), 1) for k, v in phase_totals.items()}
        overall = (
            round(sum(phase_progress.values()) / max(len(phase_progress), 1), 1)
            if phase_progress
            else 0.0
        )

        await session.execute(
            text(
                """
                INSERT INTO progress_snapshots
                  (organization_id, project_id, snapshot_date, overall_progress_pct,
                   phase_progress, photo_ids)
                VALUES
                  (:org, :project_id, :day, :overall, CAST(:phases AS jsonb), :photo_ids)
                ON CONFLICT (project_id, snapshot_date) DO UPDATE SET
                  overall_progress_pct = EXCLUDED.overall_progress_pct,
                  phase_progress = EXCLUDED.phase_progress,
                  photo_ids = EXCLUDED.photo_ids
                """
            ),
            {
                "org": str(organization_id),
                "project_id": str(project_id),
                "day": today,
                "overall": overall,
                "phases": json.dumps(phase_progress),
                "photo_ids": photo_ids,
            },
        )


# ---------- Weekly report ----------


async def generate_weekly_report(
    *,
    organization_id: UUID,
    project_id: UUID,
    week_start: date,
    week_end: date,
) -> WeeklyReport:
    async with TenantAwareSession(organization_id) as session:
        data = await _gather_report_data(session, organization_id, project_id, week_start, week_end)
        content = await _assemble_report(data)

        # Attach the latest approved BOQ as a sidecar PDF. Best-effort:
        # projects without an approved estimate just skip this step
        # without failing the weekly report. Done before HTML rendering
        # so the report body could in future link to the attachment
        # via a Jinja loop on `content.attachments`.
        try:
            boq_attachment = await _maybe_render_boq_attachment(
                session, project_id=project_id, week_start=week_start
            )
            if boq_attachment is not None:
                content = content.model_copy(
                    update={"attachments": [*content.attachments, boq_attachment]}
                )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "weekly_report.boq_attach failed for project %s: %s",
                project_id,
                exc,
            )

        html = _render_html(content)
        pdf_url = await _render_pdf_and_upload(html, project_id, week_start)

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO weekly_reports
                      (organization_id, project_id, week_start, week_end,
                       content, rendered_html, pdf_url)
                    VALUES
                      (:org, :project_id, :week_start, :week_end,
                       CAST(:content AS jsonb), :html, :pdf_url)
                    ON CONFLICT (project_id, week_start) DO UPDATE SET
                      week_end = EXCLUDED.week_end,
                      content = EXCLUDED.content,
                      rendered_html = EXCLUDED.rendered_html,
                      pdf_url = EXCLUDED.pdf_url
                    RETURNING *
                    """
                    ),
                    {
                        "org": str(organization_id),
                        "project_id": str(project_id),
                        "week_start": week_start,
                        "week_end": week_end,
                        "content": content.model_dump_json(),
                        "html": html,
                        "pdf_url": pdf_url,
                    },
                )
            )
            .mappings()
            .one()
        )

    report_dict = dict(row)
    if isinstance(report_dict.get("content"), dict):
        report_dict["content"] = ReportContent.model_validate(report_dict["content"])
    return WeeklyReport.model_validate(report_dict)


async def _gather_report_data(
    session: AsyncSession,
    organization_id: UUID,
    project_id: UUID,
    week_start: date,
    week_end: date,
) -> dict[str, Any]:
    photos = (
        (
            await session.execute(
                text(
                    """
                SELECT id, ai_analysis, safety_status, taken_at, thumbnail_url
                FROM site_photos
                WHERE organization_id = :org AND project_id = :project_id
                  AND taken_at >= :start AND taken_at < (CAST(:end AS date) + INTERVAL '1 day')
                ORDER BY taken_at
                """
                ),
                {
                    "org": str(organization_id),
                    "project_id": str(project_id),
                    "start": week_start,
                    "end": week_end,
                },
            )
        )
        .mappings()
        .all()
    )
    incidents = (
        (
            await session.execute(
                text(
                    """
                SELECT * FROM safety_incidents
                WHERE organization_id = :org AND project_id = :project_id
                  AND detected_at >= :start AND detected_at < (CAST(:end AS date) + INTERVAL '1 day')
                """
                ),
                {
                    "org": str(organization_id),
                    "project_id": str(project_id),
                    "start": week_start,
                    "end": week_end,
                },
            )
        )
        .mappings()
        .all()
    )
    snapshots = (
        (
            await session.execute(
                text(
                    """
                SELECT * FROM progress_snapshots
                WHERE organization_id = :org AND project_id = :project_id
                ORDER BY snapshot_date DESC
                LIMIT 2
                """
                ),
                {"org": str(organization_id), "project_id": str(project_id)},
            )
        )
        .mappings()
        .all()
    )
    project = (
        (
            await session.execute(
                text(
                    "SELECT name, start_date, end_date FROM projects "
                    "WHERE id = :id AND organization_id = :org"
                ),
                {"id": str(project_id), "org": str(organization_id)},
            )
        )
        .mappings()
        .first()
    )

    return {
        "project": dict(project) if project else {},
        "week_start": week_start,
        "week_end": week_end,
        "photos": [dict(p) for p in photos],
        "incidents": [dict(i) for i in incidents],
        "snapshots": [dict(s) for s in snapshots],
    }


async def _assemble_report(data: dict[str, Any]) -> ReportContent:
    snapshots = data["snapshots"]
    latest = snapshots[0] if snapshots else None
    prev = snapshots[1] if len(snapshots) > 1 else None
    overall = float(latest["overall_progress_pct"]) if latest else 0.0
    delta = overall - float(prev["overall_progress_pct"]) if prev else overall

    project = data["project"]
    start = project.get("start_date")
    end = project.get("end_date")
    today = date.today()
    days_elapsed = (today - start).days if start else 0
    days_remaining = (end - today).days if end else None
    schedule_status = "on_track" if delta >= 1 else ("behind" if delta < 0.5 else "unknown")

    llm = ChatOpenAI(model="gpt-4o", temperature=0.2, api_key=_settings.openai_api_key)
    parser = JsonOutputParser()
    prompt = (
        "You are a professional construction project manager in Vietnam. "
        "Generate a weekly progress report from the data below. "
        "Respond in Vietnamese for user-facing text. "
        "Return ONLY JSON with keys: executive_summary, progress_this_week "
        "(object: overall, by_phase), safety_summary (object: incidents, status, notes), "
        "issues_and_risks (array of strings), next_week_plan (array of strings), "
        "photos_highlighted (array of photo id strings, max 6)."
    )
    context = {
        "project": data["project"],
        "week_start": str(data["week_start"]),
        "week_end": str(data["week_end"]),
        "overall_progress_pct": overall,
        "progress_delta_pct": delta,
        "phase_progress": (latest or {}).get("phase_progress", {}),
        "incidents": [
            {"type": i["incident_type"], "severity": i["severity"], "status": i["status"]}
            for i in data["incidents"]
        ],
        "photos_sample": [
            {"id": str(p["id"]), "tags": (p.get("ai_analysis") or {}).get("detected_elements", [])}
            for p in data["photos"][:20]
        ],
    }
    resp = await llm.ainvoke(
        [SystemMessage(content=prompt), HumanMessage(content=json.dumps(context, default=str))]
    )
    try:
        parsed = parser.parse(resp.content if isinstance(resp.content, str) else str(resp.content))
    except Exception:
        parsed = {
            "executive_summary": "",
            "progress_this_week": {"overall": f"{overall}%", "by_phase": {}},
            "safety_summary": {"incidents": len(data["incidents"]), "status": "unknown"},
            "issues_and_risks": [],
            "next_week_plan": [],
            "photos_highlighted": [],
        }

    highlighted = []
    for pid in parsed.get("photos_highlighted", [])[:6]:
        try:
            highlighted.append(UUID(str(pid)))
        except (ValueError, TypeError):
            continue

    return ReportContent(
        executive_summary=parsed.get("executive_summary", ""),
        progress_this_week=parsed.get("progress_this_week", {}),
        safety_summary=parsed.get(
            "safety_summary", {"incidents": len(data["incidents"]), "status": "unknown"}
        ),
        issues_and_risks=parsed.get("issues_and_risks", []),
        next_week_plan=parsed.get("next_week_plan", []),
        photos_highlighted=highlighted,
        kpis=ReportKPIs(
            days_elapsed=days_elapsed,
            days_remaining=days_remaining,
            schedule_status=schedule_status,  # type: ignore[arg-type]
            overall_progress_pct=overall,
        ),
    )


def _render_html(content: ReportContent) -> str:
    phase_rows = "".join(
        f"<tr><td>{p}</td><td>{v}%</td></tr>"
        for p, v in (content.progress_this_week.get("by_phase") or {}).items()
    )
    risks = "".join(f"<li>{r}</li>" for r in content.issues_and_risks)
    plans = "".join(f"<li>{p}</li>" for p in content.next_week_plan)
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<title>Báo cáo tuần</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;margin:2em auto;color:#111}}
h1,h2{{color:#0a3d62}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:.5em;text-align:left}}
.kpi{{display:inline-block;padding:.5em 1em;margin-right:.5em;background:#eef2f7;border-radius:6px}}
</style></head><body>
<h1>Báo cáo tuần công trường</h1>
<p>{content.executive_summary}</p>
<div>
 <span class="kpi">Tiến độ: {content.kpis.overall_progress_pct}%</span>
 <span class="kpi">Đã qua: {content.kpis.days_elapsed} ngày</span>
 <span class="kpi">Trạng thái: {content.kpis.schedule_status}</span>
</div>
<h2>Tiến độ theo giai đoạn</h2>
<table><tr><th>Hạng mục</th><th>Hoàn thành</th></tr>{phase_rows}</table>
<h2>An toàn</h2>
<p>Sự cố: {content.safety_summary.get("incidents", 0)} — {content.safety_summary.get("status", "")}</p>
<h2>Vấn đề & Rủi ro</h2><ul>{risks}</ul>
<h2>Kế hoạch tuần tới</h2><ul>{plans}</ul>
</body></html>"""


async def _render_pdf_and_upload(html: str, project_id: UUID, week_start: date) -> str:
    from weasyprint import HTML  # imported here to avoid cold-start cost

    pdf_bytes = await asyncio.to_thread(lambda: HTML(string=html).write_pdf())
    key = f"siteeye/reports/{project_id}/{week_start.isoformat()}.pdf"
    await _s3_put(key, pdf_bytes, content_type="application/pdf")
    return f"s3://{_settings.s3_bucket}/{key}"


async def _maybe_render_boq_attachment(
    session: AsyncSession,
    *,
    project_id: UUID,
    week_start: date,
) -> ReportAttachment | None:
    """If the project has an approved estimate, render its BOQ as a PDF.

    The intent is "give the recipient a one-click way to see the latest
    cost baseline alongside the weekly progress". Only approved
    estimates land here — drafts would noisily flap each week as the
    estimator iterates.

    Returns `None` (and logs at INFO) when:
      * The project has no approved estimate.
      * The approved estimate has zero BOQ rows (corrupt/in-flight).
      * `services.boq_io` isn't importable for some reason — the import
        is local so a missing reportlab can't take down the whole
        weekly cron.

    The session is reused (it's already tenant-scoped via
    `TenantAwareSession`) — no extra connection cost.
    """
    from models.costpulse import BoqItem, Estimate

    estimate = (
        await session.execute(
            select(Estimate)
            .where(Estimate.project_id == project_id, Estimate.status == "approved")
            .order_by(Estimate.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if estimate is None:
        logger.info(
            "weekly_report.boq_attach: no approved estimate for project %s; skipping",
            project_id,
        )
        return None

    items = (
        (
            await session.execute(
                select(BoqItem)
                .where(BoqItem.estimate_id == estimate.id)
                .order_by(BoqItem.sort_order)
            )
        )
        .scalars()
        .all()
    )
    if not items:
        logger.info(
            "weekly_report.boq_attach: estimate %s has no BOQ items; skipping",
            estimate.id,
        )
        return None

    # Build BoqRow values from the ORM rows. Local import: services.boq_io
    # depends on reportlab + openpyxl, which are heavy and not always
    # present in pure-ML test environments. Lazy-import keeps the
    # weekly cron robust to a misconfigured deploy that drops the deps.
    try:
        from services.boq_io import BoqRow, render_boq_pdf
    except ImportError as exc:
        logger.warning("weekly_report.boq_attach: services.boq_io missing: %s", exc)
        return None

    rows = [
        BoqRow(
            description=i.description or "",
            code=i.code,
            unit=i.unit,
            quantity=i.quantity,
            unit_price_vnd=i.unit_price_vnd,
            total_price_vnd=i.total_price_vnd,
            material_code=i.material_code,
            sort_order=i.sort_order or 0,
        )
        for i in items
    ]

    pdf_bytes = await asyncio.to_thread(render_boq_pdf, estimate.name, rows)
    key = f"siteeye/reports/{project_id}/{week_start.isoformat()}-boq.pdf"
    await _s3_put(key, pdf_bytes, content_type="application/pdf")
    return ReportAttachment(
        kind="boq_pdf",
        label=f"BOQ — {estimate.name}",
        url=f"s3://{_settings.s3_bucket}/{key}",
    )


async def email_weekly_report(
    *,
    organization_id: UUID,
    report_id: UUID,
    recipients: list[str],
    subject: str | None,
    message: str | None,
) -> bool:
    import aioboto3

    async with TenantAwareSession(organization_id) as session:
        row = (
            (
                await session.execute(
                    text("SELECT * FROM weekly_reports WHERE id = :id AND organization_id = :org"),
                    {"id": str(report_id), "org": str(organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if not row:
            return False

        body_html = row["rendered_html"] or ""
        subject_line = subject or f"Báo cáo tuần — {row['week_start']}"

        ses = aioboto3.Session(region_name=_settings.aws_region)
        async with ses.client("ses") as client:
            await client.send_email(
                Source=_settings.email_from,
                Destination={"ToAddresses": recipients},
                Message={
                    "Subject": {"Data": subject_line, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": body_html, "Charset": "UTF-8"},
                        "Text": {"Data": message or "See attached report.", "Charset": "UTF-8"},
                    },
                },
            )

        await session.execute(
            text(
                """
                UPDATE weekly_reports
                SET sent_to = :recipients, sent_at = NOW()
                WHERE id = :id AND organization_id = :org
                """
            ),
            {"id": str(report_id), "org": str(organization_id), "recipients": recipients},
        )
    return True


# ---------- External integrations ----------


def _vision_llm(*, temperature: float = 0.0) -> ChatOpenAI:
    return ChatOpenAI(
        model="gpt-4o",
        temperature=temperature,
        api_key=_settings.openai_api_key,
        timeout=60,
    )


async def _call_yolo_safety(image_bytes: bytes) -> list[PhotoDetection]:
    """POST the image to the Ray Serve deployment and parse detections."""
    url = f"{_ray_serve_base()}/siteeye-safety/infer"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, files={"image": ("photo.jpg", image_bytes, "image/jpeg")})
        resp.raise_for_status()
        payload = resp.json()
    return [
        PhotoDetection(
            label=d["label"],
            confidence=float(d["confidence"]),
            bbox=[float(x) for x in d["bbox"]],
        )
        for d in payload.get("detections", [])
    ]


def _ray_serve_base() -> str:
    return getattr(_settings, "siteeye_ray_serve_url", "http://siteeye-safety:8000")


async def _s3_get(key: str) -> bytes | None:
    import aioboto3

    session = aioboto3.Session(region_name=_settings.aws_region)
    async with session.client("s3") as client:
        try:
            obj = await client.get_object(Bucket=_settings.s3_bucket, Key=key)
            return await obj["Body"].read()
        except Exception:
            return None


async def _s3_put(key: str, body: bytes, *, content_type: str) -> None:
    import aioboto3

    session = aioboto3.Session(region_name=_settings.aws_region)
    async with session.client("s3") as client:
        await client.put_object(
            Bucket=_settings.s3_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )


def _data_url(image_bytes: bytes) -> str:
    import base64

    return "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")


def _extract_exif(img: Image.Image) -> tuple[datetime | None, dict[str, float] | None]:
    try:
        raw_exif = img.getexif()
    except Exception:
        return None, None
    if not raw_exif:
        return None, None
    tag_map = {ExifTags.TAGS.get(k, k): v for k, v in raw_exif.items()}
    taken_at: datetime | None = None
    dt_str = tag_map.get("DateTimeOriginal") or tag_map.get("DateTime")
    if dt_str:
        try:
            taken_at = datetime.strptime(str(dt_str), "%Y:%m:%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            taken_at = None

    gps_ifd = raw_exif.get_ifd(ExifTags.IFD.GPSInfo) if hasattr(ExifTags, "IFD") else {}
    location: dict[str, float] | None = None
    if gps_ifd:
        gps = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
        lat = _dms_to_deg(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
        lng = _dms_to_deg(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
        if lat is not None and lng is not None:
            location = {"lat": lat, "lng": lng}
    return taken_at, location


def _dms_to_deg(dms, ref) -> float | None:
    if not dms or not ref:
        return None
    try:
        deg, mins, secs = (float(x) for x in dms)
    except (TypeError, ValueError):
        return None
    val = deg + mins / 60 + secs / 3600
    if ref in ("S", "W"):
        val = -val
    return val


async def _mark_job(
    job_id: UUID, organization_id: UUID, *, status_: str, error: str | None = None
) -> None:
    async with TenantAwareSession(organization_id) as session:
        await session.execute(
            text(
                """
                UPDATE ai_jobs
                SET status = :status,
                    error = :error,
                    completed_at = CASE WHEN :status IN ('completed','failed') THEN NOW() ELSE completed_at END
                WHERE id = :id AND organization_id = :org
                """
            ),
            {"id": str(job_id), "org": str(organization_id), "status": status_, "error": error},
        )
