"""Integration smoke for SiteEye → DailyLog cross-module wiring.

Confirms two contracts of `_create_safety_incidents`:

  1. Each violation triggers an INSERT INTO safety_incidents *with*
     a RETURNING clause — the row is needed to call the sync helper.
  2. Each returned row is handed off to `sync_incident_to_dailylog`
     with the originating organization_id (so RLS plus the daily-log
     stub-creation works tenant-scoped).

A failure inside the sync MUST NOT propagate — the safety incident
itself is the safety-critical write and must persist regardless.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")
PHOTO_ID = UUID("44444444-4444-4444-4444-444444444444")


class _RecordingSession:
    """Returns a queueable result for each execute() call. Tracks every
    statement that was issued so we can spot the RETURNING and the sync's
    follow-up reads/writes."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, dict]] = []
        self._queue: list[Any] = []

    def push(self, result: Any) -> None:
        self._queue.append(result)

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        self.executes.append((str(stmt), params or {}))
        if self._queue:
            return self._queue.pop(0)
        r = MagicMock()
        r.one_or_none.return_value = None
        r.scalar_one.return_value = 0
        return r

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


def _result_returning(row: SimpleNamespace) -> MagicMock:
    r = MagicMock()
    r.one.return_value = row
    r.one_or_none.return_value = row
    return r


@pytest.fixture
def patch_session(monkeypatch):
    s = _RecordingSession()

    class _Fake:
        def __init__(self, _o: Any) -> None: ...
        async def __aenter__(self):
            return s

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr("ml.pipelines.siteeye.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def patch_sync(monkeypatch):
    """Stub the dailylog_sync module so the inline import in the pipeline
    doesn't drag the real one (which would issue more SQL we'd have to mock)."""
    mod = ModuleType("services.dailylog_sync")
    mod.sync_incident_to_dailylog = AsyncMock(return_value={"id": uuid4()})
    if "services" not in sys.modules:
        monkeypatch.setitem(sys.modules, "services", ModuleType("services"))
    monkeypatch.setitem(sys.modules, "services.dailylog_sync", mod)
    return mod


def _violation(label: str = "no_hard_hat") -> Any:
    from schemas.siteeye import PhotoDetection

    return PhotoDetection(label=label, confidence=0.92, bbox=[10, 20, 100, 200])


def _state() -> Any:
    from ml.pipelines.siteeye import PhotoState

    return PhotoState(
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        photo_id=PHOTO_ID,
    )


# ============================================================================


async def test_create_safety_incidents_calls_sync_per_violation(patch_session, patch_sync):
    from ml.pipelines.siteeye import _create_safety_incidents

    iid_a, iid_b = uuid4(), uuid4()
    # Two violations → two RETURNING rows
    patch_session.push(
        _result_returning(
            SimpleNamespace(
                id=iid_a,
                project_id=PROJECT_ID,
                detected_at=None,  # the helper coerces None → today
                severity="high",
                incident_type="no_ppe",
                ai_description="Worker without hard hat detected",
            )
        )
    )
    patch_session.push(
        _result_returning(
            SimpleNamespace(
                id=iid_b,
                project_id=PROJECT_ID,
                detected_at=None,
                severity="medium",
                incident_type="no_ppe",
                ai_description="Worker without safety vest detected",
            )
        )
    )

    await _create_safety_incidents(_state(), [_violation("no_hard_hat"), _violation("no_vest")])

    # Two INSERTs ran, both with RETURNING clauses.
    insert_stmts = [s for s, _ in patch_session.executes if "INSERT INTO safety_incidents" in s]
    assert len(insert_stmts) == 2
    for stmt in insert_stmts:
        assert "RETURNING" in stmt

    # Sync was called for each, with the org id that owns this PhotoState.
    assert patch_sync.sync_incident_to_dailylog.await_count == 2
    for call in patch_sync.sync_incident_to_dailylog.await_args_list:
        kwargs = call.kwargs
        assert kwargs["organization_id"] == ORG_ID
        # Either dict or SimpleNamespace is fine; sync helper accepts both.
        inc = kwargs["incident"]
        assert getattr(inc, "id", None) in (iid_a, iid_b)


async def test_sync_failure_does_not_break_incident_persistence(patch_session, patch_sync):
    """If the dailylog sync raises (e.g. observation table missing in old
    deployments), the safety incident itself was already INSERTed and must
    stay committed. The pipeline catches & logs."""
    from ml.pipelines.siteeye import _create_safety_incidents

    patch_session.push(
        _result_returning(
            SimpleNamespace(
                id=uuid4(),
                project_id=PROJECT_ID,
                detected_at=None,
                severity="critical",
                incident_type="fire_hazard",
                ai_description="Fire hazard detected",
            )
        )
    )
    patch_sync.sync_incident_to_dailylog.side_effect = RuntimeError("table missing")

    # Must NOT raise.
    await _create_safety_incidents(_state(), [_violation("fire_hazard")])

    # Both calls happened (the INSERT before the failing sync).
    insert_stmts = [s for s, _ in patch_session.executes if "INSERT INTO safety_incidents" in s]
    assert len(insert_stmts) == 1
    patch_sync.sync_incident_to_dailylog.assert_awaited_once()
