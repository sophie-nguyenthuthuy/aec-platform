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
    organization_id: UUID | None = None,
    status: str = "sent",
    sent_to: list[UUID] | None = None,
    responses: list[dict[str, Any]] | None = None,
    deadline: date | None = None,
):
    """Mapping-style row stand-in mirroring `session.execute(...).mappings().all()`."""
    return {
        "id": rfq_id,
        # The audit emit added in T1.2 reads `organization_id` to
        # attribute the `costpulse.rfq.slots_expired` row to the
        # owning tenant.
        "organization_id": organization_id or uuid4(),
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
        # Populated by the `_fake_record` stub installed by the
        # `install_admin` fixture — one entry per audit emit.
        self.audit_calls: list[dict] = []

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
    """Wire the fake session in place of `AdminSessionFactory`.

    Also stubs `services.audit.record` so the cron's audit emit
    doesn't need to drive the full ORM (the fake session here is
    SELECT/UPDATE-only). The stub records the calls so tests can
    assert per-RFQ attribution.
    """

    def _install(rows: list[dict]) -> _FakeAdminSession:
        session = _FakeAdminSession(rows)
        # The cron does `from db.session import AdminSessionFactory`
        # inside the function body — patch the module the cron
        # actually imports.
        from db import session as db_session

        monkeypatch.setattr(db_session, "AdminSessionFactory", lambda: session)

        # Replace the audit writer with a recorder that just appends
        # the kwargs to a list on the session. This lets tests assert
        # `len(session.audit_calls) == N` and inspect the per-RFQ
        # before/after payloads without standing up the audit ORM.
        from services import audit as audit_mod

        async def _fake_record(_sess, **kwargs):
            session.audit_calls.append(kwargs)

        monkeypatch.setattr(audit_mod, "record", _fake_record)
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
    # No mutations → no audit emits either; the audit row only appears
    # when the cron actually changed something (matches the UPDATE-gating
    # condition in the cron body).
    assert session.audit_calls == []


async def test_audit_event_emitted_per_mutated_rfq_with_correct_diff(install_admin):
    """Each RFQ the cron mutates emits exactly one
    `costpulse.rfq.slots_expired` audit row, attributed to the RFQ's
    own `organization_id`, with a before/after diff that captures the
    status transition + count of slots flipped."""
    from workers.queue import rfq_deadlines_cron

    org_a, org_b = uuid4(), uuid4()
    rfq_a, rfq_b = uuid4(), uuid4()
    sup1, sup2, sup3 = uuid4(), uuid4(), uuid4()
    rows = [
        # Tenant A: no responses → status flips, 1 slot expires.
        _row(
            rfq_a,
            organization_id=org_a,
            status="sent",
            sent_to=[sup1],
            responses=[
                {"supplier_id": str(sup1), "status": "dispatched", "quote": None},
            ],
            deadline=date.today() - timedelta(days=2),
        ),
        # Tenant B: 1 responded + 1 dispatched → status held, 1 slot expires.
        _row(
            rfq_b,
            organization_id=org_b,
            status="responded",
            sent_to=[sup2, sup3],
            responses=[
                {"supplier_id": str(sup2), "status": "responded", "quote": {"total_vnd": "1", "line_items": []}},
                {"supplier_id": str(sup3), "status": "dispatched", "quote": None},
            ],
            deadline=date.today() - timedelta(days=2),
        ),
    ]
    session = install_admin(rows)

    await rfq_deadlines_cron(ctx={})

    # One audit emit per mutated RFQ. Per-tenant attribution lines up
    # with each row's own organization_id — RFQ A → org A, RFQ B → org B.
    assert len(session.audit_calls) == 2
    by_resource = {c["resource_id"]: c for c in session.audit_calls}

    a = by_resource[rfq_a]
    assert a["organization_id"] == org_a
    # Cron is the actor — both actor columns must end up NULL on the row.
    # The new `audit.record(..., auth=...)` signature derives that from
    # `auth=None`; asserting `auth is None` is the post-refactor
    # equivalent of the old `actor_user_id is None` check.
    assert a["auth"] is None
    assert a["action"] == "costpulse.rfq.slots_expired"
    assert a["resource_type"] == "rfq"
    assert a["before"] == {"status": "sent"}
    assert a["after"] == {"status": "expired", "expired_slot_count": 1}

    b = by_resource[rfq_b]
    assert b["organization_id"] == org_b
    assert b["before"] == {"status": "responded"}
    # Status held (some supplier responded) but one pending slot flipped.
    assert b["after"] == {"status": "responded", "expired_slot_count": 1}


async def test_audit_event_not_emitted_when_rfq_unchanged(install_admin):
    """When a deadline-passed RFQ already had every slot responded, the
    cron emits no UPDATE — and therefore no audit row. Otherwise we'd
    pollute the audit table with phantom "expired 0 slots" rows on every
    daily run."""
    from workers.queue import rfq_deadlines_cron

    rfq_id = uuid4()
    sup = uuid4()
    rows = [
        _row(
            rfq_id,
            status="responded",
            sent_to=[sup],
            responses=[
                {"supplier_id": str(sup), "status": "responded", "quote": {"total_vnd": "1", "line_items": []}},
            ],
            deadline=date.today() - timedelta(days=2),
        ),
    ]
    session = install_admin(rows)
    await rfq_deadlines_cron(ctx={})

    assert session.updates == []
    assert session.audit_calls == []
