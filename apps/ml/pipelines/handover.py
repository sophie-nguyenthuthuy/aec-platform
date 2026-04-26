"""HANDOVER AI pipelines.

Three operations:
  1. Extract equipment specs from MEP drawings → generate O&M manual
     (equipment list + maintenance schedule).
  2. Extract warranty items from procurement contracts.
  3. Seed closeout checklist from project scope.

Each is a LangGraph-shaped pipeline around Anthropic Claude with structured
JSON output. File contents are loaded from the shared `files` table (S3 keys)
via the `load_text` helper, which today calls the backing storage; stubbed to
read `extracted_metadata.text` when a worker has already done OCR.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field
from schemas.handover import (
    CloseoutCategory,
    CloseoutItemCreate,
    Discipline,
    EquipmentSpec,
    MaintenanceTask,
    WarrantyItemCreate,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_MAX_DOC_CHARS = 60_000


def _llm(temperature: float = 0.1) -> ChatAnthropic:
    return ChatAnthropic(model=_ANTHROPIC_MODEL, temperature=temperature, max_tokens=4096)


# ---------- File loading ----------


async def _load_text(db: AsyncSession, file_id: UUID) -> tuple[str, str]:
    """Return (filename, extracted_text). Assumes an earlier worker populated
    `extracted_metadata.text`; if absent, returns empty text and the pipeline
    reports low confidence rather than hallucinating.
    """
    row = (
        (
            await db.execute(
                text("SELECT name, extracted_metadata FROM files WHERE id = :id"),
                {"id": str(file_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return ("", "")
    metadata = row.get("extracted_metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    txt = metadata.get("text", "") if isinstance(metadata, dict) else ""
    return (row["name"], (txt or "")[:_MAX_DOC_CHARS])


async def _load_many(db: AsyncSession, file_ids: list[UUID]) -> list[tuple[str, str]]:
    return [await _load_text(db, fid) for fid in file_ids]


def _format_documents(docs: list[tuple[str, str]]) -> str:
    blocks: list[str] = []
    for i, (name, content) in enumerate(docs):
        label = name or f"file-{i}"
        blocks.append(f"=== DOCUMENT [{i}] {label} ===\n{content or '(no text extracted)'}")
    return "\n\n".join(blocks) or "(no documents)"


# ---------- O&M manual pipeline ----------

_OM_EQUIPMENT_SYSTEM = """You are HANDOVER's O&M manual generator for building services.

Given one or more MEP drawing / specification documents, extract every distinct
piece of installed equipment. For each item, produce:
  - tag           (from the drawing, e.g. "AHU-01", "CHW-P-02", "PNL-L1A")
  - name          (human-readable, e.g. "Air Handling Unit AHU-01")
  - discipline    (one of: mep, electrical, plumbing, hvac, fire)
  - manufacturer  (null if not stated)
  - model         (null if not stated)
  - serial        (null if not stated)
  - location      (room / level / grid reference, null if not stated)
  - capacity      (e.g. "10,000 CMH / 30 kW", null if not stated)
  - notes         (anything else relevant; null if none)

Do NOT invent values. Leave fields null when the document doesn't say.

Return JSON: {{"equipment": [...]}} — nothing else.
"""

_OM_SCHEDULE_SYSTEM = """You are HANDOVER generating a preventive-maintenance schedule.

Given a list of equipment (tag, name, discipline, capacity), produce a maintenance
schedule following ASHRAE / BSRIA / Vietnam MOC standard practice. For each
equipment, include the tasks the owner/operator must perform. Each task:
  - equipment_tag   (must match one provided)
  - task            (short imperative: "Inspect filter condition", "Check belt tension")
  - frequency       (one of: "weekly", "monthly", "quarterly", "semi_annually", "yearly")
  - duration_minutes (integer estimate, null if highly variable)
  - tools           (array of strings, may be empty)
  - safety          (PPE / LOTO notes, null if none)

Produce a reasonable but conservative schedule — prefer fewer, higher-quality
tasks over long speculative lists.

Return JSON: {{"maintenance_schedule": [...]}} — nothing else.
"""


class _OmState(BaseModel):
    project_id: UUID
    discipline: Discipline
    documents: list[tuple[str, str]] = Field(default_factory=list)
    equipment: list[EquipmentSpec] = Field(default_factory=list)
    maintenance_schedule: list[MaintenanceTask] = Field(default_factory=list)


async def generate_om_manual(
    db: AsyncSession,
    project_id: UUID,
    discipline: Discipline,
    source_file_ids: list[UUID],
) -> tuple[list[EquipmentSpec], list[MaintenanceTask]]:
    """Run the two-stage O&M pipeline. Returns (equipment, maintenance_schedule)."""

    async def node_load(state: _OmState) -> _OmState:
        state.documents = await _load_many(db, source_file_ids)
        return state

    async def node_equipment(state: _OmState) -> _OmState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _OM_EQUIPMENT_SYSTEM),
                ("human", "Discipline: {discipline}\n\nDocuments:\n{docs}\n\nReturn JSON only."),
            ]
        )
        chain = prompt | _llm(temperature=0.0) | JsonOutputParser()
        try:
            raw = await chain.ainvoke(
                {
                    "discipline": state.discipline.value,
                    "docs": _format_documents(state.documents),
                }
            )
        except Exception:
            return state
        for item in raw.get("equipment", []):
            try:
                state.equipment.append(
                    EquipmentSpec(
                        tag=str(item.get("tag") or "").strip(),
                        name=str(item.get("name") or "").strip(),
                        discipline=Discipline(item.get("discipline") or state.discipline.value),
                        manufacturer=item.get("manufacturer"),
                        model=item.get("model"),
                        serial=item.get("serial"),
                        location=item.get("location"),
                        capacity=item.get("capacity"),
                        notes=item.get("notes"),
                    )
                )
            except ValueError:
                continue
        state.equipment = [e for e in state.equipment if e.tag and e.name]
        return state

    async def node_schedule(state: _OmState) -> _OmState:
        if not state.equipment:
            return state
        equipment_summary = [
            {"tag": e.tag, "name": e.name, "discipline": e.discipline.value, "capacity": e.capacity}
            for e in state.equipment
        ]
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _OM_SCHEDULE_SYSTEM),
                ("human", "Equipment:\n{equipment}\n\nReturn JSON only."),
            ]
        )
        chain = prompt | _llm(temperature=0.1) | JsonOutputParser()
        try:
            raw = await chain.ainvoke(
                {
                    "equipment": json.dumps(equipment_summary, ensure_ascii=False, indent=2),
                }
            )
        except Exception:
            return state
        valid_tags = {e.tag for e in state.equipment}
        for task in raw.get("maintenance_schedule", []):
            tag = str(task.get("equipment_tag") or "").strip()
            if tag not in valid_tags:
                continue
            duration = task.get("duration_minutes")
            try:
                state.maintenance_schedule.append(
                    MaintenanceTask(
                        equipment_tag=tag,
                        task=str(task.get("task") or "").strip(),
                        frequency=str(task.get("frequency") or "yearly"),
                        duration_minutes=int(duration)
                        if isinstance(duration, int | float)
                        else None,
                        tools=[str(t) for t in (task.get("tools") or [])],
                        safety=task.get("safety"),
                    )
                )
            except (TypeError, ValueError):
                continue
        return state

    graph = StateGraph(_OmState)
    graph.add_node("load", node_load)
    graph.add_node("equipment", node_equipment)
    graph.add_node("schedule", node_schedule)
    graph.set_entry_point("load")
    graph.add_edge("load", "equipment")
    graph.add_edge("equipment", "schedule")
    graph.add_edge("schedule", END)
    app = graph.compile()

    initial = _OmState(project_id=project_id, discipline=discipline)
    final = await app.ainvoke(initial)
    result = final if isinstance(final, _OmState) else _OmState(**final)
    return (result.equipment, result.maintenance_schedule)


# ---------- Warranty extraction ----------

_WARRANTY_SYSTEM = """You are HANDOVER extracting warranty items from a construction contract.

From the contract text, list every item/equipment/system that carries a warranty.
For each item, return:
  - item_name              (e.g. "Waterproofing — basement slab")
  - category               (one of: equipment, finishes, mep, structure, envelope, landscape, other)
  - vendor                 (company providing the warranty, null if not stated)
  - warranty_period_months (integer; convert years to months)
  - start_date             (ISO YYYY-MM-DD if stated; null otherwise — usually starts at practical completion)
  - coverage               (brief summary of what's covered, 1-2 sentences)
  - claim_contact          (object with any of: name, phone, email — null fields omitted)

If a document contains no warranty terms, return {{"items": []}}.

Do NOT invent dates or periods. Use null when not stated. Return JSON only:
{{"items": [...]}}
"""


async def extract_warranty_items(
    db: AsyncSession,
    project_id: UUID,
    package_id: UUID | None,
    contract_file_ids: list[UUID],
) -> list[WarrantyItemCreate]:
    documents = await _load_many(db, contract_file_ids)
    if not documents or all(not content for _, content in documents):
        return []

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _WARRANTY_SYSTEM),
            ("human", "Contract documents:\n{docs}\n\nReturn JSON only."),
        ]
    )
    chain = prompt | _llm(temperature=0.0) | JsonOutputParser()
    try:
        raw = await chain.ainvoke({"docs": _format_documents(documents)})
    except Exception:
        return []

    results: list[WarrantyItemCreate] = []
    for i, item in enumerate(raw.get("items", [])):
        name = str(item.get("item_name") or "").strip()
        if not name:
            continue

        period = item.get("warranty_period_months")
        start = _parse_iso_date(item.get("start_date"))
        expiry: date | None = None
        if isinstance(period, int | float) and start:
            expiry = start + timedelta(days=int(period) * 30)

        contract_file_id = contract_file_ids[i % len(contract_file_ids)]

        results.append(
            WarrantyItemCreate(
                project_id=project_id,
                package_id=package_id,
                item_name=name,
                category=item.get("category"),
                vendor=item.get("vendor"),
                contract_file_id=contract_file_id,
                warranty_period_months=int(period) if isinstance(period, int | float) else None,
                start_date=start,
                expiry_date=expiry,
                coverage=item.get("coverage"),
                claim_contact=item.get("claim_contact") or {},
            )
        )
    return results


def _parse_iso_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------- Closeout checklist seeding ----------

_DEFAULT_CHECKLIST: list[tuple[CloseoutCategory, str, str, bool]] = [
    (
        CloseoutCategory.drawings,
        "As-built drawings — architecture",
        "Signed, dated, full set PDF + DWG.",
        True,
    ),
    (
        CloseoutCategory.drawings,
        "As-built drawings — structure",
        "Include final structural calc report.",
        True,
    ),
    (
        CloseoutCategory.drawings,
        "As-built drawings — MEP",
        "All disciplines merged, with equipment tags.",
        True,
    ),
    (CloseoutCategory.documents, "Project scope summary", "Final scope vs. delivered.", True),
    (
        CloseoutCategory.documents,
        "Commissioning report",
        "All systems tested and signed off.",
        True,
    ),
    (
        CloseoutCategory.certificates,
        "Occupancy / completion certificate",
        "From local authority.",
        True,
    ),
    (
        CloseoutCategory.certificates,
        "Fire safety approval (PCCC)",
        "Final inspection certificate.",
        True,
    ),
    (
        CloseoutCategory.certificates,
        "Electrical safety certificate",
        "From utility / licensed engineer.",
        True,
    ),
    (
        CloseoutCategory.warranties,
        "Consolidated warranty register",
        "All vendor warranties listed + expiry.",
        True,
    ),
    (CloseoutCategory.manuals, "O&M manuals — MEP", "Equipment list + maintenance schedule.", True),
    (
        CloseoutCategory.manuals,
        "Operating instructions for building systems",
        "Elevators, fire panel, BMS, etc.",
        True,
    ),
    (
        CloseoutCategory.permits,
        "Environmental compliance records",
        "EIA sign-off, waste disposal.",
        False,
    ),
    (
        CloseoutCategory.testing,
        "Test reports — water, fire, electrical",
        "Pressure tests, hi-pot, etc.",
        True,
    ),
    (CloseoutCategory.testing, "Commissioning data sheets", "Air balance, system start-up.", False),
    (
        CloseoutCategory.other,
        "Keys + access register",
        "Physical + digital access handed over.",
        True,
    ),
    (
        CloseoutCategory.other,
        "Defects list + rectification plan",
        "Outstanding snags with owners.",
        True,
    ),
]


async def seed_closeout_items(
    db: AsyncSession,
    organization_id: UUID,
    package_id: UUID,
    scope_summary: dict[str, Any] | None = None,
) -> list[CloseoutItemCreate]:
    """Seed closeout items. Today uses a static list tailored by scope flags;
    swap for an LLM call if scope is non-standard."""
    scope = scope_summary or {}
    items: list[CloseoutItemCreate] = []
    for sort_order, (category, title, description, required) in enumerate(_DEFAULT_CHECKLIST):
        if category == CloseoutCategory.permits and not scope.get("has_environmental_scope", True):
            continue
        items.append(
            CloseoutItemCreate(
                category=category,
                title=title,
                description=description,
                required=required,
                sort_order=sort_order,
            )
        )
    now = datetime.now(UTC)
    rows = [
        {
            "id": str(uuid4()),
            "organization_id": str(organization_id),
            "package_id": str(package_id),
            "category": item.category.value,
            "title": item.title,
            "description": item.description,
            "required": item.required,
            "sort_order": item.sort_order,
            "updated_at": now,
        }
        for item in items
    ]
    if rows:
        await db.execute(
            text(
                """
                INSERT INTO closeout_items
                  (id, organization_id, package_id, category, title, description,
                   required, sort_order, updated_at)
                VALUES
                  (CAST(:id AS uuid), CAST(:organization_id AS uuid), CAST(:package_id AS uuid),
                   :category, :title, :description, :required, :sort_order, :updated_at)
                """
            ),
            rows,
        )
    return items
