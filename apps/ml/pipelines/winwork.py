"""WINWORK — AI proposal generation pipeline.

LangGraph state machine:

    BenchmarkLookup → ScopeExpansion → FeeCalculation → ProposalDraft → ConfidenceScoring

The pipeline reads from the shared pgvector index for precedent match (past proposals
with the same project type) and returns a structured payload the WINWORK service
persists into the `proposals` table.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import UUID, uuid4

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

MODEL_NAME = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


# ---------- Graph state ----------

class PipelineState(TypedDict, total=False):
    # Inputs
    org_id: str
    project_type: str
    area_sqm: float
    floors: int
    location: str
    scope_items: list[str]
    client_brief: str
    discipline: str
    language: str

    # Intermediate
    benchmark: dict[str, Any] | None
    precedents: list[dict[str, Any]]
    scope_of_work: dict[str, Any] | None
    fee_breakdown: dict[str, Any] | None

    # Output
    title: str
    notes: str | None
    confidence: float


@dataclass
class PipelineDeps:
    session: AsyncSession
    ai_job_id: UUID = field(default_factory=uuid4)


# ---------- Nodes ----------

async def _node_benchmark_lookup(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """Pull the tightest matching fee benchmark band."""
    rows = (
        await deps.session.execute(
            text(
                """
                SELECT fee_percent_low, fee_percent_mid, fee_percent_high, source, province
                FROM fee_benchmarks
                WHERE discipline = :d AND project_type = :pt AND country_code = 'VN'
                ORDER BY COALESCE(area_sqm_min, 0) ASC
                """
            ),
            {"d": state["discipline"], "pt": state["project_type"]},
        )
    ).mappings().all()

    benchmark = None
    if rows:
        row = rows[0]
        benchmark = {
            "low": float(row["fee_percent_low"] or 0),
            "mid": float(row["fee_percent_mid"] or 0),
            "high": float(row["fee_percent_high"] or 0),
            "source": row["source"],
            "province": row["province"],
        }
    return {**state, "benchmark": benchmark}


async def _node_precedents(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    """Find up to 3 prior won proposals matching the project type."""
    rows = (
        await deps.session.execute(
            text(
                """
                SELECT p.id, p.title, p.scope_of_work, p.fee_breakdown, p.total_fee_vnd
                FROM proposals p
                JOIN projects proj ON proj.id = p.project_id
                WHERE p.organization_id = :org
                  AND p.status = 'won'
                  AND proj.type = :pt
                ORDER BY p.created_at DESC
                LIMIT 3
                """
            ),
            {"org": state["org_id"], "pt": state["project_type"]},
        )
    ).mappings().all()
    precedents = [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "scope_of_work": r["scope_of_work"],
            "fee_breakdown": r["fee_breakdown"],
            "total_fee_vnd": r["total_fee_vnd"],
        }
        for r in rows
    ]
    return {**state, "precedents": precedents}


def _llm() -> ChatAnthropic:
    return ChatAnthropic(model=MODEL_NAME, temperature=0.2, max_tokens=4096)


async def _node_scope_expansion(state: PipelineState, _deps: PipelineDeps) -> PipelineState:
    language = state.get("language", "vi")
    system = (
        "You are a senior architect in Vietnam drafting the scope of work for a client "
        "proposal. Expand terse scope items into detailed, phase-based deliverables. "
        "Use industry phases: Concept, Schematic, Design Development, Construction "
        "Documents, Construction Administration. Respond in "
        + ("Vietnamese" if language == "vi" else "English")
        + ". Return strict JSON."
    )
    user = json.dumps(
        {
            "project_type": state["project_type"],
            "area_sqm": state["area_sqm"],
            "floors": state["floors"],
            "location": state["location"],
            "discipline": state["discipline"],
            "scope_items": state["scope_items"],
            "client_brief": state["client_brief"],
            "precedents": [p["title"] for p in state.get("precedents", [])],
            "schema": {
                "items": [
                    {
                        "id": "string",
                        "phase": "string",
                        "title": "string",
                        "description": "string",
                        "deliverables": ["string"],
                        "hours_estimate": "number",
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    resp = await _llm().ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    try:
        scope = json.loads(_extract_json(resp.content))
    except Exception as exc:
        log.exception("Failed to parse scope JSON: %s", exc)
        scope = {"items": [{"id": "fallback", "phase": "Concept", "title": item, "deliverables": []} for item in state["scope_items"]]}
    return {**state, "scope_of_work": scope}


async def _node_fee_calculation(state: PipelineState, _deps: PipelineDeps) -> PipelineState:
    """Distribute fee across phases using benchmark mid-point + phase weights."""
    benchmark = state.get("benchmark") or {"low": 5.0, "mid": 7.5, "high": 10.0, "source": "default"}
    construction_cost_per_sqm = _construction_cost_per_sqm(state["project_type"])
    base_cost = int(state["area_sqm"] * construction_cost_per_sqm)
    total_fee = int(base_cost * benchmark["mid"] / 100)

    phase_weights = {
        "Concept": 0.10,
        "Schematic": 0.15,
        "Design Development": 0.25,
        "Construction Documents": 0.30,
        "Construction Administration": 0.20,
    }
    lines = []
    running_subtotal = 0
    for phase, weight in phase_weights.items():
        amount = int(total_fee * weight)
        running_subtotal += amount
        lines.append(
            {
                "phase": phase,
                "label": phase,
                "amount_vnd": amount,
                "percent": round(weight * 100, 1),
            }
        )
    vat = int(running_subtotal * 0.08)
    total = running_subtotal + vat

    return {
        **state,
        "fee_breakdown": {
            "lines": lines,
            "subtotal_vnd": running_subtotal,
            "vat_vnd": vat,
            "total_vnd": total,
        },
    }


def _construction_cost_per_sqm(project_type: str) -> int:
    return {
        "residential_villa": 12_000_000,
        "residential_apartment": 10_000_000,
        "commercial_office": 15_000_000,
        "commercial_retail": 14_000_000,
        "industrial": 8_000_000,
        "infrastructure": 20_000_000,
    }.get(project_type, 12_000_000)


async def _node_proposal_draft(state: PipelineState, _deps: PipelineDeps) -> PipelineState:
    language = state.get("language", "vi")
    system = (
        "You are drafting the cover letter and executive summary for a design proposal. "
        "Return JSON {\"title\": str, \"notes\": str}. Title is concise (<=80 chars). "
        "Notes is a 2-3 paragraph executive summary in "
        + ("Vietnamese." if language == "vi" else "English.")
    )
    user = json.dumps(
        {
            "project_type": state["project_type"],
            "area_sqm": state["area_sqm"],
            "floors": state["floors"],
            "location": state["location"],
            "client_brief": state["client_brief"],
            "scope_of_work": state["scope_of_work"],
            "fee_total_vnd": state["fee_breakdown"]["total_vnd"],
        },
        ensure_ascii=False,
    )
    resp = await _llm().ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    try:
        parsed = json.loads(_extract_json(resp.content))
    except Exception:
        parsed = {
            "title": f"Proposal — {state['project_type']} — {state['location']}",
            "notes": state["client_brief"],
        }
    return {**state, "title": parsed["title"], "notes": parsed.get("notes")}


async def _node_confidence(state: PipelineState, _deps: PipelineDeps) -> PipelineState:
    """Score confidence based on data coverage + precedent match."""
    score = 0.4
    if state.get("benchmark"):
        score += 0.25
    if state.get("precedents"):
        score += 0.15 if len(state["precedents"]) >= 2 else 0.08
    if state.get("scope_of_work") and len(state["scope_of_work"].get("items", [])) >= 3:
        score += 0.1
    if len(state["client_brief"]) >= 200:
        score += 0.05
    return {**state, "confidence": round(min(score, 0.95), 2)}


def _extract_json(content: str | list) -> str:
    """Anthropic may return a list of content blocks; collapse to text and strip fences."""
    if isinstance(content, list):
        content = "".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        # remove possible leading "json\n"
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    return text


# ---------- Graph assembly ----------

def _build_graph(deps: PipelineDeps):
    graph = StateGraph(PipelineState)

    async def wrap(node):
        async def runner(state):
            return await node(state, deps)
        return runner

    # LangGraph's add_node expects sync reference; we use closures above
    graph.add_node("benchmark", lambda s: _node_benchmark_lookup(s, deps))
    graph.add_node("precedents", lambda s: _node_precedents(s, deps))
    graph.add_node("scope", lambda s: _node_scope_expansion(s, deps))
    graph.add_node("fee", lambda s: _node_fee_calculation(s, deps))
    graph.add_node("draft", lambda s: _node_proposal_draft(s, deps))
    graph.add_node("confidence", lambda s: _node_confidence(s, deps))

    graph.set_entry_point("benchmark")
    graph.add_edge("benchmark", "precedents")
    graph.add_edge("precedents", "scope")
    graph.add_edge("scope", "fee")
    graph.add_edge("fee", "draft")
    graph.add_edge("draft", "confidence")
    graph.add_edge("confidence", END)
    return graph.compile()


# ---------- Entry point called by the router ----------

async def run_proposal_pipeline(
    *,
    session: AsyncSession,
    org_id: UUID,
    request: Any,  # schemas.winwork.ProposalGenerateRequest — keeps this module decoupled
) -> dict[str, Any]:
    deps = PipelineDeps(session=session)
    await _record_job_start(session, org_id, deps.ai_job_id, request)

    initial: PipelineState = {
        "org_id": str(org_id),
        "project_type": request.project_type,
        "area_sqm": float(request.area_sqm),
        "floors": int(request.floors),
        "location": request.location,
        "scope_items": list(request.scope_items),
        "client_brief": request.client_brief,
        "discipline": request.discipline,
        "language": request.language,
        "precedents": [],
    }

    try:
        graph = _build_graph(deps)
        final: PipelineState = await graph.ainvoke(initial)
    except Exception as exc:
        await _record_job_failure(session, deps.ai_job_id, str(exc))
        raise

    output = {
        "title": final["title"],
        "notes": final.get("notes"),
        "scope_of_work": final["scope_of_work"],
        "fee_breakdown": final["fee_breakdown"],
        "confidence": final.get("confidence", 0.5),
        "ai_job_id": deps.ai_job_id,
    }
    await _record_job_success(session, deps.ai_job_id, output)
    return output


async def _record_job_start(session: AsyncSession, org_id: UUID, job_id: UUID, request: Any) -> None:
    await session.execute(
        text(
            """
            INSERT INTO ai_jobs (id, organization_id, module, job_type, status, input, started_at, created_at)
            VALUES (:id, :org, 'winwork', 'proposal.generate', 'running', :input, :now, :now)
            """
        ),
        {
            "id": str(job_id),
            "org": str(org_id),
            "input": json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
            "now": datetime.now(timezone.utc),
        },
    )


async def _record_job_success(session: AsyncSession, job_id: UUID, output: dict) -> None:
    await session.execute(
        text(
            """
            UPDATE ai_jobs SET status = 'done', output = :out, completed_at = :now
            WHERE id = :id
            """
        ),
        {"id": str(job_id), "out": json.dumps({k: v for k, v in output.items() if k != "ai_job_id"}, default=str, ensure_ascii=False), "now": datetime.now(timezone.utc)},
    )


async def _record_job_failure(session: AsyncSession, job_id: UUID, error: str) -> None:
    await session.execute(
        text("UPDATE ai_jobs SET status = 'failed', error = :err, completed_at = :now WHERE id = :id"),
        {"id": str(job_id), "err": error, "now": datetime.now(timezone.utc)},
    )
