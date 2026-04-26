"""SchedulePilot AI pipelines.

Two pieces:

  1. **Critical-path computation (CPM)** — pure-Python forward+backward pass
     over (activities, dependencies). No LLM call. Returns the codes on the
     longest path together with per-activity slack and projected slip.

  2. **Top-N risk narration** — feeds the CPM output + observed actuals into
     Anthropic Claude to produce a short list of natural-language risks
     with mitigations. Wrapped in a structured JSON schema so the router
     can persist the rows verbatim.

The CPM core is unit-testable without any LLM credentials; the LLM call is
gated by `force=True` or "we have a baseline + at least one in-progress
activity" so empty schedules return a deterministic empty result.

Data shapes (raw dicts, mirroring `models.schedulepilot`):

    activity = {
        "id": UUID, "code": str, "name": str, "activity_type": str,
        "planned_start": date|None, "planned_finish": date|None,
        "planned_duration_days": int|None,
        "baseline_start": date|None, "baseline_finish": date|None,
        "actual_start": date|None, "actual_finish": date|None,
        "percent_complete": Decimal|float, "status": str,
    }
    dependency = {
        "predecessor_id": UUID, "successor_id": UUID,
        "relationship_type": "fs"|"ss"|"ff"|"sf", "lag_days": int,
    }
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict, deque
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_MODEL_VERSION = f"schedulepilot/v1@{_ANTHROPIC_MODEL}"


# =============================================================================
# CPM — pure functional core
# =============================================================================


def _duration_days(a: dict[str, Any]) -> int:
    """Best-effort duration. Prefer explicit value, else (finish-start)+1, else 0."""
    if a.get("planned_duration_days") is not None:
        return int(a["planned_duration_days"])
    s, f = a.get("planned_start"), a.get("planned_finish")
    if isinstance(s, date) and isinstance(f, date):
        return max(0, (f - s).days + 1)
    return 0


def _project_finish(a: dict[str, Any]) -> date | None:
    """Activity's projected finish. If complete, use actual_finish; else
    extrapolate from percent_complete linearly off planned_finish."""
    if a.get("actual_finish"):
        return a["actual_finish"]
    pf = a.get("planned_finish")
    if not isinstance(pf, date):
        return None
    pct = float(a.get("percent_complete") or 0)
    # Naive: a 50%-done activity that's already past planned finish projects to
    # planned + (planned_duration / 2). Sufficient for "behind schedule" cues.
    if pct >= 100 or pct <= 0:
        return pf
    dur = _duration_days(a)
    if dur == 0:
        return pf
    overshoot_days = round(dur * (1 - pct / 100))
    today = date.today()
    return max(pf, today + timedelta(days=overshoot_days))


def _slip_days(a: dict[str, Any]) -> int:
    """Days the activity is forecast to slip vs its baseline_finish (or
    planned_finish if no baseline). Negative = ahead of schedule."""
    proj = _project_finish(a)
    bench = a.get("baseline_finish") or a.get("planned_finish")
    if not isinstance(proj, date) or not isinstance(bench, date):
        return 0
    return (proj - bench).days


def compute_critical_path(
    activities: list[dict[str, Any]], dependencies: list[dict[str, Any]]
) -> dict[str, Any]:
    """Run a forward-pass CPM over the (activity, dep) graph.

    Implementation notes:
      - Only FS dependencies advance ES/EF; SS/FF/SF are honoured for graph
        topology but treated as FS for slack purposes (good-enough first cut).
      - Lag days widen the predecessor's effective EF.
      - Activities without dates contribute zero duration.

    Returns:
      {
        "critical_path_codes": [code, ...],   # topological order
        "overall_slip_days": int,             # max slip on the path
        "per_activity_slack": {id: float},    # for UI deep-dives
        "input_summary": {...},
      }
    """
    if not activities:
        return {
            "critical_path_codes": [],
            "overall_slip_days": 0,
            "per_activity_slack": {},
            "input_summary": {"activity_count": 0},
        }

    by_id: dict[str, dict[str, Any]] = {str(a["id"]): a for a in activities}
    successors: dict[str, list[tuple[str, int]]] = defaultdict(list)
    predecessors: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for d in dependencies:
        s = str(d["successor_id"])
        p = str(d["predecessor_id"])
        if s not in by_id or p not in by_id:
            # Orphan dep (e.g. activity deleted) — ignore.
            continue
        lag = int(d.get("lag_days") or 0)
        successors[p].append((s, lag))
        predecessors[s].append((p, lag))

    # Topological order via Kahn's algorithm; on cycle (shouldn't happen — the
    # router guards), bail out gracefully.
    indeg = {aid: len(predecessors[aid]) for aid in by_id}
    q: deque[str] = deque(aid for aid, n in indeg.items() if n == 0)
    topo: list[str] = []
    while q:
        cur = q.popleft()
        topo.append(cur)
        for s, _lag in successors[cur]:
            indeg[s] -= 1
            if indeg[s] == 0:
                q.append(s)
    if len(topo) != len(by_id):
        logger.warning(
            "schedulepilot.cpm: graph cycle detected (topo=%d, total=%d) — "
            "returning empty critical path",
            len(topo),
            len(by_id),
        )
        return {
            "critical_path_codes": [],
            "overall_slip_days": 0,
            "per_activity_slack": {},
            "input_summary": {"activity_count": len(by_id), "cycle_detected": True},
        }

    # Forward pass: ES/EF in days from project start (day 0).
    es: dict[str, int] = {}
    ef: dict[str, int] = {}
    for aid in topo:
        a = by_id[aid]
        dur = _duration_days(a)
        max_pred_ef = 0
        for p, lag in predecessors[aid]:
            max_pred_ef = max(max_pred_ef, ef[p] + lag)
        es[aid] = max_pred_ef
        ef[aid] = max_pred_ef + dur

    project_finish = max(ef.values()) if ef else 0

    # Backward pass: LF/LS so we can compute slack.
    lf: dict[str, int] = {aid: project_finish for aid in by_id}
    ls: dict[str, int] = {aid: project_finish for aid in by_id}
    for aid in reversed(topo):
        a = by_id[aid]
        dur = _duration_days(a)
        if successors[aid]:
            lf[aid] = min(ls[s] - lag for s, lag in successors[aid])
        ls[aid] = lf[aid] - dur

    slack = {aid: ls[aid] - es[aid] for aid in by_id}
    # Critical = slack <= 0 (allow tiny negatives from lag arithmetic).
    critical_ids = [aid for aid in topo if slack[aid] <= 0]
    critical_codes = [by_id[aid].get("code", "") for aid in critical_ids if by_id[aid].get("code")]

    overall_slip = max((_slip_days(by_id[aid]) for aid in critical_ids), default=0)

    in_progress = sum(1 for a in activities if a.get("status") == "in_progress")
    complete = sum(1 for a in activities if a.get("status") == "complete")
    behind = sum(1 for a in activities if _slip_days(a) > 0)

    return {
        "critical_path_codes": critical_codes,
        "overall_slip_days": int(overall_slip),
        "per_activity_slack": {aid: float(slack[aid]) for aid in by_id},
        "input_summary": {
            "activity_count": len(by_id),
            "dependency_count": len(dependencies),
            "in_progress": in_progress,
            "complete": complete,
            "behind_schedule": behind,
            "project_duration_days": project_finish,
        },
    }


# =============================================================================
# LLM risk narration
# =============================================================================


_RISK_PROMPT_SYSTEM = """\
You are a construction-schedule risk analyst. Given a JSON snapshot of a
project schedule (activities on the critical path, baselines vs actuals,
percent-complete values, dependencies), identify the 3-5 highest-impact
schedule risks. Each risk must reference a specific activity by code.

Respond with ONLY valid JSON matching this exact shape:

{{
  "top_risks": [
    {{
      "activity_id": "<UUID of the activity>",
      "code": "<activity code>",
      "name": "<activity name>",
      "expected_slip_days": <integer days>,
      "reason": "<one-sentence explanation citing concrete numbers>",
      "mitigation": "<one-sentence concrete mitigation>"
    }}
  ],
  "confidence_pct": <0-100 self-reported confidence>,
  "notes": "<optional one-sentence overall summary>"
}}

Be concrete: cite percent_complete, days_behind, or dependency-chain effects
in your `reason`. Do not invent activities — only reference codes from the
input. If the schedule has no critical issues, return an empty `top_risks`
array and a short note explaining why.
"""


def _serialise_for_llm(
    cpm: dict[str, Any],
    activities: list[dict[str, Any]],
) -> str:
    """Compact JSON view for the LLM prompt — drops fields it doesn't need."""
    cpm_set = set(cpm["critical_path_codes"])
    rows = []
    for a in activities:
        code = a.get("code", "")
        if not code:
            continue
        rows.append(
            {
                "id": str(a["id"]),
                "code": code,
                "name": a.get("name", ""),
                "type": a.get("activity_type", "task"),
                "status": a.get("status", "not_started"),
                "percent_complete": float(a.get("percent_complete") or 0),
                "planned_start": _iso_date(a.get("planned_start")),
                "planned_finish": _iso_date(a.get("planned_finish")),
                "baseline_finish": _iso_date(a.get("baseline_finish")),
                "actual_finish": _iso_date(a.get("actual_finish")),
                "slip_days": _slip_days(a),
                "on_critical_path": code in cpm_set,
            }
        )
    return json.dumps(
        {
            "critical_path_codes": cpm["critical_path_codes"],
            "overall_slip_days": cpm["overall_slip_days"],
            "input_summary": cpm["input_summary"],
            "activities": rows,
        },
        ensure_ascii=False,
    )


def _iso_date(d: Any) -> str | None:
    if isinstance(d, date):
        return d.isoformat()
    if isinstance(d, str):
        return d
    return None


async def _narrate_risks_llm(
    cpm: dict[str, Any], activities: list[dict[str, Any]]
) -> dict[str, Any]:
    """Best-effort LLM call. Returns `{top_risks, confidence_pct, notes}`.

    On any failure (no API key, model error, parse error) returns a
    deterministic empty narration so the router can still persist a row.
    """
    try:
        # Lazy import — keeps the CPM core importable in test environments
        # that don't install langchain-anthropic.
        from langchain_anthropic import ChatAnthropic
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError:
        logger.info("schedulepilot.risk: langchain not available; returning empty narration")
        return {"top_risks": [], "confidence_pct": None, "notes": None}

    if not os.getenv("ANTHROPIC_API_KEY"):
        return {
            "top_risks": [],
            "confidence_pct": None,
            "notes": "ANTHROPIC_API_KEY not configured; CPM-only assessment",
        }

    payload = _serialise_for_llm(cpm, activities)
    llm = ChatAnthropic(model=_ANTHROPIC_MODEL, temperature=0.1, max_tokens=2048)
    prompt = ChatPromptTemplate.from_messages(
        [("system", _RISK_PROMPT_SYSTEM), ("human", "{payload}")]
    )
    chain = prompt | llm | JsonOutputParser()
    try:
        out = await chain.ainvoke({"payload": payload})
    except Exception as exc:  # pragma: no cover — network / parse failures
        logger.warning("schedulepilot.risk: LLM call failed: %s", exc)
        return {
            "top_risks": [],
            "confidence_pct": None,
            "notes": f"LLM error: {exc}",
        }

    risks = out.get("top_risks") or []
    # Sanitise: ensure we never persist a risk that doesn't reference a real
    # activity_id (LLM hallucination guardrail).
    valid_ids = {str(a["id"]) for a in activities}
    cleaned = []
    for r in risks[:5]:  # cap at 5
        aid = str(r.get("activity_id", "") or "")
        if aid not in valid_ids:
            continue
        cleaned.append(
            {
                "activity_id": aid,
                "code": str(r.get("code", "") or ""),
                "name": str(r.get("name", "") or ""),
                "expected_slip_days": int(r.get("expected_slip_days") or 0),
                "reason": str(r.get("reason", "") or ""),
                "mitigation": str(r.get("mitigation", "") or ""),
            }
        )
    return {
        "top_risks": cleaned,
        "confidence_pct": (
            int(out["confidence_pct"])
            if isinstance(out.get("confidence_pct"), int | float)
            else None
        ),
        "notes": out.get("notes") or None,
    }


# =============================================================================
# Public entry point — used by the router
# =============================================================================


async def run_risk_assessment(
    activities: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """End-to-end: CPM + LLM narration. Returns a dict ready to persist.

    `force` currently only documents intent; the inline pipeline always runs
    (the router could later cache via a freshness check on the latest row).
    """
    cpm = compute_critical_path(activities, dependencies)

    has_progress = any(a.get("status") in ("in_progress", "complete") for a in activities)
    if not (force or has_progress) or not activities:
        # Skip the LLM when there's no progress — pure CPM is enough.
        narration: dict[str, Any] = {
            "top_risks": [],
            "confidence_pct": None,
            "notes": "No in-progress activity to assess yet",
        }
    else:
        narration = await _narrate_risks_llm(cpm, activities)

    return {
        "model_version": _MODEL_VERSION,
        "overall_slip_days": cpm["overall_slip_days"],
        "confidence_pct": narration.get("confidence_pct"),
        "critical_path_codes": cpm["critical_path_codes"],
        "top_risks": narration["top_risks"],
        "input_summary": cpm["input_summary"],
        "notes": narration.get("notes"),
    }


__all__ = [
    "compute_critical_path",
    "run_risk_assessment",
]
