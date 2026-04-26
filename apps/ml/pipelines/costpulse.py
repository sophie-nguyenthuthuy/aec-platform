"""CostPulse AI pipelines — BOQ estimation from brief and from drawings.

Graph topology (LangGraph):

  from-brief:
    project_params → brief_boq_generator → price_lookup → assembler → persist

  from-drawings:
    drawing_file_ids → drawing_parser (GPT-4o vision, per-page) →
        quantity_takeoff → material_mapper → price_lookup → assembler → persist
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import date
from decimal import Decimal
from typing import Any, TypedDict
from uuid import UUID, uuid4

from core.config import get_settings
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from models.costpulse import BoqItem, Estimate, MaterialPrice
from schemas.costpulse import (
    AiEstimateResult,
    BoqItemOut,
    BoqItemSource,
    EstimateConfidence,
    EstimateFromBriefRequest,
    EstimateFromDrawingsRequest,
    EstimateMethod,
    EstimateStatus,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
_settings = get_settings()


# Standard BOQ hierarchy
BOQ_SECTIONS: list[tuple[str, str]] = [
    ("01", "Preliminary & Temporary Works"),
    ("02", "Site Preparation"),
    ("03", "Foundation Works"),
    ("04", "Structural Works"),
    ("05", "Masonry"),
    ("06", "Finishes"),
    ("07", "MEP (allowance)"),
    ("08", "External Works"),
]

# Waste factors per material category
WASTE_FACTOR: dict[str, Decimal] = {
    "concrete": Decimal("1.03"),
    "steel": Decimal("1.05"),
    "masonry": Decimal("1.07"),
    "finishing": Decimal("1.10"),
    "mep": Decimal("1.05"),
    "timber": Decimal("1.10"),
}


# Dev-only bypass: when AEC_PIPELINE_DEV_STUB=1 (and AEC_ENV != "production"),
# swap OpenAI for a canned-response shim so the graph runs end-to-end without
# OPENAI_API_KEY. Mirrors apps/ml/pipelines/winwork.py — single env var gates
# every pipeline.
_AEC_ENV = os.getenv("AEC_ENV", "development")
_REQUEST_STUB = os.getenv("AEC_PIPELINE_DEV_STUB") == "1"
PIPELINE_DEV_STUB = _REQUEST_STUB and _AEC_ENV != "production"
if _REQUEST_STUB and not PIPELINE_DEV_STUB:
    logger.error(
        "AEC_PIPELINE_DEV_STUB=1 ignored: refusing to stub LLM calls when AEC_ENV=%s",
        _AEC_ENV,
    )


class _StubLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubLLM:
    """Offline shim used when AEC_PIPELINE_DEV_STUB=1.

    Returns a 3-element BOQ skeleton matching brief_generator_node's expected
    JSON contract (elements with material_code/quantity/unit/category). Only
    enough data to make the round-trip concrete; pricing and assembly happen
    downstream against the real material_prices table.
    """

    async def ainvoke(self, _messages: list[Any]) -> _StubLLMResponse:
        payload = {
            "elements": [
                {
                    "material_code": "CONC_C30",
                    "quantity": 120.0,
                    "unit": "m3",
                    "category": "concrete",
                    "section_code": "04",
                    "description": "[DEV STUB] Bê tông cấu kiện C30",
                },
                {
                    "material_code": "STEEL_REBAR",
                    "quantity": 8500.0,
                    "unit": "kg",
                    "category": "steel",
                    "section_code": "04",
                    "description": "[DEV STUB] Thép cốt bê tông",
                },
                {
                    "material_code": "PAINT_EMULSION",
                    "quantity": 1800.0,
                    "unit": "m2",
                    "category": "finishing",
                    "section_code": "06",
                    "description": "[DEV STUB] Sơn nội thất",
                },
            ]
        }
        return _StubLLMResponse(json.dumps(payload, ensure_ascii=False))


def _vision_llm() -> ChatOpenAI | _StubLLM:
    if PIPELINE_DEV_STUB:
        logger.warning("CostPulse vision pipeline running with AEC_PIPELINE_DEV_STUB=1")
        return _StubLLM()
    return ChatOpenAI(
        model="gpt-4o",
        api_key=_settings.openai_api_key,
        temperature=0,
        max_tokens=4096,
    )


def _text_llm() -> ChatOpenAI | _StubLLM:
    if PIPELINE_DEV_STUB:
        logger.warning("CostPulse text pipeline running with AEC_PIPELINE_DEV_STUB=1")
        return _StubLLM()
    return ChatOpenAI(
        model="gpt-4o-mini",
        api_key=_settings.openai_api_key,
        temperature=0,
    )


# ============================================================
# Shared state types
# ============================================================


class PriceLookupState(TypedDict, total=False):
    elements: list[dict[str, Any]]  # [{material_code, quantity, unit, description, category}]
    province: str
    priced: list[dict[str, Any]]
    missing: list[str]


# ============================================================
# Shared nodes
# ============================================================


async def price_lookup_node(state: PriceLookupState, *, db: AsyncSession) -> PriceLookupState:
    """Resolve unit prices from material_prices (latest effective_date by province)."""
    elements = state.get("elements", [])
    province = state.get("province")
    priced: list[dict[str, Any]] = []
    missing: list[str] = []

    codes = sorted({e["material_code"] for e in elements if e.get("material_code")})
    if not codes:
        return {**state, "priced": elements, "missing": missing}

    today = date.today()
    stmt = (
        select(MaterialPrice)
        .where(
            MaterialPrice.material_code.in_(codes),
            MaterialPrice.effective_date <= today,
        )
        .order_by(MaterialPrice.effective_date.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()

    # Prefer province match, fall back to national average
    best: dict[str, MaterialPrice] = {}
    for r in rows:
        key = r.material_code
        if key in best:
            current = best[key]
            # province exact match beats everything
            if province and r.province == province and current.province != province:
                best[key] = r
            continue
        if province and r.province and r.province != province:
            # hold it; a province-match may come later — but rows are sorted by date, not province
            best[key] = r
        else:
            best[key] = r

    for el in elements:
        code = el.get("material_code")
        if not code or code not in best:
            missing.append(code or el.get("description", "unknown"))
            priced.append({**el, "unit_price_vnd": None, "total_price_vnd": None})
            continue
        price_row = best[code]
        unit_price = Decimal(price_row.price_vnd)
        waste = WASTE_FACTOR.get(price_row.category or "", Decimal("1.0"))
        qty = Decimal(str(el.get("quantity") or 0)) * waste
        total = unit_price * qty
        priced.append(
            {
                **el,
                "name": price_row.name,
                "unit": price_row.unit,
                "category": price_row.category,
                "quantity": float(qty),
                "unit_price_vnd": float(unit_price),
                "total_price_vnd": float(total),
            }
        )

    return {**state, "priced": priced, "missing": missing}


# ============================================================
# from-brief pipeline
# ============================================================


class BriefState(TypedDict, total=False):
    payload: dict[str, Any]
    elements: list[dict[str, Any]]
    province: str
    priced: list[dict[str, Any]]
    missing: list[str]


BRIEF_SYSTEM = """You are an expert construction cost estimator in Vietnam.

Given project parameters, output rough quantity estimates for standard material codes.
Use realistic per-m² factors for the given project type and quality tier.

Output strictly as JSON with shape:
{
  "elements": [
    {
      "section_code": "03",
      "description": "Concrete C30 for foundation",
      "material_code": "CONC_C30",
      "category": "concrete",
      "quantity": 120.5,
      "unit": "m3"
    }
  ]
}

Use these material codes: CONC_C25, CONC_C30, CONC_C40, REBAR_CB300, REBAR_CB500,
STEEL_STRUCT, BRICK_RED, BRICK_AAC, CEMENT_PCB40, SAND_FINE, GRAVEL_1x2,
TILE_CERAMIC, PAINT_EMULSION, PAINT_EXTERIOR, PLASTER, WATERPROOF_MEMBRANE,
ELECTRICAL_ALLOWANCE, PLUMBING_ALLOWANCE, HVAC_ALLOWANCE.

Section codes: 01 prelim, 02 site prep, 03 foundation, 04 structural, 05 masonry,
06 finishes, 07 MEP, 08 external.
"""


async def brief_generator_node(state: BriefState) -> BriefState:
    llm = _text_llm()
    p = state["payload"]
    user = (
        f"Project: {p['project_type']}, {p['area_sqm']} m², {p['floors']} floors, "
        f"{p['province']}, quality={p['quality_tier']}, structure={p['structure_type']}. "
        f"Notes: {p.get('notes') or '(none)'}. Return ONLY JSON."
    )
    resp = await llm.ainvoke([SystemMessage(content=BRIEF_SYSTEM), HumanMessage(content=user)])
    try:
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        parsed = json.loads(_strip_fences(content))
        elements = parsed.get("elements", [])
    except Exception as exc:
        logger.warning("brief_generator parse failed: %s", exc)
        elements = []
    return {**state, "elements": elements, "province": p["province"]}


def _build_brief_graph(db: AsyncSession):
    # LangGraph inspects the node callable — wrapping an async fn in a sync
    # lambda yields a coroutine, which the runtime tries to treat as a dict
    # ("Expected dict, got <coroutine object ...>"). Use async closures.
    async def _price(state: BriefState) -> BriefState:
        return await price_lookup_node(state, db=db)

    graph: StateGraph = StateGraph(BriefState)
    graph.add_node("generate", brief_generator_node)
    graph.add_node("price", _price)
    graph.set_entry_point("generate")
    graph.add_edge("generate", "price")
    graph.add_edge("price", END)
    return graph.compile()


async def estimate_from_brief(
    *,
    db: AsyncSession,
    organization_id: UUID,
    created_by: UUID,
    payload: EstimateFromBriefRequest,
) -> AiEstimateResult:
    app = _build_brief_graph(db)
    out: BriefState = await app.ainvoke({"payload": payload.model_dump(mode="json")})

    return await _assemble_and_persist(
        db=db,
        organization_id=organization_id,
        created_by=created_by,
        project_id=payload.project_id,
        name=payload.name,
        method=EstimateMethod.ai_generated,
        confidence=EstimateConfidence.rough_order,
        priced=out.get("priced", []),
        missing=out.get("missing", []),
        contingency_pct=10.0,
    )


# ============================================================
# from-drawings pipeline
# ============================================================


class DrawingsState(TypedDict, total=False):
    payload: dict[str, Any]
    file_ids: list[str]
    page_extractions: list[dict[str, Any]]
    aggregated: list[dict[str, Any]]
    elements: list[dict[str, Any]]
    province: str
    priced: list[dict[str, Any]]
    missing: list[str]


DRAWING_PARSER_SYSTEM = """You are an expert construction drawing analyst.
Examine this architectural or structural drawing. Extract quantifiable elements:
- Room areas (walls, floors, ceilings)
- Wall lengths and heights
- Slab areas
- Column and beam schedules (count, section size, length)

Output strictly as JSON:
{
  "drawing_type": "architectural_plan | structural_plan | elevation | section | schedule",
  "scale": "1:100 | 1:50 | unknown",
  "elements": [
    {"type": "column", "count": 12, "section": "400x400", "height_m": 3.5, "concrete_class": "C30"},
    {"type": "slab", "area_m2": 85.0, "thickness_m": 0.15},
    {"type": "wall", "length_m": 24.0, "height_m": 3.2, "material": "brick"},
    {"type": "finish", "surface": "floor", "area_m2": 85.0, "material": "ceramic_tile"}
  ]
}

If a value is illegible, omit it. Be precise — do not invent numbers."""


async def drawing_parser_node(state: DrawingsState, *, db: AsyncSession) -> DrawingsState:
    """Per-file: fetch bytes, call GPT-4o vision, accumulate extractions."""
    from models.core import File as FileModel  # core module file table

    llm = _vision_llm()
    extractions: list[dict[str, Any]] = []

    for file_id_str in state.get("file_ids", []):
        file_id = UUID(file_id_str)
        file_row = (
            await db.execute(select(FileModel).where(FileModel.id == file_id))
        ).scalar_one_or_none()
        if file_row is None:
            continue

        image_b64 = await _fetch_file_as_b64(file_row.storage_key)
        if not image_b64:
            continue

        resp = await llm.ainvoke(
            [
                SystemMessage(content=DRAWING_PARSER_SYSTEM),
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": "Extract quantifiable elements from this drawing.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{file_row.mime_type};base64,{image_b64}"},
                        },
                    ]
                ),
            ]
        )
        try:
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            parsed = json.loads(_strip_fences(content))
            parsed["file_id"] = str(file_id)
            extractions.append(parsed)
        except Exception as exc:
            logger.warning("drawing_parser failed for file %s: %s", file_id, exc)

    return {**state, "page_extractions": extractions}


async def quantity_takeoff_node(state: DrawingsState) -> DrawingsState:
    """Aggregate raw extractions into (element_type → quantity) map."""
    totals: dict[str, dict[str, float]] = {}

    for page in state.get("page_extractions", []):
        for el in page.get("elements", []):
            t = el.get("type")
            if not t:
                continue
            bucket = totals.setdefault(t, {"quantity": 0.0, "unit": "pcs"})

            if t == "column":
                count = float(el.get("count", 0))
                h = float(el.get("height_m", 0))
                section = el.get("section", "400x400")
                try:
                    a, b = section.lower().split("x")
                    vol = (float(a) / 1000) * (float(b) / 1000) * h * count
                except (ValueError, AttributeError):
                    vol = 0.0
                bucket["quantity"] += vol
                bucket["unit"] = "m3"
                bucket.setdefault("concrete_class", el.get("concrete_class", "C30"))
            elif t == "slab":
                area = float(el.get("area_m2", 0))
                thickness = float(el.get("thickness_m", 0.15))
                bucket["quantity"] += area * thickness
                bucket["unit"] = "m3"
                bucket.setdefault("concrete_class", el.get("concrete_class", "C30"))
            elif t == "wall":
                area = float(el.get("length_m", 0)) * float(el.get("height_m", 0))
                bucket["quantity"] += area
                bucket["unit"] = "m2"
                bucket.setdefault("material", el.get("material", "brick"))
            elif t == "finish":
                bucket["quantity"] += float(el.get("area_m2", 0))
                bucket["unit"] = "m2"
                bucket.setdefault("material", el.get("material", "ceramic_tile"))
            elif t == "beam":
                bucket["quantity"] += float(el.get("length_m", 0)) * float(el.get("count", 1))
                bucket["unit"] = "m"

    return {**state, "aggregated": [{"type": k, **v} for k, v in totals.items()]}


def material_mapper_node(state: DrawingsState) -> DrawingsState:
    """Map aggregated quantities to standard material_codes."""
    section_map = {
        "column": ("04", "concrete"),
        "slab": ("04", "concrete"),
        "beam": ("04", "concrete"),
        "wall": ("05", "masonry"),
        "finish": ("06", "finishing"),
    }
    concrete_code_map = {"C25": "CONC_C25", "C30": "CONC_C30", "C40": "CONC_C40"}
    finish_code_map = {
        "ceramic_tile": "TILE_CERAMIC",
        "paint": "PAINT_EMULSION",
        "plaster": "PLASTER",
    }
    wall_code_map = {"brick": "BRICK_RED", "aac": "BRICK_AAC"}

    elements: list[dict[str, Any]] = []
    for item in state.get("aggregated", []):
        t = item["type"]
        section_code, category = section_map.get(t, ("04", "other"))
        desc = f"{t.capitalize()} works"
        material_code: str | None = None

        if t in ("column", "slab", "beam"):
            cls = item.get("concrete_class", "C30")
            material_code = concrete_code_map.get(cls, "CONC_C30")
            desc = f"Concrete {cls} for {t}"
        elif t == "wall":
            mat = item.get("material", "brick")
            material_code = wall_code_map.get(mat, "BRICK_RED")
            desc = f"{mat.capitalize()} wall"
        elif t == "finish":
            mat = item.get("material", "ceramic_tile")
            material_code = finish_code_map.get(mat, "TILE_CERAMIC")
            desc = f"Finish: {mat}"

        elements.append(
            {
                "section_code": section_code,
                "description": desc,
                "material_code": material_code,
                "category": category,
                "quantity": item["quantity"],
                "unit": item["unit"],
            }
        )

    # add standard MEP allowances (flat, per-m² style — pipeline v1)
    elements.append(
        {
            "section_code": "07",
            "description": "MEP allowance",
            "material_code": "ELECTRICAL_ALLOWANCE",
            "category": "mep",
            "quantity": 1,
            "unit": "lot",
        }
    )

    return {**state, "elements": elements, "province": state["payload"]["province"]}


def _build_drawings_graph(db: AsyncSession):
    # See `_build_brief_graph` — async nodes must be async closures, not sync
    # lambdas returning coroutines.
    async def _parse(state: DrawingsState) -> DrawingsState:
        return await drawing_parser_node(state, db=db)

    async def _price(state: DrawingsState) -> DrawingsState:
        return await price_lookup_node(state, db=db)

    graph: StateGraph = StateGraph(DrawingsState)
    graph.add_node("parse", _parse)
    graph.add_node("takeoff", quantity_takeoff_node)
    graph.add_node("map", material_mapper_node)
    graph.add_node("price", _price)
    graph.set_entry_point("parse")
    graph.add_edge("parse", "takeoff")
    graph.add_edge("takeoff", "map")
    graph.add_edge("map", "price")
    graph.add_edge("price", END)
    return graph.compile()


async def estimate_from_drawings(
    *,
    db: AsyncSession,
    organization_id: UUID,
    created_by: UUID,
    payload: EstimateFromDrawingsRequest,
) -> AiEstimateResult:
    app = _build_drawings_graph(db)
    out: DrawingsState = await app.ainvoke(
        {
            "payload": payload.model_dump(mode="json"),
            "file_ids": [str(f) for f in payload.drawing_file_ids],
        }
    )

    return await _assemble_and_persist(
        db=db,
        organization_id=organization_id,
        created_by=created_by,
        project_id=payload.project_id,
        name=payload.name,
        method=EstimateMethod.ai_generated,
        confidence=EstimateConfidence.detailed
        if not out.get("missing")
        else EstimateConfidence.preliminary,
        priced=out.get("priced", []),
        missing=out.get("missing", []),
        contingency_pct=payload.include_contingency_pct,
    )


# ============================================================
# Assembler + persist
# ============================================================


async def _assemble_and_persist(
    *,
    db: AsyncSession,
    organization_id: UUID,
    created_by: UUID,
    project_id: UUID | None,
    name: str,
    method: EstimateMethod,
    confidence: EstimateConfidence,
    priced: list[dict[str, Any]],
    missing: list[str],
    contingency_pct: float,
) -> AiEstimateResult:
    """Build hierarchical BOQ, compute totals + contingency, persist atomically."""
    estimate_id = uuid4()

    estimate = Estimate(
        id=estimate_id,
        organization_id=organization_id,
        project_id=project_id,
        name=name,
        version=1,
        status=EstimateStatus.draft.value,
        method=method.value,
        confidence=confidence.value,
        created_by=created_by,
    )
    db.add(estimate)
    await db.flush()

    # Group priced items by section
    by_section: dict[str, list[dict[str, Any]]] = {}
    for p in priced:
        code = p.get("section_code") or "04"
        by_section.setdefault(code, []).append(p)

    section_totals: list[Decimal] = []
    rows_out: list[BoqItem] = []

    sort_cursor = 0
    for code, title in BOQ_SECTIONS:
        sort_cursor += 1
        parent_id = uuid4()
        parent = BoqItem(
            id=parent_id,
            estimate_id=estimate_id,
            parent_id=None,
            sort_order=sort_cursor,
            code=code,
            description=title,
            source=BoqItemSource.ai_extracted.value,
        )
        rows_out.append(parent)

        children = by_section.get(code, [])
        section_total = Decimal(0)
        for idx, ch in enumerate(children):
            sort_cursor += 1
            line_total = Decimal(str(ch.get("total_price_vnd") or 0))
            section_total += line_total
            rows_out.append(
                BoqItem(
                    id=uuid4(),
                    estimate_id=estimate_id,
                    parent_id=parent_id,
                    sort_order=sort_cursor,
                    code=f"{code}.{idx + 1:02d}",
                    description=ch.get("description") or ch.get("name") or "",
                    unit=ch.get("unit"),
                    quantity=Decimal(str(ch.get("quantity") or 0)),
                    unit_price_vnd=Decimal(str(ch["unit_price_vnd"]))
                    if ch.get("unit_price_vnd") is not None
                    else None,
                    total_price_vnd=line_total,
                    material_code=ch.get("material_code"),
                    source=BoqItemSource.ai_extracted.value,
                )
            )

        parent.total_price_vnd = section_total
        section_totals.append(section_total)

    subtotal = sum(section_totals, Decimal(0))
    contingency = subtotal * Decimal(str(contingency_pct)) / Decimal(100)

    sort_cursor += 1
    rows_out.append(
        BoqItem(
            id=uuid4(),
            estimate_id=estimate_id,
            parent_id=None,
            sort_order=sort_cursor,
            code="09",
            description=f"Contingency ({contingency_pct:.1f}%)",
            unit="lot",
            quantity=Decimal(1),
            unit_price_vnd=contingency,
            total_price_vnd=contingency,
            source=BoqItemSource.ai_extracted.value,
        )
    )

    grand_total = subtotal + contingency
    estimate.total_vnd = int(grand_total)

    for r in rows_out:
        db.add(r)

    await db.commit()
    await db.refresh(estimate)

    refreshed = (
        (
            await db.execute(
                select(BoqItem)
                .where(BoqItem.estimate_id == estimate_id)
                .order_by(BoqItem.sort_order)
            )
        )
        .scalars()
        .all()
    )

    warnings: list[str] = []
    if missing:
        warnings.append(f"{len(missing)} material(s) missing price data — manual entry required")

    return AiEstimateResult(
        estimate_id=estimate_id,
        total_vnd=int(grand_total),
        confidence=confidence,
        items=[BoqItemOut.model_validate(i) for i in refreshed],
        warnings=warnings,
        missing_price_codes=missing,
    )


# ============================================================
# Helpers
# ============================================================


def _strip_fences(content: str) -> str:
    s = content.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    return s.strip()


async def _fetch_file_as_b64(storage_key: str) -> str | None:
    """Fetch file bytes from S3 and return base64 string."""
    try:
        import boto3
    except ImportError:
        logger.warning("boto3 not installed; cannot fetch %s", storage_key)
        return None

    try:
        s3 = boto3.client("s3", region_name=_settings.aws_region)
        obj = s3.get_object(Bucket=_settings.s3_bucket, Key=storage_key)
        return base64.b64encode(obj["Body"].read()).decode("ascii")
    except Exception as exc:
        logger.warning("S3 fetch failed for %s: %s", storage_key, exc)
        return None
