"""Unit tests for the BIDRADAR scoring pipeline (LLM mocked)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.asyncio


def _tender(**overrides):
    base = dict(
        id=None,
        title="Thiết kế cải tạo trụ sở UBND quận",
        description="Renovation of district admin HQ, ~5000 sqm, BIM required.",
        issuer="UBND Quận 1",
        type="design",
        budget_vnd=8_000_000_000,
        province="HCMC",
        disciplines=["architecture", "structural"],
        project_types=["civic"],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _profile(**overrides):
    base = dict(
        disciplines=["architecture", "structural", "MEP"],
        project_types=["civic", "commercial"],
        provinces=["HCMC", "Hanoi"],
        min_budget_vnd=1_000_000_000,
        max_budget_vnd=20_000_000_000,
        team_size=30,
        active_capacity_pct=60.0,
        past_wins=[{"title": "UBND Quận 3 renovation", "year": 2024}],
        keywords=["BIM", "civic"],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


async def test_score_uses_llm_output_and_rule_score_blend(monkeypatch):
    from ml.pipelines import bidradar as pipe

    def fake_llm_score(state):
        return {
            **state,
            "llm": pipe._LLMScore(
                win_probability=0.8,
                competition_level=pipe.CompetitionLevel.moderate,
                reasoning="Strong alignment with past civic wins.",
                strengths=["Past civic wins", "Full discipline coverage"],
                risks=["Tight deadline"],
                required_capabilities=["BIM Level 2"],
            ),
        }

    monkeypatch.setattr(pipe, "_llm_score", fake_llm_score)
    monkeypatch.setattr(pipe, "_GRAPH", pipe._build_graph())

    rec = await pipe.score_tender_for_firm(_tender(), _profile())

    assert rec.win_probability == 0.8
    assert rec.competition_level == pipe.CompetitionLevel.moderate
    assert rec.strengths == ["Past civic wins", "Full discipline coverage"]
    assert rec.risks == ["Tight deadline"]
    assert rec.estimated_value_vnd == 8_000_000_000
    assert rec.match_score > 60
    assert rec.recommended_bid is True


async def test_score_falls_back_when_llm_raises(monkeypatch):
    from ml.pipelines import bidradar as pipe

    def boom(state):
        raise RuntimeError("Anthropic down")

    monkeypatch.setattr(pipe, "_llm", lambda **_: None)

    def fake_llm_score(state):
        try:
            boom(state)
        except Exception:
            return {
                **state,
                "llm": pipe._LLMScore(
                    win_probability=min(state["rule_score"] / 100.0, 1.0) * 0.6,
                    competition_level=pipe.CompetitionLevel.moderate,
                    reasoning="LLM unavailable; rule-only.",
                    risks=["AI scoring unavailable"],
                ),
            }

    monkeypatch.setattr(pipe, "_llm_score", fake_llm_score)
    monkeypatch.setattr(pipe, "_GRAPH", pipe._build_graph())

    rec = await pipe.score_tender_for_firm(_tender(), _profile())
    assert "LLM unavailable" in rec.reasoning
    assert "AI scoring unavailable" in rec.risks


async def test_rule_score_penalises_oversized_budget(monkeypatch):
    from ml.pipelines import bidradar as pipe

    monkeypatch.setattr(
        pipe,
        "_llm_score",
        lambda state: {
            **state,
            "llm": pipe._LLMScore(
                win_probability=0.3,
                competition_level=pipe.CompetitionLevel.high,
                reasoning="Outside firm sweet spot.",
            ),
        },
    )
    monkeypatch.setattr(pipe, "_GRAPH", pipe._build_graph())

    oversized = _tender(budget_vnd=500_000_000_000)
    profile = _profile(max_budget_vnd=20_000_000_000)
    rec = await pipe.score_tender_for_firm(oversized, profile)
    assert rec.recommended_bid is False


async def test_all_asean_scrapers_registered():
    from ml.pipelines.bidradar import SCRAPERS

    assert set(SCRAPERS.keys()) == {
        "mua-sam-cong.gov.vn",
        "philgeps.gov.ph",
        "egp.go.th",
        "eproc.lkpp.go.id",
        "gebiz.gov.sg",
    }


async def test_unknown_source_returns_empty():
    from ml.pipelines.bidradar import scrape_source

    assert await scrape_source("does-not-exist.gov", max_pages=3) == []
