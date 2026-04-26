"""ChangeOrder AI pipeline.

Two operations:

  1. **Extract candidates** — given an RFI's subject+description or a pasted
     email body, the LLM proposes 0–3 ChangeOrder candidates. Each
     candidate is a structured proposal: title, description, line items
     (with cost & schedule estimates), an overall confidence percentage,
     and a short rationale citing the source. The router persists each
     proposal to `change_order_candidates`.

  2. **Analyze impact** — given an existing CO + its line items, the LLM
     re-estimates `cost_impact_vnd` and `schedule_impact_days` based on
     what the line items actually contain. Useful when a user adds line
     items piecemeal and wants the parent rollup refreshed without doing
     the math themselves. Stores the analysis in `change_orders.ai_analysis`.

Both calls degrade gracefully without ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_EXTRACT_MODEL_VERSION = f"co-extract/v1@{_ANTHROPIC_MODEL}"
_ANALYZE_MODEL_VERSION = f"co-analyze/v1@{_ANTHROPIC_MODEL}"


_EXTRACT_PROMPT = """\
You are a construction project manager. Given an RFI question or an inbound
email about a project change, propose 0-3 CHANGE ORDER CANDIDATES.

Each candidate must include itemized line_items breaking out additions,
deletions, or substitutions, with a per-item cost (VND) and time (days)
estimate when reasonable.

Respond with ONLY JSON of this exact shape:

{{
  "candidates": [
    {{
      "title": "<short title>",
      "description": "<one paragraph explaining the change>",
      "line_items": [
        {{
          "description": "<itemized scope>",
          "line_kind": "add" | "delete" | "substitute",
          "spec_section": "<CSI section if known, else null>",
          "quantity": <number or null>,
          "unit": "<unit or null>",
          "unit_cost_vnd": <integer or null>,
          "cost_vnd": <integer or null>,
          "schedule_impact_days": <integer or null>
        }}
      ],
      "cost_impact_vnd_estimate": <integer or null>,
      "schedule_impact_days_estimate": <integer or null>,
      "confidence_pct": <0-100>,
      "rationale": "<1-2 sentences citing the source text>"
    }}
  ]
}}

If the source text doesn't justify any change, return `"candidates": []`.
"""


_ANALYZE_PROMPT = """\
You are a quantity surveyor. Given a change order's title + description and
its line items, return a refreshed cost & schedule rollup with assumptions.

Respond with ONLY JSON:

{{
  "cost_impact_vnd": <integer>,
  "schedule_impact_days": <integer>,
  "rollup_method": "<sum | parallel_max | mixed | other>",
  "assumptions": ["<assumption 1>", "<assumption 2>", ...],
  "confidence_pct": <0-100>,
  "summary": "<one-sentence executive summary>"
}}
"""


async def extract_candidates(
    *,
    text: str,
    source_kind: str = "manual_paste",
) -> list[dict[str, Any]]:
    """LLM extraction. Returns list of CandidateProposal-shaped dicts."""
    if not text or not text.strip():
        return []

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError:
        return _heuristic_extract(text)

    if not os.getenv("ANTHROPIC_API_KEY"):
        return _heuristic_extract(text)

    llm = ChatAnthropic(model=_ANTHROPIC_MODEL, temperature=0.1, max_tokens=2048)
    prompt = ChatPromptTemplate.from_messages(
        [("system", _EXTRACT_PROMPT), ("human", "Source ({sk}):\n{txt}")]
    )
    chain = prompt | llm | JsonOutputParser()
    try:
        out = await chain.ainvoke({"sk": source_kind, "txt": text})
    except Exception as exc:  # pragma: no cover — network / parse errors
        logger.warning("changeorder.extract: LLM call failed: %s", exc)
        return _heuristic_extract(text)

    candidates: list[dict[str, Any]] = []
    for c in (out.get("candidates") or [])[:3]:
        title = str(c.get("title", "") or "").strip()
        description = str(c.get("description", "") or "").strip()
        if not title or not description:
            continue
        line_items: list[dict[str, Any]] = []
        for li in (c.get("line_items") or [])[:20]:
            desc = str(li.get("description", "") or "").strip()
            if not desc:
                continue
            line_items.append(
                {
                    "description": desc,
                    "line_kind": _normalise_line_kind(li.get("line_kind")),
                    "spec_section": _opt_str(li.get("spec_section")),
                    "quantity": _opt_float(li.get("quantity")),
                    "unit": _opt_str(li.get("unit")),
                    "unit_cost_vnd": _opt_int(li.get("unit_cost_vnd")),
                    "cost_vnd": _opt_int(li.get("cost_vnd")),
                    "schedule_impact_days": _opt_int(li.get("schedule_impact_days")),
                }
            )
        candidates.append(
            {
                "title": title[:200],
                "description": description,
                "line_items": line_items,
                "cost_impact_vnd_estimate": _opt_int(c.get("cost_impact_vnd_estimate")),
                "schedule_impact_days_estimate": _opt_int(
                    c.get("schedule_impact_days_estimate")
                ),
                "confidence_pct": _opt_int(c.get("confidence_pct")),
                "rationale": (str(c.get("rationale", "") or "")[:480] or None),
            }
        )
    return candidates


def _heuristic_extract(text: str) -> list[dict[str, Any]]:
    """No-LLM fallback: a single low-confidence draft echoing the source."""
    snippet = text.strip()[:240]
    if not snippet:
        return []
    return [
        {
            "title": "Đề xuất thay đổi (chưa phân tích AI)",
            "description": snippet,
            "line_items": [],
            "cost_impact_vnd_estimate": None,
            "schedule_impact_days_estimate": None,
            "confidence_pct": 20,
            "rationale": "Heuristic fallback (no LLM credentials)",
        }
    ]


async def analyze_impact(
    *,
    title: str,
    description: str | None,
    line_items: list[dict[str, Any]],
    current_cost_vnd: int | None,
    current_schedule_days: int | None,
) -> dict[str, Any]:
    """Re-estimate the parent CO's cost & schedule rollup from its line items."""
    payload = json.dumps(
        {
            "title": title,
            "description": description,
            "current_cost_impact_vnd": current_cost_vnd,
            "current_schedule_impact_days": current_schedule_days,
            "line_items": line_items,
        },
        ensure_ascii=False,
    )

    sum_cost = sum(int(li.get("cost_vnd") or 0) for li in line_items)
    fallback = {
        "cost_impact_vnd": sum_cost or current_cost_vnd or 0,
        "schedule_impact_days": (
            max((int(li.get("schedule_impact_days") or 0) for li in line_items), default=0)
            or current_schedule_days
            or 0
        ),
        "rollup_method": "sum_cost+max_days" if line_items else "passthrough",
        "assumptions": ["Heuristic rollup (no LLM)"]
        if not os.getenv("ANTHROPIC_API_KEY")
        else [],
        "confidence_pct": 50,
        "summary": "Heuristic rollup",
        "model_version": _ANALYZE_MODEL_VERSION + "+fallback",
    }

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError:
        return fallback

    if not os.getenv("ANTHROPIC_API_KEY"):
        return fallback

    llm = ChatAnthropic(model=_ANTHROPIC_MODEL, temperature=0.1, max_tokens=512)
    prompt = ChatPromptTemplate.from_messages(
        [("system", _ANALYZE_PROMPT), ("human", "{payload}")]
    )
    chain = prompt | llm | JsonOutputParser()
    try:
        out = await chain.ainvoke({"payload": payload})
    except Exception as exc:  # pragma: no cover — network / parse errors
        logger.warning("changeorder.analyze: LLM call failed: %s", exc)
        return fallback

    return {
        "cost_impact_vnd": _opt_int(out.get("cost_impact_vnd")) or 0,
        "schedule_impact_days": _opt_int(out.get("schedule_impact_days")) or 0,
        "rollup_method": str(out.get("rollup_method", "") or "")[:60] or "unknown",
        "assumptions": [
            str(a)[:240] for a in (out.get("assumptions") or [])[:6] if a
        ],
        "confidence_pct": _opt_int(out.get("confidence_pct")),
        "summary": str(out.get("summary", "") or "")[:480],
        "model_version": _ANALYZE_MODEL_VERSION,
    }


# ---------- Coercion helpers ----------


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _opt_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalise_line_kind(v: Any) -> str:
    s = str(v or "add").strip().lower()
    return s if s in ("add", "delete", "substitute") else "add"


__all__ = ["extract_candidates", "analyze_impact"]
