"""Unit tests for the SiteEye → DailyLog sync service.

These exercise the deterministic logic (severity coercion, dict/ORM-row
shape handling, idempotency check) with a queued-result fake session. The
SQL itself is integration-level and lives outside this file.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from services.dailylog_sync import (
    _normalise_severity,
    sync_incident_to_dailylog,
)

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")


class _Session:
    def __init__(self) -> None:
        self._queue: list[Any] = []
        self.executes: list[Any] = []

    def queue(self, result: Any) -> None:
        self._queue.append(result)

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        self.executes.append((_a, _k))
        if self._queue:
            return self._queue.pop(0)
        return MagicMock(one=MagicMock(return_value=None), one_or_none=MagicMock(return_value=None))


def _row(**fields: Any) -> SimpleNamespace:
    return SimpleNamespace(_mapping=fields, **fields)


def _scalar(v: Any) -> MagicMock:
    r = MagicMock()
    r.one.return_value = SimpleNamespace(id=v) if not hasattr(v, "id") else v
    r.one_or_none.return_value = SimpleNamespace(id=v) if not hasattr(v, "id") else v
    return r


# ---------- Severity coercion ----------


def test_severity_known_values_pass_through():
    assert _normalise_severity("low") == "low"
    assert _normalise_severity("MEDIUM") == "medium"
    assert _normalise_severity("high") == "high"
    assert _normalise_severity("critical") == "critical"


def test_severity_synonyms_map_correctly():
    assert _normalise_severity("info") == "low"
    assert _normalise_severity("warning") == "medium"
    assert _normalise_severity("major") == "high"
    assert _normalise_severity("emergency") == "critical"


def test_severity_unknown_falls_back_to_medium():
    assert _normalise_severity(None) == "medium"
    assert _normalise_severity("") == "medium"
    assert _normalise_severity("nonsense") == "medium"


# ---------- Sync ----------


async def test_skips_incident_without_project_id():
    s = _Session()
    inc = {
        "id": uuid4(),
        "project_id": None,
        "detected_at": datetime(2026, 4, 26, tzinfo=UTC),
        "severity": "high",
    }
    out = await sync_incident_to_dailylog(s, organization_id=ORG_ID, incident=inc)
    assert out is None
    assert s.executes == []  # no SQL fired


async def test_idempotent_when_observation_already_exists():
    s = _Session()
    incident_id = uuid4()
    log_id = uuid4()
    # 1st: ensure_daily_log → returns log_id
    s.queue(_scalar(log_id))
    # 2nd: idempotency SELECT → already exists
    existing = MagicMock()
    existing.one_or_none.return_value = SimpleNamespace(id=uuid4())
    s.queue(existing)

    inc = {
        "id": incident_id,
        "project_id": PROJECT_ID,
        "detected_at": datetime(2026, 4, 26, 10, 30, tzinfo=UTC),
        "severity": "high",
        "incident_type": "PPE missing",
        "ai_description": "Worker without hard hat",
    }
    out = await sync_incident_to_dailylog(s, organization_id=ORG_ID, incident=inc)
    assert out is None
    # Two queries: ensure_daily_log + idempotency check. No INSERT.
    assert len(s.executes) == 2


async def test_inserts_observation_when_new():
    s = _Session()
    incident_id = uuid4()
    log_id = uuid4()
    obs_id = uuid4()

    # 1: ensure_daily_log
    s.queue(_scalar(log_id))
    # 2: idempotency SELECT (none)
    existing = MagicMock()
    existing.one_or_none.return_value = None
    s.queue(existing)
    # 3: INSERT observation RETURNING
    insert_row = MagicMock()
    obs_row = SimpleNamespace(
        _mapping={
            "id": obs_id,
            "log_id": log_id,
            "kind": "safety",
            "severity": "high",
            "source": "siteeye_hit",
            "related_safety_incident_id": incident_id,
        },
    )
    insert_row.one.return_value = obs_row
    s.queue(insert_row)

    inc = {
        "id": incident_id,
        "project_id": PROJECT_ID,
        "detected_at": datetime(2026, 4, 26, 10, 30, tzinfo=UTC),
        "severity": "high",
        "incident_type": "PPE missing",
        "ai_description": "Worker without hard hat detected near zone B",
    }
    out = await sync_incident_to_dailylog(s, organization_id=ORG_ID, incident=inc)
    assert out is not None
    assert out["kind"] == "safety"
    assert out["severity"] == "high"
    assert out["source"] == "siteeye_hit"
    assert out["related_safety_incident_id"] == incident_id


async def test_handles_orm_style_input():
    """Accept a SimpleNamespace/ORM row, not just a dict."""
    s = _Session()
    s.queue(_scalar(uuid4()))
    existing = MagicMock()
    existing.one_or_none.return_value = SimpleNamespace(id=uuid4())  # treat as exists
    s.queue(existing)

    inc = SimpleNamespace(
        id=uuid4(),
        project_id=PROJECT_ID,
        detected_at=datetime(2026, 4, 26, tzinfo=UTC),
        severity="medium",
        incident_type=None,
        ai_description=None,
    )
    # Should not raise even though `inc` is not a dict.
    await sync_incident_to_dailylog(s, organization_id=ORG_ID, incident=inc)


async def test_log_date_falls_back_to_today_when_detected_at_missing():
    s = _Session()
    s.queue(_scalar(uuid4()))
    existing = MagicMock()
    existing.one_or_none.return_value = SimpleNamespace(id=uuid4())
    s.queue(existing)

    inc = {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "detected_at": None,
        "severity": None,
    }
    # Just confirm it doesn't crash on missing detected_at.
    await sync_incident_to_dailylog(s, organization_id=ORG_ID, incident=inc)


def test_date_coercion_accepts_date_and_datetime():
    """Pure-function check on the helper used internally."""
    from services.dailylog_sync import _coerce_log_date

    today = date(2026, 4, 26)
    assert _coerce_log_date(today) == today
    assert _coerce_log_date(datetime(2026, 4, 26, 9, 0, tzinfo=UTC)) == today
