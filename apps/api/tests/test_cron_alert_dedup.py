"""Cron alert dedup ratchet (cycle R3).

Pinned seams:
  1. `should_emit_alert` returns emit=True for a fresh failure
     (no prior row).
  2. Subsequent calls within the repeat-interval suppress (emit=False).
  3. Repeat intervals: 30min for the 2nd alert, 6h for subsequent.
  4. Unknown kind raises ValueError (defensive — caller bug, not
     silent suppression).
  5. `_repeat_interval_for(alert_count)` graduates correctly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


pytestmark = pytest.mark.asyncio


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        sql_text = stmt.text if hasattr(stmt, "text") else str(stmt)
        self.calls.append((sql_text, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.mappings.return_value.first.return_value = None
        r.rowcount = 0
        return r

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


def _no_existing() -> Any:
    """SELECT result with no prior alert row."""
    r = MagicMock()
    r.mappings.return_value.first.return_value = None
    return r


def _existing_alert(*, alert_count: int) -> Any:
    """SELECT result for a prior-alert row with the given count."""
    from datetime import UTC, datetime, timedelta

    r = MagicMock()
    r.mappings.return_value.first.return_value = {
        "alert_count": alert_count,
        "last_alert_at": datetime.now(UTC) - timedelta(minutes=10),
        "first_alert_at": datetime.now(UTC) - timedelta(minutes=10),
    }
    return r


def _insert_returning(alert_count: int) -> Any:
    """INSERT … RETURNING result with the given alert_count."""
    from datetime import UTC, datetime

    r = MagicMock()
    r.mappings.return_value.first.return_value = {
        "alert_count": alert_count,
        "first_alert_at": datetime.now(UTC),
    }
    return r


def _update_no_match() -> Any:
    """UPDATE … RETURNING with no rows matched (suppress branch)."""
    r = MagicMock()
    r.mappings.return_value.first.return_value = None
    return r


# ---------- _repeat_interval_for ----------------------------------


def test_repeat_interval_first_alert_is_30min():
    """alert_count=1 → next alert in 30 minutes. Pin so a refactor
    that bumps the constant changes the operator-facing cadence
    deliberately, not by accident."""
    from services.cron_alert_dedup import _repeat_interval_for

    assert _repeat_interval_for(1) == 30 * 60


def test_repeat_interval_subsequent_is_6h():
    """alert_count >= 2 → next alert in 6 hours. Matches PagerDuty's
    repeat cadence; keeps Slack quiet during a long outage."""
    from services.cron_alert_dedup import _repeat_interval_for

    assert _repeat_interval_for(2) == 6 * 60 * 60
    assert _repeat_interval_for(10) == 6 * 60 * 60


# ---------- should_emit_alert -------------------------------------


async def test_first_alert_emits_and_inserts(monkeypatch):
    """No prior row → INSERT + emit. The Slack message goes out
    on this tick."""
    from services import cron_alert_dedup as svc

    fake = _FakeSession()
    fake.push(_no_existing())  # SELECT
    fake.push(_insert_returning(1))  # INSERT … RETURNING

    monkeypatch.setattr(svc, "AdminSessionFactory", lambda: fake)

    out = await svc.should_emit_alert(cron_name="cron:weekly_report", kind="cron_failure")
    assert out["emit"] is True
    assert out["alert_count"] == 1
    # Two DB calls: SELECT then INSERT.
    assert len(fake.calls) == 2
    assert "INSERT INTO cron_alerts_sent" in fake.calls[1][0]


async def test_subsequent_alert_within_window_suppresses(monkeypatch):
    """Prior alert exists, within 30-minute window → suppress.
    Pin so a flat-interval regression that re-emits every tick
    would fail this test loudly."""
    from services import cron_alert_dedup as svc

    fake = _FakeSession()
    fake.push(_existing_alert(alert_count=1))  # SELECT
    fake.push(_update_no_match())  # UPDATE returns 0 rows (within window)

    monkeypatch.setattr(svc, "AdminSessionFactory", lambda: fake)

    out = await svc.should_emit_alert(cron_name="cron:weekly_report", kind="cron_failure")
    assert out["emit"] is False
    assert out["alert_count"] == 1


async def test_subsequent_alert_past_window_emits_and_bumps(monkeypatch):
    """Past the repeat interval → UPDATE matches, emit=True with
    bumped alert_count. The 'still failing' framing comes from the
    incremented counter."""
    from services import cron_alert_dedup as svc

    fake = _FakeSession()
    fake.push(_existing_alert(alert_count=1))  # SELECT
    fake.push(_insert_returning(2))  # UPDATE returns row w/ count=2

    monkeypatch.setattr(svc, "AdminSessionFactory", lambda: fake)

    out = await svc.should_emit_alert(cron_name="cron:weekly_report", kind="cron_failure")
    assert out["emit"] is True
    assert out["alert_count"] == 2


async def test_concurrent_insert_race_loser_suppresses(monkeypatch):
    """Two watchdogs race on the same fresh failure. ON CONFLICT DO
    NOTHING means one INSERT returns no row — that branch must
    suppress.

    Without this, both racers would emit and we'd double-alert on
    every fresh failure when two workers happen to tick within
    milliseconds of each other (deploy rollover, e.g.)."""
    from services import cron_alert_dedup as svc

    fake = _FakeSession()
    fake.push(_no_existing())  # SELECT — neither racer has the row yet
    fake.push(_update_no_match())  # INSERT … ON CONFLICT DO NOTHING returns 0 rows

    monkeypatch.setattr(svc, "AdminSessionFactory", lambda: fake)

    out = await svc.should_emit_alert(cron_name="cron:weekly_report", kind="cron_failure")
    assert out["emit"] is False


async def test_unknown_kind_raises_valueerror(monkeypatch):
    """Defensive — typo in caller code surfaces as a typed error,
    not silent suppression. Pin so a future refactor that adds a
    third kind without updating ALERT_KINDS fails loudly here."""
    from services import cron_alert_dedup as svc

    fake = _FakeSession()
    monkeypatch.setattr(svc, "AdminSessionFactory", lambda: fake)
    with pytest.raises(ValueError, match="unknown alert kind"):
        await svc.should_emit_alert(cron_name="cron:weekly_report", kind="bogus")


def test_alert_kinds_vocabulary_pinned():
    """ALERT_KINDS = {'cron_failure', 'cron_stuck'}. Pin so a refactor
    that adds a kind reminds the developer to update both this
    set AND `services.cron_alerts._KIND` constants."""
    from services.cron_alert_dedup import ALERT_KINDS

    assert ALERT_KINDS == frozenset({"cron_failure", "cron_stuck"})


# ---------- clear_alert ---------------------------------------------


async def test_clear_alert_returns_true_on_delete(monkeypatch):
    """Operator manually clears — DELETE row, return True. Used by
    the manual-clear admin flow (REPL-only for v1)."""
    from services import cron_alert_dedup as svc

    fake = _FakeSession()
    delete_result = MagicMock()
    delete_result.rowcount = 1
    fake.push(delete_result)
    monkeypatch.setattr(svc, "AdminSessionFactory", lambda: fake)

    out = await svc.clear_alert(cron_name="cron:weekly_report", kind="cron_failure")
    assert out is True


async def test_clear_alert_returns_false_when_no_row(monkeypatch):
    """No prior row → False (no-op). The caller knows there was
    nothing to clear."""
    from services import cron_alert_dedup as svc

    fake = _FakeSession()
    delete_result = MagicMock()
    delete_result.rowcount = 0
    fake.push(delete_result)
    monkeypatch.setattr(svc, "AdminSessionFactory", lambda: fake)

    out = await svc.clear_alert(cron_name="cron:weekly_report", kind="cron_failure")
    assert out is False
