"""AI pipelines for the PROJECTPULSE module.

Three pipelines:
  - analyze_change_order:   Impact + recommendation analysis on a CO.
  - structure_meeting_notes: Freeform notes → structured summary + action items.
  - generate_client_report:  Aggregate project data → client-facing narrative.

Uses LangChain with Anthropic Claude. LangGraph is used for the report pipeline
(multi-step: aggregate → narrate → render).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Literal
from uuid import UUID

from core.config import get_settings
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from schemas.pulse import (
    ActionItem,
    ChangeOrderAIAnalysis,
    ClientReportContent,
    MeetingStructured,
)

logger = logging.getLogger(__name__)


def _llm(temperature: float = 0.2) -> ChatAnthropic:
    settings = get_settings()
    return ChatAnthropic(
        model=settings.anthropic_model,
        anthropic_api_key=settings.anthropic_api_key,
        temperature=temperature,
        max_tokens=4096,
    )


# ---------------------------------------------------------------------------
# Change Order Analysis
# ---------------------------------------------------------------------------

_CO_SYSTEM = """You are a senior AEC construction contract analyst.
You evaluate Change Orders (COs) from Vietnamese construction projects.
Classify, assess, and recommend. Respond ONLY with valid JSON matching the
schema provided. Do not include any narration outside the JSON object."""

_CO_HUMAN = """Analyze the following Change Order.

Description:
{description}

Cost impact (VND): {cost_impact_vnd}
Schedule impact (days): {schedule_impact_days}
Initiator: {initiator}

Project context:
{project_context}

Produce a JSON object with this exact shape:
{{
  "root_cause": "design_change" | "scope_creep" | "site_condition" | "error" | "other",
  "cost_breakdown": {{"summary": "...", "reasonable": true|false, "notes": "..."}},
  "schedule_analysis": {{"summary": "...", "critical_path_impact": true|false, "notes": "..."}},
  "contract_clauses": ["<clause reference>", ...],
  "recommendation": "approve" | "negotiate" | "reject" | "request_more_info",
  "reasoning": "<2-4 sentence rationale>",
  "confidence": <float 0..1>
}}"""


async def analyze_change_order(
    *,
    description: str,
    cost_impact_vnd: int | None,
    schedule_impact_days: int | None,
    initiator: str | None,
    project_context: dict[str, Any],
) -> ChangeOrderAIAnalysis:
    prompt = ChatPromptTemplate.from_messages(
        [SystemMessage(content=_CO_SYSTEM), ("human", _CO_HUMAN)]
    )
    chain = prompt | _llm(temperature=0.1) | JsonOutputParser()

    raw = await chain.ainvoke(
        {
            "description": description or "(no description provided)",
            "cost_impact_vnd": cost_impact_vnd if cost_impact_vnd is not None else "unknown",
            "schedule_impact_days": schedule_impact_days
            if schedule_impact_days is not None
            else "unknown",
            "initiator": initiator or "unknown",
            "project_context": json.dumps(project_context, ensure_ascii=False, default=str),
        }
    )
    return ChangeOrderAIAnalysis.model_validate(raw)


# ---------------------------------------------------------------------------
# Meeting Notes Structuring
# ---------------------------------------------------------------------------

_MEETING_SYSTEM = """You structure freeform AEC project meeting notes.
Input may be Vietnamese, English, or mixed. Preserve the original language in
the output fields. Extract only facts present in the input — do not invent.
Respond ONLY with valid JSON."""

_MEETING_HUMAN = """Structure these meeting notes.

Preferred output language: {language}

Raw notes:
---
{raw_notes}
---

Produce a JSON object with this exact shape:
{{
  "summary": "<3-6 sentence summary>",
  "decisions": ["<decision>", ...],
  "action_items": [
    {{"title": "<task>", "owner": "<name or null>", "deadline": "YYYY-MM-DD or null"}},
    ...
  ],
  "risks": ["<risk>", ...],
  "next_meeting": "YYYY-MM-DD or null"
}}"""


async def structure_meeting_notes(
    *,
    raw_notes: str,
    language: Literal["vi", "en"] | None = None,
) -> MeetingStructured:
    prompt = ChatPromptTemplate.from_messages(
        [SystemMessage(content=_MEETING_SYSTEM), ("human", _MEETING_HUMAN)]
    )
    chain = prompt | _llm(temperature=0.1) | JsonOutputParser()

    raw = await chain.ainvoke(
        {
            "raw_notes": raw_notes,
            "language": language or "match input",
        }
    )

    action_items = [
        ActionItem(
            title=item.get("title", ""),
            owner=item.get("owner"),
            deadline=_parse_date(item.get("deadline")),
        )
        for item in raw.get("action_items", [])
        if item.get("title")
    ]
    return MeetingStructured(
        summary=raw.get("summary", ""),
        decisions=[d for d in raw.get("decisions", []) if d],
        action_items=action_items,
        risks=[r for r in raw.get("risks", []) if r],
        next_meeting=_parse_date(raw.get("next_meeting")),
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Client Report Generation (LangGraph multi-step pipeline)
# ---------------------------------------------------------------------------


class _ReportState(dict[str, Any]):
    """State passed between graph nodes."""


_REPORT_SYSTEM = """You write client-facing progress reports for AEC projects.
Tone: professional, reassuring, factual. Do not over-promise. Do not invent
details beyond the provided data. Return ONLY valid JSON."""

_REPORT_HUMAN = """Write a progress report for a client.

Language: {language}
Period: {period}
Include photos section: {include_photos}
Include financials section: {include_financials}

Data (JSON):
{data}

Notes for the writer:
- `data.completed_tasks` / `data.milestones` drive the progress narrative.
- `data.change_orders` and `data.approved_change_order_totals` drive the
  cost/schedule impact sentences in `header_summary` and `financials`.
- `data.schedule_slip` (when present) reports SchedulePilot CPM slip in
  days. Mention it under `issues` only when `overall_slip_days > 0` —
  use a sentence like "X activities are tracking past baseline; CPM
  forecast is N days late."
- `data.submittals` (when present) reports the submittal queue. Mention
  the count if `revise_resubmit_count > 0` (a real issue) or if the
  contractor's queue is large (`contractor_court_count > 5`).
- `data.dailylog` (when present) summarises field-log issues. Reference
  `high_severity_observation_count` under `issues` when > 0.
- `data.changeorder_extended.pending_candidates` (when > 0) is worth a
  brief line in `next_steps` — these are AI-suggested changes awaiting
  the team's review.

Produce a JSON object with this exact shape:
{{
  "header_summary": "<1 paragraph overview in the requested language>",
  "progress_section": {{
    "narrative": "<2-3 paragraphs>",
    "highlights": ["<bullet>", ...],
    "progress_pct": <float 0..100>
  }},
  "photos_section": [{{"caption": "...", "url": "..."}}],
  "financials": {{"narrative": "...", "summary": {{"spent": null, "budget": null, "variance": null}}}},
  "issues": [{{"title": "...", "status": "...", "impact": "..."}}],
  "next_steps": ["<bullet>", ...]
}}"""


async def _narrate_node(state: _ReportState) -> _ReportState:
    prompt = ChatPromptTemplate.from_messages(
        [SystemMessage(content=_REPORT_SYSTEM), ("human", _REPORT_HUMAN)]
    )
    chain = prompt | _llm(temperature=0.4) | JsonOutputParser()
    raw = await chain.ainvoke(
        {
            "language": state["language"],
            "period": state["period"],
            "include_photos": state["include_photos"],
            "include_financials": state["include_financials"],
            "data": json.dumps(state["data"], ensure_ascii=False, default=str),
        }
    )
    state["content"] = raw
    return state


async def _validate_node(state: _ReportState) -> _ReportState:
    raw = state["content"]
    content = ClientReportContent(
        header_summary=raw.get("header_summary", ""),
        progress_section=raw.get("progress_section", {}),
        photos_section=raw.get("photos_section", []) if state["include_photos"] else [],
        financials=raw.get("financials") if state["include_financials"] else None,
        issues=raw.get("issues", []),
        next_steps=raw.get("next_steps", []),
    )
    state["validated"] = content
    return state


def _build_report_graph():
    graph: StateGraph = StateGraph(_ReportState)
    graph.add_node("narrate", _narrate_node)
    graph.add_node("validate", _validate_node)
    graph.set_entry_point("narrate")
    graph.add_edge("narrate", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


_REPORT_GRAPH = _build_report_graph()


async def generate_client_report(
    *,
    project_id: UUID,
    period: str,
    language: Literal["vi", "en"],
    include_photos: bool,
    include_financials: bool,
    data: dict[str, Any],
) -> ClientReportContent:
    state = _ReportState(
        project_id=str(project_id),
        period=period,
        language=language,
        include_photos=include_photos,
        include_financials=include_financials,
        data=data,
    )
    result = await _REPORT_GRAPH.ainvoke(state)
    return result["validated"]


# ---------------------------------------------------------------------------
# HTML rendering (branded template)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; color: #1a1a1a; max-width: 820px; margin: 32px auto; padding: 0 24px; }}
  h1 {{ color: #0f3b82; border-bottom: 3px solid #0f3b82; padding-bottom: 8px; }}
  h2 {{ color: #0f3b82; margin-top: 32px; }}
  .summary {{ background: #f4f7fb; padding: 16px 20px; border-radius: 8px; }}
  .highlights li {{ margin: 4px 0; }}
  .issue {{ border-left: 4px solid #e08b00; padding: 8px 12px; margin: 8px 0; background: #fff7e6; }}
  .photos {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
  .photo figcaption {{ font-size: 12px; color: #555; }}
</style>
</head>
<body>
  <h1>{title}</h1>
  <div class="summary">{header_summary}</div>

  <h2>{progress_label}</h2>
  <p>{progress_narrative}</p>
  <ul class="highlights">{highlights}</ul>

  {photos_html}
  {financials_html}

  <h2>{issues_label}</h2>
  {issues_html}

  <h2>{next_steps_label}</h2>
  <ul>{next_steps_html}</ul>
</body>
</html>"""


async def render_report_html(
    content: ClientReportContent,
    *,
    language: Literal["vi", "en"] = "vi",
) -> str:
    labels = {
        "vi": {
            "title": "Báo cáo tiến độ dự án",
            "progress": "Tiến độ",
            "photos": "Hình ảnh công trường",
            "financials": "Tình hình tài chính",
            "issues": "Vấn đề & Change Orders",
            "next_steps": "Bước tiếp theo",
        },
        "en": {
            "title": "Project Progress Report",
            "progress": "Progress",
            "photos": "Site Photos",
            "financials": "Financials",
            "issues": "Issues & Change Orders",
            "next_steps": "Next Steps",
        },
    }[language]

    highlights = "".join(
        f"<li>{_escape(h)}</li>" for h in (content.progress_section or {}).get("highlights", [])
    )
    narrative = _escape((content.progress_section or {}).get("narrative", ""))

    photos_html = ""
    if content.photos_section:
        photos_html = f'<h2>{labels["photos"]}</h2><div class="photos">'
        for p in content.photos_section:
            url = _escape(p.get("url", ""))
            caption = _escape(p.get("caption", ""))
            photos_html += (
                f'<figure class="photo"><img src="{url}" style="width:100%"/>'
                f"<figcaption>{caption}</figcaption></figure>"
            )
        photos_html += "</div>"

    financials_html = ""
    if content.financials:
        financials_html = f"<h2>{labels['financials']}</h2><p>{_escape(content.financials.get('narrative', ''))}</p>"

    issues_html = (
        "".join(
            f'<div class="issue"><strong>{_escape(i.get("title", ""))}</strong> — '
            f"{_escape(i.get('status', ''))}. {_escape(i.get('impact', ''))}</div>"
            for i in content.issues
        )
        or "<p>—</p>"
    )

    next_steps_html = "".join(f"<li>{_escape(s)}</li>" for s in content.next_steps)

    return _HTML_TEMPLATE.format(
        lang=language,
        title=labels["title"],
        header_summary=_escape(content.header_summary),
        progress_label=labels["progress"],
        progress_narrative=narrative,
        highlights=highlights,
        photos_html=photos_html,
        financials_html=financials_html,
        issues_label=labels["issues"],
        issues_html=issues_html,
        next_steps_label=labels["next_steps"],
        next_steps_html=next_steps_html,
    )


def _escape(s: Any) -> str:
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class PDFRendererUnavailable(RuntimeError):
    """Raised when the optional WeasyPrint dependency isn't installed.

    The caller is expected to catch this and fall back to HTML-only reports
    (the route keeps `pdf_url = None`) instead of surfacing a 5xx.
    """


async def render_report_pdf(html: str, *, base_url: str | None = None) -> bytes:
    """Render an HTML string into a PDF byte string via WeasyPrint.

    WeasyPrint is imported lazily so the rest of the module (and all router
    tests that only exercise the HTML path) don't pay the native-dependency
    cost. If WeasyPrint isn't installed we raise `PDFRendererUnavailable`,
    which the generate-report route turns into a graceful skip — the report
    still persists with `pdf_url=None` and the client can fall back to the
    HTML preview.

    `base_url` is forwarded to WeasyPrint so relative image URLs in the
    template (e.g. `<img src="/static/logo.png">`) can be resolved against
    your CDN root. Absolute URLs (S3, CloudFront) work unchanged.

    Args:
        html: Fully-rendered HTML document (use `render_report_html` first).
        base_url: Optional base for resolving relative URLs.

    Returns:
        The PDF bytes. Typical size for a weekly report is 40-200 KB.

    Raises:
        PDFRendererUnavailable: if WeasyPrint or its native deps are missing.
    """
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PDFRendererUnavailable(
            "weasyprint is not installed; run `pip install weasyprint` and "
            "install native deps (libpango, libcairo) to enable PDF export."
        ) from exc

    # WeasyPrint is CPU-bound and synchronous; push the render into a worker
    # thread so the event loop keeps serving other requests while the PDF
    # generates (a 10-page report takes ~300ms single-threaded on an M1).
    import asyncio

    def _render() -> bytes:
        return HTML(string=html, base_url=base_url).write_pdf()

    return await asyncio.to_thread(_render)
