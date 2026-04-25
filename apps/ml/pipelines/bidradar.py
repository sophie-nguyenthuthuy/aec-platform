"""AI pipeline for BIDRADAR — scraping + LangGraph scoring + digest.

Scrapers are pluggable per-source. Scoring runs a LangGraph state machine:
    normalize → rule_score → llm_score → finalize

LLM uses Anthropic Claude (matching the rest of the codebase).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict
from uuid import UUID

import httpx
from bs4 import BeautifulSoup
from core.config import get_settings
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError
from schemas.bidradar import AIRecommendation, CompetitionLevel

logger = logging.getLogger(__name__)


def _llm(temperature: float = 0.2) -> ChatAnthropic:
    settings = get_settings()
    return ChatAnthropic(
        model=settings.anthropic_model,
        anthropic_api_key=settings.anthropic_api_key,
        temperature=temperature,
        max_tokens=1024,
    )


# ============================================================
# Scrapers
# ============================================================

ScrapedTender = dict[str, Any]
ScraperFn = Callable[[int], Awaitable[list[ScrapedTender]]]

USER_AGENT = "AECPlatform/1.0 BidRadar (+https://aec-platform.vn)"


async def _fetch(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _digits_only(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    return int(digits) if digits else None


def _txt(el: Any) -> str | None:
    return el.get_text(strip=True) if el else None


async def _scrape_mua_sam_cong(max_pages: int) -> list[ScrapedTender]:
    """Vietnam public procurement: muasamcong.mpi.gov.vn."""
    base = "https://muasamcong.mpi.gov.vn"
    out: list[ScrapedTender] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        for page in range(1, max_pages + 1):
            try:
                html = await _fetch(client, f"{base}/tender/search?page={page}")
            except httpx.HTTPError as exc:
                logger.warning("mua-sam-cong page %d failed: %s", page, exc)
                break
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select(".tender-item, li.search-result")
            if not rows:
                break
            for row in rows:
                link = row.select_one("a[href]")
                title = _txt(row.select_one(".title, h3, a"))
                if not (link and title):
                    continue
                href = link.get("href", "")
                external_id = href.rstrip("/").split("/")[-1] or href
                out.append(
                    {
                        "external_id": external_id,
                        "title": title,
                        "issuer": _txt(row.select_one(".issuer, .org")),
                        "type": _txt(row.select_one(".type")),
                        "budget_vnd": _digits_only(_txt(row.select_one(".budget"))),
                        "currency": "VND",
                        "country_code": "VN",
                        "province": _txt(row.select_one(".province")),
                        "raw_url": href if href.startswith("http") else f"{base}{href}",
                        "raw_payload": {"html_snippet": str(row)[:4000]},
                    }
                )
    return out


async def _scrape_philgeps(max_pages: int) -> list[ScrapedTender]:
    """Philippines: philgeps.gov.ph."""
    base = "https://notices.philgeps.gov.ph"
    out: list[ScrapedTender] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        for page in range(1, max_pages + 1):
            try:
                html = await _fetch(
                    client, f"{base}/GEPSNONPILOT/Tender/SplashBidNoticeAbstractUI.aspx?page={page}"
                )
            except httpx.HTTPError as exc:
                logger.warning("PhilGEPS page %d failed: %s", page, exc)
                break
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("tr.notice-row, .bid-notice, table tr[data-ref]")
            if not rows:
                break
            for row in rows:
                title = _txt(row.select_one(".title, td.title, a"))
                if not title:
                    continue
                ref = row.get("data-ref") or _txt(row.select_one(".ref")) or title
                out.append(
                    {
                        "external_id": ref,
                        "title": title,
                        "issuer": _txt(row.select_one(".issuer, .org, td.org")),
                        "type": _txt(row.select_one(".category")),
                        "budget_vnd": None,
                        "currency": "PHP",
                        "country_code": "PH",
                        "province": _txt(row.select_one(".area, .region")),
                        "raw_url": base,
                        "raw_payload": {"row_html": str(row)[:4000]},
                    }
                )
    return out


async def _scrape_egp_thailand(max_pages: int) -> list[ScrapedTender]:
    """Thailand: egp.go.th (e-Government Procurement)."""
    base = "https://process3.gprocurement.go.th"
    out: list[ScrapedTender] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        for page in range(1, max_pages + 1):
            try:
                html = await _fetch(client, f"{base}/EGPWeb/jsp/annual_plan_search.jsp?page={page}")
            except httpx.HTTPError as exc:
                logger.warning("eGP Thailand page %d failed: %s", page, exc)
                break
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("tr.result-row, .search-result-item")
            if not rows:
                break
            for row in rows:
                title = _txt(row.select_one(".title, a"))
                if not title:
                    continue
                ref = _txt(row.select_one(".ref, .project-no")) or title
                out.append(
                    {
                        "external_id": ref,
                        "title": title,
                        "issuer": _txt(row.select_one(".agency")),
                        "budget_vnd": None,
                        "currency": "THB",
                        "country_code": "TH",
                        "province": _txt(row.select_one(".province")),
                        "raw_url": base,
                        "raw_payload": {"row_html": str(row)[:4000]},
                    }
                )
    return out


async def _scrape_lkpp(max_pages: int) -> list[ScrapedTender]:
    """Indonesia: eproc.lkpp.go.id (LPSE)."""
    base = "https://inaproc.id"
    out: list[ScrapedTender] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        for page in range(1, max_pages + 1):
            try:
                html = await _fetch(client, f"{base}/tender/search?page={page}")
            except httpx.HTTPError as exc:
                logger.warning("LKPP page %d failed: %s", page, exc)
                break
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select(".tender-item, li.search-result, tr.data-row")
            if not rows:
                break
            for row in rows:
                title = _txt(row.select_one(".title, a"))
                if not title:
                    continue
                ref = _txt(row.select_one(".kode, .ref")) or title
                out.append(
                    {
                        "external_id": ref,
                        "title": title,
                        "issuer": _txt(row.select_one(".instansi")),
                        "budget_vnd": None,
                        "currency": "IDR",
                        "country_code": "ID",
                        "province": _txt(row.select_one(".provinsi")),
                        "raw_url": base,
                        "raw_payload": {"row_html": str(row)[:4000]},
                    }
                )
    return out


async def _scrape_gebiz(max_pages: int) -> list[ScrapedTender]:
    """Singapore: gebiz.gov.sg."""
    base = "https://www.gebiz.gov.sg"
    out: list[ScrapedTender] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        for page in range(1, max_pages + 1):
            try:
                html = await _fetch(client, f"{base}/ptn/opportunity/BOListing.xhtml?page={page}")
            except httpx.HTTPError as exc:
                logger.warning("GeBIZ page %d failed: %s", page, exc)
                break
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select(".table_row, tr.opportunity-row")
            if not rows:
                break
            for row in rows:
                title = _txt(row.select_one(".title, a"))
                if not title:
                    continue
                ref = _txt(row.select_one(".ref-no")) or title
                out.append(
                    {
                        "external_id": ref,
                        "title": title,
                        "issuer": _txt(row.select_one(".agency")),
                        "budget_vnd": None,
                        "currency": "SGD",
                        "country_code": "SG",
                        "province": None,
                        "raw_url": base,
                        "raw_payload": {"row_html": str(row)[:4000]},
                    }
                )
    return out


async def _scrape_generic(source: str, max_pages: int) -> list[ScrapedTender]:
    logger.info("No dedicated scraper for %s; returning empty result", source)
    return []


SCRAPERS: dict[str, ScraperFn] = {
    "mua-sam-cong.gov.vn": _scrape_mua_sam_cong,
    "philgeps.gov.ph": _scrape_philgeps,
    "egp.go.th": _scrape_egp_thailand,
    "eproc.lkpp.go.id": _scrape_lkpp,
    "gebiz.gov.sg": _scrape_gebiz,
}


async def scrape_source(source: str, max_pages: int = 5) -> list[ScrapedTender]:
    scraper = SCRAPERS.get(source)
    if scraper is None:
        return await _scrape_generic(source, max_pages)
    return await scraper(max_pages)


# ============================================================
# Scoring (LangGraph)
# ============================================================


class _LLMScore(BaseModel):
    win_probability: float = Field(ge=0, le=1)
    competition_level: CompetitionLevel
    reasoning: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)


class ScoreState(TypedDict, total=False):
    tender: dict[str, Any]
    profile: dict[str, Any]
    normalized: dict[str, Any]
    rule_score: float
    estimated_value_vnd: int | None
    llm: _LLMScore
    recommendation: AIRecommendation


def _normalize(state: ScoreState) -> ScoreState:
    tender = state["tender"]
    profile = state["profile"]
    return {
        **state,
        "normalized": {
            "tender_disciplines": set(tender.get("disciplines") or []),
            "tender_types": set(tender.get("project_types") or []),
            "tender_province": tender.get("province"),
            "tender_budget": tender.get("budget_vnd"),
            "profile_disciplines": set(profile.get("disciplines") or []),
            "profile_types": set(profile.get("project_types") or []),
            "profile_provinces": set(profile.get("provinces") or []),
        },
    }


def _rule_score(state: ScoreState) -> ScoreState:
    n = state["normalized"]
    profile = state["profile"]
    score = 0.0

    td, pd = n["tender_disciplines"], n["profile_disciplines"]
    if pd:
        overlap = len(td & pd) / max(len(pd), 1) if td else 0.0
        score += 35.0 * min(overlap, 1.0)

    tt, pt = n["tender_types"], n["profile_types"]
    if pt and tt:
        overlap = len(tt & pt) / max(len(pt), 1)
        score += 20.0 * min(overlap, 1.0)

    if (
        n["tender_province"]
        and n["profile_provinces"]
        and n["tender_province"] in n["profile_provinces"]
    ):
        score += 15.0

    budget = n["tender_budget"]
    if budget is not None:
        lo, hi = profile.get("min_budget_vnd"), profile.get("max_budget_vnd")
        if (lo is None or budget >= lo) and (hi is None or budget <= hi):
            score += 20.0
        elif hi is not None and budget > hi * 1.5:
            score -= 10.0

    capacity = profile.get("active_capacity_pct")
    if capacity is not None:
        free = max(0.0, 100.0 - float(capacity))
        score += 10.0 * min(free / 50.0, 1.0)

    return {**state, "rule_score": max(0.0, min(100.0, score)), "estimated_value_vnd": budget}


_LLM_SYSTEM = (
    "You score public-tender opportunities for an AEC "
    "(architecture / engineering / construction) firm. "
    "Return a single JSON object with keys: "
    "win_probability (0-1), competition_level (low|moderate|high|very_high), "
    "reasoning (string), strengths (list[string]), risks (list[string]), "
    "required_capabilities (list[string]). JSON only, no prose."
)


def _build_user_prompt(state: ScoreState) -> str:
    tender = state["tender"]
    profile = state["profile"]
    return (
        "FIRM PROFILE:\n"
        f"- disciplines: {profile.get('disciplines') or []}\n"
        f"- project_types: {profile.get('project_types') or []}\n"
        f"- provinces: {profile.get('provinces') or []}\n"
        f"- team_size: {profile.get('team_size')}\n"
        f"- active_capacity_pct: {profile.get('active_capacity_pct')}\n"
        f"- past_wins: {profile.get('past_wins') or []}\n"
        f"- keywords: {profile.get('keywords') or []}\n\n"
        "TENDER:\n"
        f"- title: {tender.get('title')}\n"
        f"- issuer: {tender.get('issuer')}\n"
        f"- type: {tender.get('type')}\n"
        f"- budget_vnd: {tender.get('budget_vnd')}\n"
        f"- province: {tender.get('province')}\n"
        f"- disciplines: {tender.get('disciplines') or []}\n"
        f"- description: {(tender.get('description') or '')[:4000]}\n\n"
        "Assess fit and competition. Output JSON only."
    )


def _llm_score(state: ScoreState) -> ScoreState:
    try:
        resp = _llm().invoke(
            [
                SystemMessage(content=_LLM_SYSTEM),
                HumanMessage(content=_build_user_prompt(state)),
            ]
        )
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        result = _LLMScore.model_validate_json(_extract_json(text))
    except (ValidationError, ValueError, Exception) as exc:
        logger.warning("LLM scoring failed (%s); falling back to rule-only", exc)
        result = _LLMScore(
            win_probability=min(state["rule_score"] / 100.0, 1.0) * 0.6,
            competition_level=CompetitionLevel.moderate,
            reasoning="LLM unavailable; score derived from rule-based heuristic only.",
            risks=["AI scoring unavailable"],
        )
    return {**state, "llm": result}


def _extract_json(text: str) -> str:
    """Claude sometimes wraps JSON in ```json fences — strip them."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:].lstrip()
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        return t[start : end + 1]
    return t


def _finalize(state: ScoreState) -> ScoreState:
    rule = state["rule_score"]
    llm = state["llm"]
    combined = 0.55 * rule + 0.45 * (llm.win_probability * 100.0)
    recommended = combined >= 65.0 and llm.win_probability >= 0.35

    return {
        **state,
        "recommendation": AIRecommendation(
            match_score=round(combined, 2),
            estimated_value_vnd=state.get("estimated_value_vnd"),
            competition_level=llm.competition_level,
            win_probability=round(llm.win_probability, 3),
            recommended_bid=recommended,
            reasoning=llm.reasoning,
            strengths=llm.strengths,
            risks=llm.risks,
            required_capabilities=llm.required_capabilities,
        ),
    }


def _build_graph():
    g = StateGraph(ScoreState)
    g.add_node("normalize_node", _normalize)
    g.add_node("rule_score_node", _rule_score)
    g.add_node("llm_score_node", _llm_score)
    g.add_node("finalize_node", _finalize)
    g.set_entry_point("normalize_node")
    g.add_edge("normalize_node", "rule_score_node")
    g.add_edge("rule_score_node", "llm_score_node")
    g.add_edge("llm_score_node", "finalize_node")
    g.add_edge("finalize_node", END)
    return g.compile()


_GRAPH = _build_graph()


def _tender_to_dict(tender: Any) -> dict[str, Any]:
    return {
        "id": getattr(tender, "id", None),
        "title": getattr(tender, "title", ""),
        "description": getattr(tender, "description", None),
        "issuer": getattr(tender, "issuer", None),
        "type": getattr(tender, "type", None),
        "budget_vnd": getattr(tender, "budget_vnd", None),
        "province": getattr(tender, "province", None),
        "disciplines": getattr(tender, "disciplines", None),
        "project_types": getattr(tender, "project_types", None),
    }


def _profile_to_dict(profile: Any) -> dict[str, Any]:
    return {
        "disciplines": getattr(profile, "disciplines", None) or [],
        "project_types": getattr(profile, "project_types", None) or [],
        "provinces": getattr(profile, "provinces", None) or [],
        "min_budget_vnd": getattr(profile, "min_budget_vnd", None),
        "max_budget_vnd": getattr(profile, "max_budget_vnd", None),
        "team_size": getattr(profile, "team_size", None),
        "active_capacity_pct": getattr(profile, "active_capacity_pct", None),
        "past_wins": getattr(profile, "past_wins", None) or [],
        "keywords": getattr(profile, "keywords", None) or [],
    }


async def score_tender_for_firm(tender: Any, profile: Any) -> AIRecommendation:
    """Score a tender against a firm profile. Returns an AIRecommendation."""
    state_in: ScoreState = {
        "tender": _tender_to_dict(tender),
        "profile": _profile_to_dict(profile),
    }
    loop = asyncio.get_running_loop()
    result: ScoreState = await loop.run_in_executor(None, lambda: _GRAPH.invoke(state_in))
    return result["recommendation"]


# ============================================================
# Embeddings — push tender text into the shared pgvector index
# ============================================================


async def embed_tender(
    db,
    organization_id: UUID,
    tender_id: UUID,
    title: str,
    description: str | None,
) -> None:
    """Embed tender title + description into the shared `embeddings` table.

    Uses OpenAI embeddings (matches platform default). Row tagged with
    source_module='bidradar' so tenant search + retrieval can filter.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        logger.debug("OPENAI_API_KEY unset; skipping tender embedding")
        return

    from openai import AsyncOpenAI
    from sqlalchemy import text

    content = title if not description else f"{title}\n\n{description}"
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.embeddings.create(
        model=settings.openai_embedding_model,
        input=content[:8000],
    )
    vector = resp.data[0].embedding

    await db.execute(
        text(
            "INSERT INTO embeddings "
            "(organization_id, source_module, source_id, chunk_index, content, embedding, metadata) "
            "VALUES (:org, 'bidradar', :sid, 0, :content, :embedding, :meta)"
        ),
        {
            "org": str(organization_id),
            "sid": str(tender_id),
            "content": content[:8000],
            "embedding": vector,
            "meta": json.dumps({"tender_id": str(tender_id)}),
        },
    )


# ============================================================
# Weekly digest — email send via SMTP
# ============================================================


async def send_weekly_digest(
    organization_id: UUID,
    recipients: list[str],
    match_ids: list[UUID],
    subject: str | None = None,
    html_body: str | None = None,
) -> None:
    """Send the weekly 'best matches' email.

    Uses SMTP settings from app config. If SMTP is not configured, logs the
    payload (useful in dev / CI). Callers are expected to render `html_body`
    before invoking; this function is transport-only.
    """
    settings = get_settings()
    if not recipients or not match_ids:
        logger.info("Digest skipped (no recipients or matches) org=%s", organization_id)
        return

    if not settings.smtp_host:
        logger.info(
            "SMTP unconfigured; digest payload: org=%s recipients=%s matches=%d",
            organization_id,
            recipients,
            len(match_ids),
        )
        return

    from email.message import EmailMessage

    import aiosmtplib

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject or f"BidRadar: {len(match_ids)} best tender matches this week"
    msg.set_content(
        f"You have {len(match_ids)} recommended tenders this week. "
        "View the full list at /bidradar.\n\n"
        f"Match IDs: {', '.join(str(m) for m in match_ids)}"
    )
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=True,
    )
