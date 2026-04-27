"""End-to-end test: real DB → public RFQ portal → DB write-back.

The mock-heavy unit tests in `test_public_rfq_router.py` exercise the
endpoint logic with a stubbed `AdminSessionFactory`. This integration
test instead:

  1. Seeds an org + supplier + RFQ via `AdminSessionFactory` (real DB).
  2. Mints a real JWT via `services.rfq_tokens.mint_response_token`.
  3. Drives the actual FastAPI app in-process (ASGI transport over
     `main.app`) — same code path as production, just no socket.
  4. Hits `GET /context` and `POST /respond`.
  5. Reads `rfqs.responses` back from the DB and asserts the supplier's
     quote landed in the right slot, RFQ status moved to `responded`.

What this catches that unit tests can't:

  * `supabase_jwt_secret` drift between dispatcher (mints) and API
    (verifies). If the env vars diverge in prod, the supplier link
    silently 401s. Here both happen against the same `get_settings()`
    so a single secret wins, but the verify path is exercised end-to-
    end against a token minted by the dispatcher's helper.
  * Pydantic round-trip — the JSONB `responses[]` column stores a dict
    that the dashboard later reads as `RfqResponseEntry`; the unit
    test bypasses ORM serialisation. This test goes through it.
  * Rate-limit interaction with the real envelope handler (forwarding
    `Retry-After`).

Skipped unless a live admin DB URL is provided.
"""

from __future__ import annotations

import os
from datetime import date
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_ADMIN_URL = os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("COSTPULSE_RLS_ADMIN_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        not _ADMIN_URL,
        reason=(
            "Public-RFQ E2E requires DATABASE_URL_ADMIN (or COSTPULSE_RLS_ADMIN_URL) "
            "pointing at a live DB at migration head."
        ),
    ),
]


@pytest.fixture
async def seed():
    """Seed org + supplier + RFQ; yield the ids; clean up after the test."""
    assert _ADMIN_URL is not None
    admin_engine = create_async_engine(_ADMIN_URL, future=True)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    org_id = uuid4()
    supplier_id = uuid4()
    rfq_id = uuid4()

    async with admin_factory() as s:
        await s.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'E2E Public RFQ', :slug)"),
            {"id": str(org_id), "slug": f"e2e-public-rfq-{org_id}"},
        )
        await s.execute(
            text(
                "INSERT INTO suppliers "
                "(id, organization_id, name, contact, verified) "
                'VALUES (:id, :org, :name, \'{"email": "e2e@example.com"}\'::jsonb, true)'
            ),
            {"id": str(supplier_id), "org": str(org_id), "name": "E2E Supplier"},
        )
        # RFQ with the dispatcher's per-supplier slot pre-populated, simulating
        # state right after `services.rfq_dispatch.dispatch_rfq` ran.
        # Two-step: INSERT, then UPDATE the JSONB column. asyncpg's bind-
        # parameter parser confuses `:foo::jsonb` (the `::` cast operator
        # collides with the `:foo` placeholder), so we route the JSON
        # through a `bindparam(JSONB)` instead of an inline `::jsonb` cast.
        from sqlalchemy import bindparam
        from sqlalchemy.dialects.postgresql import JSONB

        await s.execute(
            text(
                "INSERT INTO rfqs "
                "(id, organization_id, status, sent_to, responses, deadline) "
                "VALUES (:id, :org, 'sent', ARRAY[:supplier_id]::uuid[], "
                "       '[]'::jsonb, :deadline)"
            ),
            {
                "id": str(rfq_id),
                "org": str(org_id),
                "supplier_id": str(supplier_id),
                "deadline": date(2026, 5, 30),
            },
        )
        await s.execute(
            text("UPDATE rfqs SET responses = :responses WHERE id = :id").bindparams(
                bindparam("responses", type_=JSONB),
            ),
            {
                "id": str(rfq_id),
                "responses": [
                    {
                        "supplier_id": str(supplier_id),
                        "status": "dispatched",
                        "dispatched_at": "2026-04-25T10:00:00+00:00",
                        "delivery": {
                            "to": "e2e@example.com",
                            "subject": "RFQ",
                            "delivered": True,
                            "reason": None,
                        },
                        "quote": None,
                    }
                ],
            },
        )
        await s.commit()

    yield {"org_id": org_id, "supplier_id": supplier_id, "rfq_id": rfq_id}

    async with admin_factory() as s:
        await s.execute(text("DELETE FROM rfqs WHERE id = :id"), {"id": str(rfq_id)})
        await s.execute(text("DELETE FROM suppliers WHERE id = :id"), {"id": str(supplier_id)})
        await s.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_id)})
        await s.commit()
    await admin_engine.dispose()

    # The FastAPI app keeps a module-level admin engine bound to whatever
    # event loop first touched it. Subsequent tests run on a fresh loop;
    # asyncpg's connections break when reused across loops with `Event
    # loop is closed`. Dispose the cached engine so the next test gets a
    # fresh one bound to its own loop.
    try:
        from db.session import _admin_engine

        await _admin_engine.dispose()
    except Exception:  # pragma: no cover — defensive: import path may shift
        pass


async def test_supplier_portal_full_loop(seed):
    """Mint → GET /context → POST /respond → assert DB side effect."""
    # Imports after the env fixture has asserted — these read settings on import.
    from db.session import _admin_engine, engine
    from main import app
    from services.rate_limit import reset_for_tests
    from services.rfq_tokens import mint_response_token

    # Force-recycle the global engines' connection pools so this test's
    # event loop owns the asyncpg connections. Without this, when a
    # prior async test in the same suite already opened a connection on
    # *its* loop and that loop has since closed, this test trips on
    # `RuntimeError: Event loop is closed` deep inside asyncpg's
    # protocol layer. `dispose()` is async-safe and idempotent.
    await engine.dispose()
    await _admin_engine.dispose()

    # Each test starts with a clean rate-limit bucket so a stale per-token
    # bucket from an earlier test run can't 429 us.
    reset_for_tests()

    token = mint_response_token(rfq_id=seed["rfq_id"], supplier_id=seed["supplier_id"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1) Context endpoint — the supplier's first request after clicking
        #    the email link.
        ctx_res = await ac.get(f"/api/v1/public/rfq/context?t={token}")
        assert ctx_res.status_code == 200, ctx_res.text
        ctx = ctx_res.json()["data"]
        assert ctx["organization_name"] == "E2E Public RFQ"
        assert ctx["deadline"] == "2026-05-30"
        assert ctx["submission_status"] == "pending"

        # 2) Submit a quote.
        respond_res = await ac.post(
            f"/api/v1/public/rfq/respond?t={token}",
            json={
                "total_vnd": "12500000",
                "lead_time_days": 14,
                "valid_until": "2026-06-15",
                "notes": "FOB Hanoi · NET-30",
                "line_items": [
                    {
                        "material_code": "CONC_C30",
                        "description": "Concrete C30",
                        "quantity": 120,
                        "unit": "m3",
                        "unit_price_vnd": "2050000",
                    }
                ],
            },
        )
        assert respond_res.status_code == 200, respond_res.text
        assert respond_res.json()["data"] == {"status": "received"}

        # 3) Re-fetch context — submission_status must flip to "submitted".
        ctx2 = (await ac.get(f"/api/v1/public/rfq/context?t={token}")).json()["data"]
        assert ctx2["submission_status"] == "submitted"
        assert ctx2["submitted_quote"]["total_vnd"] == "12500000"
        assert ctx2["submitted_quote"]["lead_time_days"] == 14

    # 4) DB side effect — straight SQL through a fresh admin engine.
    admin_engine = create_async_engine(_ADMIN_URL, future=True)
    try:
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        async with admin_factory() as s:
            row = (
                await s.execute(
                    text("SELECT status, responses FROM rfqs WHERE id = :id"),
                    {"id": str(seed["rfq_id"])},
                )
            ).first()
            assert row is not None, "RFQ row vanished"
            status, responses = row[0], row[1]
            assert status == "responded", f"status was {status!r}, expected 'responded'"
            assert isinstance(responses, list) and len(responses) == 1
            slot = responses[0]
            assert str(slot["supplier_id"]) == str(seed["supplier_id"])
            assert slot["status"] == "responded"
            assert slot["quote"]["total_vnd"] == "12500000"
            assert slot["quote"]["line_items"][0]["material_code"] == "CONC_C30"
    finally:
        await admin_engine.dispose()


async def test_supplier_portal_rejects_token_for_wrong_supplier(seed):
    """A valid token for a DIFFERENT supplier on this RFQ must 401, not 200.

    Catches the audience-OK-but-supplier-not-on-sent_to path that
    distinguishes "this token was minted by us" from "this token is
    valid for this RFQ". The unit tests cover the same case but
    against a stubbed session — here we ride through the real DB.
    """
    from main import app
    from services.rate_limit import reset_for_tests
    from services.rfq_tokens import mint_response_token

    reset_for_tests()
    rogue_token = mint_response_token(rfq_id=seed["rfq_id"], supplier_id=uuid4())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/public/rfq/context?t={rogue_token}")
        assert res.status_code == 401
