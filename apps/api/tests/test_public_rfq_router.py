"""Router tests for the public no-auth RFQ supplier portal.

Mounts only `routers.public_rfq` and replaces `AdminSessionFactory`
inside the router module with a stub-driven fake. We never start a real
DB or Redis; the goal is to pin the contract:

  * 401 on missing / tampered / expired / wrong-audience tokens.
  * 404 when the RFQ row is gone.
  * 401 when the token's supplier_id isn't on `rfq.sent_to`.
  * 200 with the correct shape on the happy path (context + respond).
  * Submission writes the quote into `rfq.responses[]`, advances status,
    and is idempotent (a second submission overwrites the slot).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services import rate_limit
from services.rfq_tokens import mint_response_token

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Each test gets a fresh per-token bucket so caps don't leak across tests."""
    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
RFQ_ID = UUID("33333333-3333-3333-3333-333333333333")
SUPPLIER_ID = UUID("44444444-4444-4444-4444-444444444444")
OTHER_SUPPLIER_ID = UUID("55555555-5555-5555-5555-555555555555")
ESTIMATE_ID = UUID("66666666-6666-6666-6666-666666666666")
PROJECT_ID = UUID("77777777-7777-7777-7777-777777777777")


# ---------- A queue-driven fake session ----------


class FakeAsyncSession:
    """Returns programmed values for `.execute(...).scalar_one_or_none()` and friends.

    Each call to `execute` pops the next entry from `_results`. Keeps the
    test bodies declarative — push the values you expect the router to
    fetch in order, then assert.
    """

    def __init__(self) -> None:
        self._results: list[Any] = []
        self.committed = False

    def push(self, value: Any) -> None:
        self._results.append(value)

    def add(self, obj: Any) -> None:  # pragma: no cover — public router never adds
        pass

    async def commit(self) -> None:
        self.committed = True

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        result = MagicMock()
        scalar = self._results.pop(0) if self._results else None
        result.scalar_one_or_none.return_value = scalar
        # `.scalars().all()` for the BoqItem fetch — push lists for those.
        if isinstance(scalar, list):
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = scalar
            result.scalars.return_value = scalars_mock
            # When we pop a list, it was meant for the .scalars().all() path,
            # so scalar_one_or_none should NOT also return that list.
            result.scalar_one_or_none.return_value = None
        else:
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = []
            result.scalars.return_value = scalars_mock
        return result


@pytest.fixture
def fake_session() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture
def app(monkeypatch, fake_session) -> FastAPI:
    """Mount only the public RFQ router with `AdminSessionFactory` stubbed."""
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from routers import public_rfq

    class _FactoryStub:
        def __call__(self):
            return self

        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(public_rfq, "AdminSessionFactory", _FactoryStub())

    # `flag_modified` requires a real ORM instance. The router calls it
    # to tell SQLAlchemy that an in-place JSONB list mutation needs to
    # be flushed; in tests we use SimpleNamespace stand-ins, so neuter
    # the call. The mutation itself (the only thing we assert on) has
    # already happened by this point.
    monkeypatch.setattr(public_rfq, "flag_modified", lambda *a, **k: None)

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(public_rfq.router)
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Helpers ----------


def _rfq_row(**overrides: Any):
    """Plain SimpleNamespace stand-in for an Rfq ORM row.

    `MagicMock` doesn't work cleanly for the row because we mutate
    `responses` and `status` from inside the router, and assert on those
    mutations from the test. SimpleNamespace gives us regular attribute
    semantics with no auto-spec'd magic.
    """
    base = dict(
        id=RFQ_ID,
        organization_id=ORG_ID,
        project_id=None,
        estimate_id=None,
        status="sent",
        sent_to=[SUPPLIER_ID],
        responses=[
            {
                "supplier_id": str(SUPPLIER_ID),
                "status": "dispatched",
                "dispatched_at": "2026-04-25T12:00:00+00:00",
                "delivery": {"to": "x@y", "subject": "s", "delivered": True, "reason": None},
                "quote": None,
            }
        ],
        deadline=date(2026, 5, 30),
        created_at=datetime.now(UTC),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _org_row(name: str = "ACME Construction"):
    # Use SimpleNamespace — MagicMock special-cases the `name` kwarg so
    # `MagicMock(name="ACME").name` returns "<MagicMock name='ACME.name'>"
    # rather than the string we set, which Pydantic rejects.
    return SimpleNamespace(id=ORG_ID, name=name)


def _project_row(name: str = "Tower X"):
    return SimpleNamespace(id=PROJECT_ID, name=name)


def _estimate_row(name: str = "Schematic v1"):
    return SimpleNamespace(id=ESTIMATE_ID, name=name)


def _supplier_row():
    return SimpleNamespace(id=SUPPLIER_ID)


def _boq_line(material_code: str, description: str, quantity: float, unit: str, sort_order: int):
    return SimpleNamespace(
        material_code=material_code,
        description=description,
        quantity=quantity,
        unit=unit,
        sort_order=sort_order,
    )


def _good_token() -> str:
    return mint_response_token(rfq_id=RFQ_ID, supplier_id=SUPPLIER_ID)


# ---------- /context ----------


async def test_context_401_on_missing_token(client: AsyncClient):
    resp = await client.get("/api/v1/public/rfq/context")
    # FastAPI returns 422 when the required query param is missing — that's
    # before we even reach our handler. The 401 path requires a token in
    # the URL but bad.
    assert resp.status_code == 422


async def test_context_401_on_garbage_token(client: AsyncClient):
    resp = await client.get("/api/v1/public/rfq/context?t=not-a-jwt")
    assert resp.status_code == 401
    body = resp.json()
    assert body["errors"][0]["message"] == "Invalid or expired link"


async def test_context_404_when_rfq_missing(client: AsyncClient, fake_session):
    fake_session.push(None)  # rfq lookup returns nothing
    resp = await client.get(f"/api/v1/public/rfq/context?t={_good_token()}")
    assert resp.status_code == 404


async def test_context_401_when_supplier_not_on_sent_to(client: AsyncClient, fake_session):
    rfq = _rfq_row(sent_to=[OTHER_SUPPLIER_ID])  # token's supplier isn't on sent_to
    fake_session.push(rfq)
    resp = await client.get(f"/api/v1/public/rfq/context?t={_good_token()}")
    assert resp.status_code == 401


async def test_context_happy_path_with_estimate_and_boq(client: AsyncClient, fake_session):
    """Full context with a linked estimate + BOQ digest."""
    boq_lines = [
        _boq_line("CONC_C30", "Bê tông C30", 120, "m3", 1),
        _boq_line("REBAR_CB500", "Thép CB500", 8500, "kg", 2),
    ]
    fake_session.push(_rfq_row(estimate_id=ESTIMATE_ID, project_id=PROJECT_ID))
    fake_session.push(_org_row("ACME Construction"))
    fake_session.push(_project_row("Tower X"))
    fake_session.push(_estimate_row("Schematic v1"))
    fake_session.push(boq_lines)  # consumed by .scalars().all()

    resp = await client.get(f"/api/v1/public/rfq/context?t={_good_token()}")
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert data["organization_name"] == "ACME Construction"
    assert data["project_name"] == "Tower X"
    assert data["estimate_name"] == "Schematic v1"
    assert data["deadline"] == "2026-05-30"
    assert data["submission_status"] == "pending"
    assert data["submitted_quote"] is None
    assert len(data["boq_digest"]) == 2
    assert data["boq_digest"][0]["material_code"] == "CONC_C30"


async def test_context_reports_submitted_status_when_quote_exists(client: AsyncClient, fake_session):
    """If `responses[i].quote` is non-null, the form must be hidden."""
    rfq = _rfq_row(
        responses=[
            {
                "supplier_id": str(SUPPLIER_ID),
                "status": "responded",
                "quote": {"total_vnd": "12500000", "lead_time_days": 14, "line_items": []},
            }
        ]
    )
    fake_session.push(rfq)
    fake_session.push(_org_row("ACME"))
    resp = await client.get(f"/api/v1/public/rfq/context?t={_good_token()}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["submission_status"] == "submitted"
    assert data["submitted_quote"]["total_vnd"] == "12500000"


# ---------- /respond ----------


async def test_respond_401_on_garbage_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/public/rfq/respond?t=not-a-jwt",
        json={"total_vnd": "1000000", "lead_time_days": 7, "line_items": []},
    )
    assert resp.status_code == 401


async def test_respond_404_when_rfq_missing(client: AsyncClient, fake_session):
    fake_session.push(None)
    resp = await client.post(
        f"/api/v1/public/rfq/respond?t={_good_token()}",
        json={"total_vnd": "1000000", "line_items": []},
    )
    assert resp.status_code == 404


async def test_respond_writes_quote_into_responses_slot(client: AsyncClient, fake_session):
    """Happy path: existing supplier slot gets `quote`, status moves to "responded"."""
    rfq = _rfq_row()
    fake_session.push(rfq)  # rfq lookup
    fake_session.push(_supplier_row())  # supplier sanity check

    payload = {
        "total_vnd": "12500000",
        "lead_time_days": 14,
        "valid_until": "2026-06-15",
        "notes": "FOB Hanoi, payment NET-30",
        "line_items": [
            {
                "material_code": "CONC_C30",
                "description": "Concrete C30",
                "quantity": 120,
                "unit": "m3",
                "unit_price_vnd": "2050000",
            }
        ],
    }
    resp = await client.post(f"/api/v1/public/rfq/respond?t={_good_token()}", json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"status": "received"}

    # The router mutates the rfq object in place. Inspect the slot.
    assert len(rfq.responses) == 1
    slot = rfq.responses[0]
    assert slot["status"] == "responded"
    assert "responded_at" in slot
    assert slot["quote"]["total_vnd"] == "12500000"
    assert slot["quote"]["lead_time_days"] == 14
    assert slot["quote"]["line_items"][0]["material_code"] == "CONC_C30"
    # Buyer-side state machine: "sent" → "responded" on first quote.
    assert rfq.status == "responded"
    assert fake_session.committed is True


async def test_respond_creates_slot_when_dispatcher_did_not(client: AsyncClient, fake_session):
    """If `responses` had no entry for this supplier, /respond must create one."""
    rfq = _rfq_row(responses=[])  # dispatcher didn't run yet
    fake_session.push(rfq)
    fake_session.push(_supplier_row())

    resp = await client.post(
        f"/api/v1/public/rfq/respond?t={_good_token()}",
        json={"total_vnd": "999000", "line_items": []},
    )
    assert resp.status_code == 200
    assert len(rfq.responses) == 1
    assert rfq.responses[0]["supplier_id"] == str(SUPPLIER_ID)
    assert rfq.responses[0]["quote"]["total_vnd"] == "999000"


async def test_respond_is_idempotent_overwriting_existing_quote(client: AsyncClient, fake_session):
    """A supplier resubmitting must overwrite their slot, not append."""
    rfq = _rfq_row(
        responses=[
            {
                "supplier_id": str(SUPPLIER_ID),
                "status": "responded",
                "quote": {"total_vnd": "1000000", "lead_time_days": 7, "line_items": []},
            }
        ]
    )
    fake_session.push(rfq)
    fake_session.push(_supplier_row())

    resp = await client.post(
        f"/api/v1/public/rfq/respond?t={_good_token()}",
        json={"total_vnd": "1500000", "lead_time_days": 5, "line_items": []},
    )
    assert resp.status_code == 200
    assert len(rfq.responses) == 1, "must not append a second slot"
    assert rfq.responses[0]["quote"]["total_vnd"] == "1500000"
    assert rfq.responses[0]["quote"]["lead_time_days"] == 5


async def test_respond_rejects_unknown_field_in_quote(client: AsyncClient):
    """`extra='forbid'` on PublicRfqQuote must reject hand-crafted extra fields.

    A supplier portal payload with `evil_admin: true` shouldn't silently
    leak through — it'd be a sign someone is probing for a way to escalate
    the schema. 422 makes the failure visible.
    """
    resp = await client.post(
        f"/api/v1/public/rfq/respond?t={_good_token()}",
        json={"total_vnd": "1000000", "evil_admin": True, "line_items": []},
    )
    assert resp.status_code == 422


# ---------- Rate limiting ----------


async def test_context_endpoint_returns_429_after_cap(client: AsyncClient):
    """11th GET on the same `?t=` value within a minute must 429.

    Token is garbage so verification will 401 — but the rate limit fires
    BEFORE verification, so we hit the 429 first regardless of whether
    the token would have validated.
    """
    token = "garbage-but-stable-token"
    # Capacity is 10 for /context. First 10 spend the bucket on 401s.
    for _ in range(10):
        r = await client.get(f"/api/v1/public/rfq/context?t={token}")
        assert r.status_code == 401, r.text
    # 11th hits the empty bucket.
    r = await client.get(f"/api/v1/public/rfq/context?t={token}")
    assert r.status_code == 429
    assert r.headers.get("Retry-After") == "60"


async def test_respond_endpoint_returns_429_after_cap(client: AsyncClient):
    """6th POST within a minute must 429 (cap=5)."""
    token = "another-garbage-token"
    payload = {"total_vnd": "1000000", "line_items": []}
    for _ in range(5):
        r = await client.post(f"/api/v1/public/rfq/respond?t={token}", json=payload)
        assert r.status_code == 401, r.text
    r = await client.post(f"/api/v1/public/rfq/respond?t={token}", json=payload)
    assert r.status_code == 429


async def test_rate_limit_is_per_token_not_global(client: AsyncClient):
    """One supplier's flood must not deny another supplier's request."""
    flood_token = "flooder"
    for _ in range(10):
        await client.get(f"/api/v1/public/rfq/context?t={flood_token}")
    # Flooder is now blocked.
    r1 = await client.get(f"/api/v1/public/rfq/context?t={flood_token}")
    assert r1.status_code == 429
    # A different token still has its own fresh bucket.
    r2 = await client.get("/api/v1/public/rfq/context?t=different-token")
    assert r2.status_code == 401  # 401, NOT 429
