"""Tests for services.llm_spend cost computation + recording.

Pure cost math is unit-tested directly. The async `record_llm_call`
swallow-on-error contract is tested by patching AdminSessionFactory
to raise; the test must complete without re-raising.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.llm_spend import compute_cost_vnd, record_llm_call


def test_compute_cost_gemini_flash_input_only():
    """Embedding pass: input-only, zero output tokens, low rate."""
    cost = compute_cost_vnd(
        provider="gemini",
        model="gemini-1.5-flash",
        input_tokens=1000,
        output_tokens=0,
    )
    # input: 1000 tokens * 0.000075 USD/k = 0.000075 USD = 1.84 VND → 2
    assert 1 <= cost <= 3


def test_compute_cost_claude_sonnet_typical_call():
    """Typical Drawbridge call: ~4k in / ~800 out."""
    cost = compute_cost_vnd(
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=4000,
        output_tokens=800,
    )
    # input: 4000 * 0.003 / 1000 = 0.012 USD
    # output: 800 * 0.015 / 1000 = 0.012 USD
    # total: 0.024 USD * 24,500 = 588 VND
    assert 550 <= cost <= 620


def test_compute_cost_unknown_model_falls_back_conservatively():
    """Unknown model → fall back to Claude-Sonnet rate (not zero)."""
    cost = compute_cost_vnd(
        provider="anthropic",
        model="claude-unreleased-2030",
        input_tokens=1000,
        output_tokens=1000,
    )
    assert cost > 0


def test_compute_cost_zero_tokens_returns_zero():
    """Both token counts zero → cost zero, no surprises."""
    assert (
        compute_cost_vnd(
            provider="gemini", model="gemini-1.5-flash", input_tokens=0, output_tokens=0
        )
        == 0
    )


def test_compute_cost_substring_match():
    """Pricing table uses substring matching — `claude-haiku-3-5-20240520`
    should resolve to the `claude-haiku` row, not the fallback rate."""
    cheap = compute_cost_vnd(
        provider="anthropic",
        model="claude-haiku-3-5-20240520",
        input_tokens=10_000,
        output_tokens=2_000,
    )
    # haiku is ~12x cheaper than sonnet on input; if we fell back to
    # the conservative sonnet rate, cost would be ~12x what it should be.
    # Sanity check: haiku 10k in + 2k out ≈ 0.0025 + 0.0025 = 0.005 USD
    # = ~122 VND. Sonnet fallback would put it ~1500 VND.
    assert cheap < 500, f"expected haiku rate (~120 VND), got {cheap}"


@pytest.mark.asyncio
async def test_record_llm_call_inserts_with_computed_cost(monkeypatch):
    """Happy path: INSERT fires with the right (org, module, cost) bind."""
    captured: list[tuple[str, dict]] = []

    async def fake_execute(stmt, params=None):
        captured.append((str(stmt), dict(params or {})))

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)
    sess.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self_inner):
            return sess

        async def __aexit__(self_inner, *args):
            return False

    with patch("db.session.AdminSessionFactory", lambda *a, **kw: _Ctx()):
        org_id = uuid4()
        await record_llm_call(
            organization_id=org_id,
            module="drawbridge",
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=2000,
            output_tokens=500,
            request_id="req_abc",
        )

    assert len(captured) == 1
    sql, params = captured[0]
    assert "INSERT INTO llm_spend_events" in sql
    assert params["org"] == str(org_id)
    assert params["mod"] == "drawbridge"
    assert params["prov"] == "anthropic"
    assert params["in_tok"] == 2000
    assert params["out_tok"] == 500
    assert params["req"] == "req_abc"
    assert params["cost"] > 0


@pytest.mark.asyncio
async def test_record_llm_call_swallows_db_errors():
    """Recording is best-effort — a DB outage must not raise."""

    async def fake_execute(*_a, **_kw):
        raise RuntimeError("simulated db outage")

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)
    sess.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self_inner):
            return sess

        async def __aexit__(self_inner, *args):
            return False

    with patch("db.session.AdminSessionFactory", lambda *a, **kw: _Ctx()):
        # Must NOT raise.
        await record_llm_call(
            organization_id=uuid4(),
            module="codeguard",
            provider="gemini",
            model="gemini-1.5-flash",
            input_tokens=100,
            output_tokens=50,
        )


@pytest.mark.asyncio
async def test_record_llm_call_zero_tokens_is_noop(monkeypatch):
    """Zero in + zero out → no INSERT fires."""
    fired = False

    class _Ctx:
        async def __aenter__(self_inner):
            nonlocal fired
            fired = True
            return MagicMock()

        async def __aexit__(self_inner, *args):
            return False

    with patch("db.session.AdminSessionFactory", lambda *a, **kw: _Ctx()):
        await record_llm_call(
            organization_id=uuid4(),
            module="codeguard",
            provider="gemini",
            model="gemini-1.5-flash",
            input_tokens=0,
            output_tokens=0,
        )

    assert fired is False
