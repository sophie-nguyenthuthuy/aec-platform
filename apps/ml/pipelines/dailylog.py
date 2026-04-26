"""DailyLog AI pipeline.

Two operations:

  1. **Observation extraction** — given the daily-log's narrative + structured
     manpower/equipment/weather context, the LLM emits a list of typed
     observations (risk / issue / delay / milestone / safety / quality /
     productivity). Each is severity-graded and references concrete cues
     from the input. Useful for "I wrote a paragraph; surface the actual
     risks".

  2. **Pattern aggregation** — pure-Python rollup over a project's daily
     logs in a date range. Computes average headcount, weather anomaly
     days (rain >= 10mm, etc.), and the most common observation kinds.
     No LLM call — this is a SQL-backed analysis fed to the UI.

The extraction is gated by `force=True` OR a non-trivial narrative so we
don't waste tokens on empty drafts.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import date
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

_ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_EXTRACT_MODEL_VERSION = f"dailylog-extract/v1@{_ANTHROPIC_MODEL}"


_EXTRACT_PROMPT_SYSTEM = """\
You are a construction-site analyst extracting structured observations from a
daily field report. Read the narrative + manpower + equipment + weather and
return a list of 0-8 OBSERVATIONS. Each must reference concrete cues from
the input — never invent details that aren't there.

Respond with ONLY valid JSON of this exact shape:

{{
  "observations": [
    {{
      "kind": "risk" | "issue" | "delay" | "milestone" | "safety" | "quality" | "productivity",
      "severity": "low" | "medium" | "high" | "critical",
      "description": "<one concise sentence in Vietnamese>",
      "rationale": "<short justification citing the specific input fact>"
    }}
  ]
}}

Severity guide:
  - critical: imminent danger to life, blocks > 50% of crew, or schedule slip > 1 week
  - high: major rework / partial site shutdown / one-person injury
  - medium: typical issue or delay
  - low: routine observation worth tracking

If the report is empty or trivial, return `"observations": []`.
"""


async def extract_observations(
    *,
    narrative: str | None,
    work_completed: str | None,
    issues_observed: str | None,
    weather: dict[str, Any],
    manpower: list[dict[str, Any]],
    equipment: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """LLM extraction. Defensive: missing keys / errors → empty list."""
    text_blob = "\n".join(
        filter(
            None,
            [
                f"Narrative: {narrative}" if narrative else None,
                f"Work completed: {work_completed}" if work_completed else None,
                f"Issues observed: {issues_observed}" if issues_observed else None,
            ],
        )
    ).strip()
    if not text_blob:
        return []

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError:
        return _heuristic_extract(narrative or "", issues_observed or "")

    if not os.getenv("ANTHROPIC_API_KEY"):
        return _heuristic_extract(narrative or "", issues_observed or "")

    payload = json.dumps(
        {
            "weather": weather,
            "manpower": manpower,
            "equipment": equipment,
            "text": text_blob,
        },
        ensure_ascii=False,
    )
    llm = ChatAnthropic(model=_ANTHROPIC_MODEL, temperature=0.1, max_tokens=1024)
    prompt = ChatPromptTemplate.from_messages(
        [("system", _EXTRACT_PROMPT_SYSTEM), ("human", "{payload}")]
    )
    chain = prompt | llm | JsonOutputParser()
    try:
        out = await chain.ainvoke({"payload": payload})
    except Exception as exc:  # pragma: no cover — network / parse errors
        logger.warning("dailylog.extract: LLM call failed: %s", exc)
        return _heuristic_extract(narrative or "", issues_observed or "")

    cleaned: list[dict[str, Any]] = []
    valid_kinds = {
        "risk",
        "issue",
        "delay",
        "milestone",
        "safety",
        "quality",
        "productivity",
    }
    valid_sev = {"low", "medium", "high", "critical"}
    for item in (out.get("observations") or [])[:8]:
        kind = str(item.get("kind", "") or "").strip()
        sev = str(item.get("severity", "") or "").strip()
        desc = str(item.get("description", "") or "").strip()
        if kind not in valid_kinds or sev not in valid_sev or not desc:
            continue
        cleaned.append(
            {
                "kind": kind,
                "severity": sev,
                "description": desc,
                "source": "llm_extracted",
                "rationale": str(item.get("rationale", "") or "")[:240],
            }
        )
    return cleaned


def _heuristic_extract(narrative: str, issues: str) -> list[dict[str, Any]]:
    """No-LLM fallback: surface a single observation echoing the issues field
    so the UI shows *something* without LLM credentials configured."""
    text = (issues or narrative or "").strip()
    if not text:
        return []
    severity = (
        "high"
        if any(
            w in text.lower()
            for w in ("emergency", "injury", "stop", "halted", "khẩn", "ngưng", "tai nạn")
        )
        else "medium"
    )
    return [
        {
            "kind": "issue",
            "severity": severity,
            "description": text[:200],
            "source": "llm_extracted",
            "rationale": "Heuristic fallback (no LLM credentials)",
        }
    ]


# =============================================================================
# Pattern aggregation
# =============================================================================


def aggregate_patterns(
    *,
    project_id: UUID,
    date_from: date,
    date_to: date,
    log_rows: list[dict[str, Any]],
    manpower_rows: list[dict[str, Any]],
    observation_rows: list[dict[str, Any]],
    weather_anomaly_threshold_mm: float = 10.0,
) -> dict[str, Any]:
    """Pure-Python rollup. Inputs are denormalised query results from the
    router; output mirrors the PatternsResponse schema."""
    days_observed = len(log_rows)
    avg_headcount = sum(int(r.get("headcount") or 0) for r in manpower_rows) / max(days_observed, 1)

    issue_count_by_kind = Counter(r.get("kind", "") for r in observation_rows)
    severity_counts = Counter(r.get("severity", "") for r in observation_rows)

    weather_anomaly_days = []
    for log in log_rows:
        w = log.get("weather") or {}
        rain = float(w.get("precipitation_mm") or 0)
        if rain >= weather_anomaly_threshold_mm:
            weather_anomaly_days.append(
                {
                    "log_date": log["log_date"],
                    "precipitation_mm": rain,
                    "conditions": w.get("conditions"),
                }
            )

    desc_counter = Counter(
        (r.get("description") or "")[:80] for r in observation_rows if r.get("description")
    )
    most_common = [{"description": d, "count": n} for d, n in desc_counter.most_common(5)]

    return {
        "project_id": project_id,
        "date_from": date_from,
        "date_to": date_to,
        "days_observed": days_observed,
        "avg_headcount": round(avg_headcount, 2),
        "issue_count_by_kind": dict(issue_count_by_kind),
        "severity_counts": dict(severity_counts),
        "weather_anomaly_days": weather_anomaly_days,
        "most_common_observations": most_common,
    }


__all__ = ["aggregate_patterns", "extract_observations"]
