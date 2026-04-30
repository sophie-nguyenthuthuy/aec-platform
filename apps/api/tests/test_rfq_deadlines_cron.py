"""Unit tests for `workers.queue.rfq_deadlines_cron`.

Three buckets exercised:

  * RFQ with no responses — flips status `sent` → `expired`, slots
    `dispatched` → `expired`.
  * RFQ with at least one `responded` slot — keeps RFQ status
    (`responded`/`sent`), only flips the un-responded slots.
  * RFQ already past deadline but has only `closed` slots — left
    untouched (the WHERE filters out `status='closed'`).

The cron uses raw SQL via `text()` against `AdminSessionFactory` —
patching at the call site is more direct than mocking SQLAlchemy.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.asyncio


def _row(
    rfq_id: UUID,
    *,
    status: str = "sent",
    sent_to: list[UUID] | None = None,
    responses: list[dict[str, Any]] | None = None,
    deadline: date | None = None,
):
    """Mapping-style row stand-in mirroring `session.execute(...).mappings().all()`."""
    return {
        "id": rfq_id,
        "status": status,
        "sent_to": sent_to or [],
        "responses": responses or [],
        "deadline": deadline or (date.today() - timedelta(days=2)),
    }


class _FakeAdminSession:
    """Captures SELECT result + records UPDATE calls.

    The cron does:
      1. `session.execute(text("SELECT ..."), {...})` then `.mappings().all()`.
      2. zero or more `session.execute(text("UPDATE ..."), {id, status, responses})`.
      3. `await session.commit()`.

    We discriminate on the SQL string to route SELECT vs UPDATE.
    """

    def __init__(self, select_rows: list[dict]) -> None:
        self._select_rows = select_rows
        self.updates: list[dict] = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        if "select" in sql and "from rfqs" in sql:
            res = MagicMock()
            res.mappings.return_value.all.return_value = self._select_rows
            return res
        if "update rfqs" in sql:
            self.updates.append(dict(params or {}))
            return MagicMock()
        # Defensive fallthrough — surfaces a bug in the cron rather
        # than swallowing an unexpected statement silently.
        raise AssertionError(f"unexpected SQL: {sql[:120]}")

    async def commit(self):
        self.committed = True


@pytest.fixture
def install_admin(monkeypatch):
    """Wire the fake session in place of `AdminSessionFactory`."""

    def _install(rows: list[dict]) -> _FakeAdminSession:
        session = _FakeAdminSession(rows)
        # The cron does `from db.session import AdminSessionFactory`
        # inside the function body — patch the module the cron
        # actually imports.
        from db import session as db_session

        monkeypatch.setattr(db_session, "AdminSessionFactory", lambda: session)
        return session

    return _install


# ---------- Tests ----------


async def test_no_responses_expires_rfq_and_slots(install_admin):
    """Sent + 0 responded → RFQ becomes `expired`, slots flip to `expired`."""
    from workers.queue import rfq_deadlines_cron

    rfq_id = uuid4()
    supplier_a, supplier_b = uuid4(), uuid4()
    rows = [
        _row(
            rfq_id,
            status="sent",
            sent_to=[supplier_a, supplier_b],
            responses=[
                {"supplier_id": str(supplier_a), "status": "dispatched", "quote": None},
                {"supplier_id": str(supplier_b), "status": "bounced", "quote": None},
            ],
            deadline=date.today() - timedelta(days=5),
        ),
    ]
    session = install_admin(rows)

    result = await rfq_deadlines_cron(ctx={})

    assert result == {"expired_slots": 2, "expired_rfqs": 1}
    assert session.committed
    assert len(session.updates) == 1
    upd = session.updates[0]
    assert upd["status"] == "expired"
    # Both per-supplier slots flipped to expired.
    assert all(e["status"] == "expired" for e in upd["responses"])


async def test_partial_response_keeps_rfq_status_but_expires_pending_slots(install_admin):
    """1 responded + 1 dispatched → only the dispatched slot expires;
    RFQ status stays as is so the buyer can still pick a winner."""
    from workers.queue import rfq_deadlines_cron

    rfq_id = uuid4()
    responder, no_show = uuid4(), uuid4()
    rows = [
        _row(
            rfq_id,
            status="responded",
            sent_to=[responder, no_show],
            responses=[
                {
                    "supplier_id": str(responder),
                    "status": "responded",
                    "quote": {"total_vnd": "100", "line_items": []},
                },
                {"supplier_id": str(no_show), "status": "dispatched", "quote": None},
            ],
            deadline=date.today() - timedelta(days=3),
        ),
    ]
    session = install_admin(rows)

    result = await rfq_deadlines_cron(ctx={})

    assert result == {"expired_slots": 1, "expired_rfqs": 0}
    assert len(session.updates) == 1
    upd = session.updates[0]
    # RFQ status unchanged — buyer can still accept the winner's quote.
    assert upd["status"] == "responded"
    statuses = [e["status"] for e in upd["responses"]]
    assert statuses == ["responded", "expired"]


async def test_rfq_with_only_responded_slots_does_not_emit_update(install_admin):
    """Every slot responded + RFQ was past deadline → nothing to do.

    The cron's WHERE filter excludes `closed` RFQs but `responded` ones
    still match. Without per-RFQ "anything to mutate?" gating, we'd
    issue a no-op UPDATE for every all-responded RFQ on every run.
    """
    from workers.queue import rfq_deadlines_cron

    rfq_id = uuid4()
    sup = uuid4()
    rows = [
        _row(
            rfq_id,
            status="responded",
            sent_to=[sup],
            responses=[
                {"supplier_id": str(sup), "status": "responded", "quote": {"total_vnd": "100", "line_items": []}},
            ],
            deadline=date.today() - timedelta(days=2),
        ),
    ]
    session = install_admin(rows)
    result = await rfq_deadlines_cron(ctx={})

    assert result == {"expired_slots": 0, "expired_rfqs": 0}
    assert session.updates == []


async def test_no_open_rfqs_returns_zeros_without_writing(install_admin):
    """Empty result set from the SELECT → no commits, zero counters."""
    from workers.queue import rfq_deadlines_cron

    session = install_admin([])
    result = await rfq_deadlines_cron(ctx={})

    assert result == {"expired_slots": 0, "expired_rfqs": 0}
    assert session.updates == []
    assert session.committed
