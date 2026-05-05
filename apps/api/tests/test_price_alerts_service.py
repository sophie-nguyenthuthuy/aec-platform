"""Unit tests for `services/price_alerts.py::evaluate_price_alerts`.

The service is the body of the nightly arq cron `price_alerts_evaluate_job`.
What we lock in:

  1. **Baseline-seeding branch** — when an alert has `last_price_vnd=NULL`,
     the first evaluation seeds the baseline with the current price and
     does NOT fire a notification. (Common bug shape: notifying on every
     first observation, spamming subscribers.)
  2. **Threshold gate** — alerts where `|delta_pct| < threshold_pct` are
     skipped silently. Above threshold → notify + reset baseline.
  3. **Skip rules** — rows where the JOIN found no current price
     (`current_price_vnd IS NULL`) are counted under
     `skipped_missing_price`, not `evaluated`.
  4. **Cross-tenant scope** — service uses `AdminSessionFactory`, NOT
     `SessionFactory`, because price_alerts table has RLS and aec_app
     is NOBYPASSRLS. We just assert the right factory is called; the
     RLS contract is exercised in `test_costpulse_rls.py`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.asyncio


def _make_session_with_rows(rows):
    """Build a fake AsyncSession that returns the given canned rows from
    the LATERAL JOIN query, and records every UPDATE / commit."""
    session = MagicMock()

    execute_calls = []

    async def fake_execute(stmt, params=None):
        execute_calls.append((str(stmt), params or {}))
        result = MagicMock()
        # The first execute is the LATERAL JOIN; subsequent ones are
        # `_update_baseline` UPDATEs. Pretend the SELECT returns rows
        # and the UPDATEs return None.
        if "FROM price_alerts" in str(stmt):
            mappings = MagicMock()
            mappings.all.return_value = rows
            result.mappings.return_value = mappings
        return result

    session.execute = fake_execute
    session.commit = AsyncMock()
    session.execute_calls = execute_calls
    return session


def _patch_admin_factory(monkeypatch, session):
    """Replace `AdminSessionFactory` with a context manager that yields
    `session`. Mirrors what the real async_sessionmaker does."""

    @asynccontextmanager
    async def _cm():
        yield session

    monkeypatch.setattr("services.price_alerts.AdminSessionFactory", _cm)


async def test_first_observation_seeds_baseline_without_notifying(monkeypatch):
    rows = [
        {
            "alert_id": "alert-1",
            "organization_id": "org-1",
            "user_id": "user-1",
            "material_code": "CONC_C30",
            "province": "Hanoi",
            "threshold_pct": 5,
            "last_price_vnd": None,  # ← never observed before
            "user_email": "buyer@example.com",
            "current_price_vnd": 2_000_000,
            "current_effective_date": "2026-04-01",
            "material_name": "Concrete C30",
        }
    ]
    session = _make_session_with_rows(rows)
    _patch_admin_factory(monkeypatch, session)

    notify = AsyncMock()
    monkeypatch.setattr("services.price_alerts._notify", notify)

    from services.price_alerts import evaluate_price_alerts

    summary = await evaluate_price_alerts()

    assert summary == {
        "evaluated": 1,
        "triggered": 0,
        "skipped_missing_price": 0,
        "skipped_no_baseline": 1,
    }
    notify.assert_not_awaited()
    # Should have updated last_price_vnd to seed the baseline (one
    # `UPDATE price_alerts SET last_price_vnd = :p` after the SELECT).
    update_calls = [c for c in session.execute_calls if "UPDATE price_alerts" in c[0]]
    assert len(update_calls) == 1
    assert update_calls[0][1]["p"] == Decimal(2_000_000)


async def test_above_threshold_fires_notify_and_resets_baseline(monkeypatch):
    rows = [
        {
            "alert_id": "alert-1",
            "organization_id": "org-1",
            "user_id": "user-1",
            "material_code": "CONC_C30",
            "province": "Hanoi",
            "threshold_pct": 5,
            "last_price_vnd": 2_000_000,
            "user_email": "buyer@example.com",
            "current_price_vnd": 2_200_000,  # +10% — above 5% threshold
            "current_effective_date": "2026-05-01",
            "material_name": "Concrete C30",
        }
    ]
    session = _make_session_with_rows(rows)
    _patch_admin_factory(monkeypatch, session)

    notify = AsyncMock()
    monkeypatch.setattr("services.price_alerts._notify", notify)

    from services.price_alerts import evaluate_price_alerts

    summary = await evaluate_price_alerts()

    assert summary["triggered"] == 1
    assert summary["evaluated"] == 1
    notify.assert_awaited_once()
    # After firing, baseline must be reset to current price so the
    # next run doesn't fire again on the same movement.
    update_calls = [c for c in session.execute_calls if "UPDATE price_alerts" in c[0]]
    assert len(update_calls) == 1
    assert update_calls[0][1]["p"] == Decimal(2_200_000)


async def test_below_threshold_does_not_notify_and_does_not_reset(monkeypatch):
    rows = [
        {
            "alert_id": "alert-1",
            "organization_id": "org-1",
            "user_id": "user-1",
            "material_code": "CONC_C30",
            "province": "Hanoi",
            "threshold_pct": 5,
            "last_price_vnd": 2_000_000,
            "user_email": "buyer@example.com",
            "current_price_vnd": 2_080_000,  # +4% — below 5% threshold
            "current_effective_date": "2026-05-01",
            "material_name": "Concrete C30",
        }
    ]
    session = _make_session_with_rows(rows)
    _patch_admin_factory(monkeypatch, session)

    notify = AsyncMock()
    monkeypatch.setattr("services.price_alerts._notify", notify)

    from services.price_alerts import evaluate_price_alerts

    summary = await evaluate_price_alerts()

    assert summary["triggered"] == 0
    notify.assert_not_awaited()
    # Baseline NOT reset — we want to keep the old baseline so a series
    # of small movements that compound into a big one eventually fires.
    update_calls = [c for c in session.execute_calls if "UPDATE price_alerts" in c[0]]
    assert len(update_calls) == 0


async def test_negative_threshold_breach_also_fires(monkeypatch):
    """The threshold check uses `abs(delta_pct)` — a price drop above
    threshold is just as worth notifying as a price rise. Easy to
    regression with a `delta_pct >` instead of `abs(delta_pct) >=` swap."""
    rows = [
        {
            "alert_id": "alert-1",
            "organization_id": "org-1",
            "user_id": "user-1",
            "material_code": "CONC_C30",
            "province": "Hanoi",
            "threshold_pct": 5,
            "last_price_vnd": 2_000_000,
            "user_email": "buyer@example.com",
            "current_price_vnd": 1_700_000,  # -15% — drop above 5% threshold
            "current_effective_date": "2026-05-01",
            "material_name": "Concrete C30",
        }
    ]
    session = _make_session_with_rows(rows)
    _patch_admin_factory(monkeypatch, session)

    notify = AsyncMock()
    monkeypatch.setattr("services.price_alerts._notify", notify)

    from services.price_alerts import evaluate_price_alerts

    summary = await evaluate_price_alerts()

    assert summary["triggered"] == 1
    notify.assert_awaited_once()


async def test_missing_current_price_is_counted_under_skipped(monkeypatch):
    """The LATERAL JOIN returns NULL for current_price_vnd when no
    material_prices row matches the alert's (code, province). Those are
    not evaluation failures — they're alerts with stale subjects, and
    we just count them so an operator can investigate."""
    rows = [
        {
            "alert_id": "alert-1",
            "organization_id": "org-1",
            "user_id": "user-1",
            "material_code": "DEFUNCT_CODE",
            "province": "Hanoi",
            "threshold_pct": 5,
            "last_price_vnd": 1_000_000,
            "user_email": "buyer@example.com",
            "current_price_vnd": None,  # ← no matching price row
            "current_effective_date": None,
            "material_name": None,
        }
    ]
    session = _make_session_with_rows(rows)
    _patch_admin_factory(monkeypatch, session)

    notify = AsyncMock()
    monkeypatch.setattr("services.price_alerts._notify", notify)

    from services.price_alerts import evaluate_price_alerts

    summary = await evaluate_price_alerts()

    assert summary == {
        "evaluated": 1,
        "triggered": 0,
        "skipped_missing_price": 1,
        "skipped_no_baseline": 0,
    }
    notify.assert_not_awaited()


async def test_zero_baseline_resets_baseline_to_current_silently(monkeypatch):
    """Defensive: if a malformed alert ends up with last_price_vnd=0,
    the divide-by-zero would crash. Code reseeds the baseline and
    moves on — no notify, no count under triggered."""
    rows = [
        {
            "alert_id": "alert-1",
            "organization_id": "org-1",
            "user_id": "user-1",
            "material_code": "CONC_C30",
            "province": "Hanoi",
            "threshold_pct": 5,
            "last_price_vnd": 0,  # ← would divide-by-zero
            "user_email": "buyer@example.com",
            "current_price_vnd": 2_000_000,
            "current_effective_date": "2026-05-01",
            "material_name": "Concrete C30",
        }
    ]
    session = _make_session_with_rows(rows)
    _patch_admin_factory(monkeypatch, session)

    notify = AsyncMock()
    monkeypatch.setattr("services.price_alerts._notify", notify)

    from services.price_alerts import evaluate_price_alerts

    summary = await evaluate_price_alerts()

    assert summary["triggered"] == 0
    notify.assert_not_awaited()
    # Baseline did get reset (to recover from the malformed state).
    update_calls = [c for c in session.execute_calls if "UPDATE price_alerts" in c[0]]
    assert len(update_calls) == 1
