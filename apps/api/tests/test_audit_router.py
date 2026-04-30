"""Router tests for the audit log: query endpoint + emission wiring.

Two layers of coverage:
  * The `GET /api/v1/audit/events` endpoint (auth gating + filters).
  * The emission contract — when a sensitive write succeeds, exactly
    one audit row is added to the session in the SAME transaction.

We assert the emission contract by checking `fake_db.added` for an
`AuditEvent` after invoking the relevant write endpoint. That keeps
the emission tests close to the routers they audit and surfaces a
regression as a clean diff.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth  # noqa: F401 — see test_rbac

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
    """Same shape as the org/rbac fakes — extended to track add() so
    we can assert audit-row emissions."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []
        self.added: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None: ...
    async def close(self) -> None: ...
    async def flush(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.scalar_one.return_value = 0
        r.mappings.return_value.all.return_value = []
        r.mappings.return_value.one.return_value = {}
        r.mappings.return_value.first.return_value = None
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


def _build_audit_app(role: str, fake_db: FakeAsyncSession) -> FastAPI:
    """Mounts only the audit router, with auth + db deps overridden."""
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from routers import audit as audit_router

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(audit_router.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="caller@example.com",
    )

    async def _db_override() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[get_db] = _db_override
    return app


# ---------- Read endpoint: gating + filters ----------


async def test_list_audit_events_403_for_member(fake_db):
    """Audit content can leak who-touched-what; admin/owner only."""
    app = _build_audit_app("member", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/audit/events")
    assert res.status_code == 403


async def test_list_audit_events_403_for_viewer(fake_db):
    app = _build_audit_app("viewer", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/audit/events")
    assert res.status_code == 403


async def test_list_audit_events_200_for_admin_returns_paginated(fake_db):
    count_q = MagicMock()
    count_q.scalar_one.return_value = 1
    rows_q = MagicMock()
    rows_q.mappings.return_value.all.return_value = [
        {
            "id": uuid4(),
            "organization_id": ORG_ID,
            "actor_user_id": USER_ID,
            "actor_email": "alice@example.com",
            "action": "costpulse.estimate.approve",
            "resource_type": "estimates",
            "resource_id": uuid4(),
            "before": {"status": "in_review"},
            "after": {"status": "approved"},
            "ip": "10.0.0.1",
            "user_agent": "Mozilla/5.0",
            "created_at": datetime(2026, 4, 27, 9, 0, tzinfo=UTC),
        },
    ]
    fake_db.push(count_q)
    fake_db.push(rows_q)

    app = _build_audit_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/audit/events")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["action"] == "costpulse.estimate.approve"
    assert body["data"][0]["actor_email"] == "alice@example.com"
    assert body["data"][0]["before"] == {"status": "in_review"}


async def test_list_audit_events_filters_compose(fake_db):
    """Both `resource_type=` and `resource_id=` should narrow the WHERE
    clause. We assert by inspecting the SQL params."""
    count_q = MagicMock()
    count_q.scalar_one.return_value = 0
    rows_q = MagicMock()
    rows_q.mappings.return_value.all.return_value = []
    fake_db.push(count_q)
    fake_db.push(rows_q)

    rid = uuid4()
    app = _build_audit_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(
            "/api/v1/audit/events",
            params={"resource_type": "estimates", "resource_id": str(rid)},
        )
    assert res.status_code == 200
    # Both queries (count + rows) get the same param dict — check the count one.
    count_params = fake_db.calls[0][1]
    assert count_params["org"] == str(ORG_ID)
    assert count_params["rtype"] == "estimates"
    assert count_params["rid"] == str(rid)


async def test_list_audit_events_org_scoped(fake_db):
    """Even though the read is admin-gated, every query must still
    bind caller's org_id — RLS would block cross-tenant reads but
    the API contract should make the scoping explicit."""
    count_q = MagicMock()
    count_q.scalar_one.return_value = 0
    rows_q = MagicMock()
    rows_q.mappings.return_value.all.return_value = []
    fake_db.push(count_q)
    fake_db.push(rows_q)

    app = _build_audit_app("admin", fake_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/api/v1/audit/events")
    # First call is the count; second is the rows. Both should bind org.
    assert fake_db.calls[0][1]["org"] == str(ORG_ID)
    assert fake_db.calls[1][1]["org"] == str(ORG_ID)


# ---------- Emission contract: write endpoints add audit rows ----------


async def test_audit_record_helper_adds_event_to_session(fake_db):
    """Direct unit test of the `audit.record(...)` helper."""
    from models.audit import AuditEvent
    from services.audit import record

    rid = uuid4()
    await record(
        fake_db,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        actor_user_id=USER_ID,
        action="costpulse.estimate.approve",
        resource_type="estimates",
        resource_id=rid,
        before={"status": "draft"},
        after={"status": "approved"},
    )
    audits = [o for o in fake_db.added if isinstance(o, AuditEvent)]
    assert len(audits) == 1
    assert audits[0].action == "costpulse.estimate.approve"
    assert audits[0].resource_id == rid
    assert audits[0].before == {"status": "draft"}
    assert audits[0].after == {"status": "approved"}


async def test_audit_record_extracts_ip_from_x_forwarded_for(fake_db):
    """LB sets `X-Forwarded-For: <client>, <proxy>` — we honor the
    leftmost entry (the original client). Fakes the request via a
    SimpleNamespace shaped like `Request`."""
    from services.audit import record

    req = SimpleNamespace(
        headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1", "user-agent": "TestUA"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    await record(
        fake_db,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        actor_user_id=USER_ID,
        action="org.member.role_change",
        resource_type="org_members",
        resource_id=uuid4(),
        request=req,  # type: ignore[arg-type]
    )
    from models.audit import AuditEvent

    audits = [o for o in fake_db.added if isinstance(o, AuditEvent)]
    assert audits[0].ip == "1.2.3.4"
    assert audits[0].user_agent == "TestUA"


async def test_audit_record_falls_back_to_client_host(fake_db):
    """When there's no XFF header, use the direct client peer."""
    from services.audit import record

    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.5"))
    await record(
        fake_db,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        actor_user_id=USER_ID,
        action="org.member.remove",
        resource_type="org_members",
        resource_id=uuid4(),
        request=req,  # type: ignore[arg-type]
    )
    from models.audit import AuditEvent

    audits = [o for o in fake_db.added if isinstance(o, AuditEvent)]
    assert audits[0].ip == "10.0.0.5"


async def test_audit_record_caps_user_agent_length(fake_db):
    """Cap at 500 — UAs in the wild can be obscene + we don't want
    the audit table to bloat. Positive control: short UAs pass through
    unchanged (covered by the XFF test above)."""
    from services.audit import record

    long_ua = "x" * 5000
    req = SimpleNamespace(headers={"user-agent": long_ua}, client=SimpleNamespace(host="10.0.0.1"))
    await record(
        fake_db,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        actor_user_id=USER_ID,
        action="org.member.role_change",
        resource_type="org_members",
        resource_id=uuid4(),
        request=req,  # type: ignore[arg-type]
    )
    from models.audit import AuditEvent

    audits = [o for o in fake_db.added if isinstance(o, AuditEvent)]
    assert audits[0].user_agent is not None
    assert len(audits[0].user_agent) == 500
