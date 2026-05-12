"""Router tests for /api/v1/thanhtoan/* + VN tax math."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")
CLAIM_ID = UUID("44444444-4444-4444-4444-444444444444")


def _mappings_result(rows: list[dict] | None = None, row: dict | None = None) -> MagicMock:
    r = MagicMock()
    mapped = MagicMock()
    if row is not None:
        mapped.one.return_value = row
        mapped.first.return_value = row
        mapped.all.return_value = rows if rows is not None else [row]
    else:
        mapped.one.side_effect = AssertionError("unprogrammed .one()")
        mapped.first.return_value = None
        mapped.all.return_value = rows if rows is not None else []
    r.mappings.return_value = mapped
    return r


def _scalar(value: Any) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = value
    r.scalar_one_or_none.return_value = value
    return r


def _plain_all(values: list[Any]) -> MagicMock:
    """Mock for `.all()` returning tuple-shaped rows (not .mappings())."""
    r = MagicMock()
    r.all.return_value = [(v,) for v in values]
    return r


class _ProgrammableSession:
    def __init__(self) -> None:
        self._queue: list[Any] = []

    def queue(self, result: Any) -> _ProgrammableSession:
        self._queue.append(result)
        return self

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        if not self._queue:
            r = MagicMock()
            r.mappings.return_value.first.return_value = None
            r.mappings.return_value.all.return_value = []
            r.scalar_one.return_value = 0
            r.all.return_value = []
            return r
        return self._queue.pop(0)

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


@pytest.fixture
def patch_session(monkeypatch):
    s = _ProgrammableSession()

    class _Fake:
        def __init__(self, _o: Any) -> None: ...
        async def __aenter__(self):
            return s

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr("routers.thanhtoan.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import thanhtoan as router_mod

    auth = AuthContext(user_id=USER_ID, organization_id=ORG_ID, role="admin", email="t@example.com")
    a = FastAPI()
    a.add_exception_handler(HTTPException, http_exception_handler)
    a.add_exception_handler(Exception, unhandled_exception_handler)
    a.include_router(router_mod.router)
    a.dependency_overrides[require_auth] = lambda: auth
    return a


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _claim_row(**overrides: Any) -> dict[str, Any]:
    base = dict(
        id=CLAIM_ID,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        claim_no="PT-2026-04",
        sequence=1,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        status="draft",
        subtotal_vnd=0,
        vat_pct=Decimal("0.0800"),
        vat_vnd=0,
        gross_vnd=0,
        retention_pct=Decimal("0.0500"),
        retention_vnd=0,
        tndn_pct=Decimal("0.0100"),
        tndn_vnd=0,
        net_payable_vnd=0,
        cumulative_prev_vnd=0,
        submitted_at=None,
        cdt_signed_at=None,
        cdt_signed_by=None,
        cdt_decision=None,
        cdt_comment=None,
        tvgs_signed_at=None,
        tvgs_signed_by=None,
        tvgs_decision=None,
        tvgs_comment=None,
        approved_at=None,
        rejected_at=None,
        due_at=None,
        paid_at=None,
        payment_reference=None,
        pdf_file_id=None,
        notes=None,
        created_by=USER_ID,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return base


# ---------- VN tax math (pure unit tests) ----------


def test_recompute_totals_default_rates():
    from schemas.thanhtoan import recompute_totals

    # One line at 1,000,000 VND. With defaults:
    #   subtotal  = 1,000,000
    #   vat 8%   = 80,000        → gross 1,080,000
    #   retn 5%  = 1,080,000 × 5% = 54,000
    #   tndn 1%  = 1,000,000 × 1% = 10,000
    #   net      = 1,080,000 - 54,000 - 10,000 = 1,016,000
    t = recompute_totals([1_000_000])
    assert t["subtotal_vnd"] == 1_000_000
    assert t["vat_vnd"] == 80_000
    assert t["gross_vnd"] == 1_080_000
    assert t["retention_vnd"] == 54_000
    assert t["tndn_vnd"] == 10_000
    assert t["net_payable_vnd"] == 1_016_000


def test_recompute_totals_multiple_lines_round_to_vnd():
    from schemas.thanhtoan import recompute_totals

    # Subtotal 123,457 VND triggers fractional rounding on every step.
    t = recompute_totals(
        [100_000, 23_457],
        vat_pct=Decimal("0.0800"),
        retention_pct=Decimal("0.0500"),
        tndn_pct=Decimal("0.0100"),
    )
    assert t["subtotal_vnd"] == 123_457
    # 123,457 × 8% = 9,876.56 → 9,877
    assert t["vat_vnd"] == 9_877
    assert t["gross_vnd"] == 133_334
    # 133,334 × 5% = 6,666.7 → 6,667
    assert t["retention_vnd"] == 6_667
    # 123,457 × 1% = 1,234.57 → 1,235
    assert t["tndn_vnd"] == 1_235
    assert t["net_payable_vnd"] == 133_334 - 6_667 - 1_235


def test_recompute_totals_10pct_vat_override():
    """Non-construction lines may use 10% VAT — exercise that path."""
    from schemas.thanhtoan import recompute_totals

    t = recompute_totals([1_000_000], vat_pct=Decimal("0.1000"))
    assert t["vat_vnd"] == 100_000
    assert t["gross_vnd"] == 1_100_000


# ---------- create_claim ----------


async def test_create_claim_assigns_sequence_and_cumulative(patch_session, client):
    patch_session.queue(_scalar(3))  # next sequence
    patch_session.queue(_scalar(50_000_000))  # cumulative_prev
    patch_session.queue(_mappings_result(row=_claim_row(sequence=3, cumulative_prev_vnd=50_000_000)))

    resp = await client.post(
        "/api/v1/thanhtoan/claims",
        json={
            "project_id": str(PROJECT_ID),
            "claim_no": "PT-2026-04",
            "period_start": "2026-04-01",
            "period_end": "2026-04-30",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["sequence"] == 3
    assert body["cumulative_prev_vnd"] == 50_000_000


async def test_create_claim_rejects_inverted_period(patch_session, client):
    resp = await client.post(
        "/api/v1/thanhtoan/claims",
        json={
            "project_id": str(PROJECT_ID),
            "claim_no": "PT-2026-04",
            "period_start": "2026-04-30",
            "period_end": "2026-04-01",
        },
    )
    assert resp.status_code == 422


# ---------- update_claim (lock check) ----------


async def test_update_claim_blocked_when_not_draft(patch_session, client):
    patch_session.queue(_mappings_result(row=_claim_row(status="submitted")))
    resp = await client.patch(
        f"/api/v1/thanhtoan/claims/{CLAIM_ID}",
        json={"due_at": "2026-05-30"},
    )
    assert resp.status_code == 409


# ---------- submit ----------


async def test_submit_freezes_cumulative_prev(patch_session, client):
    patch_session.queue(_mappings_result(row=_claim_row(status="draft")))  # _ensure_draft
    patch_session.queue(_plain_all([1_000_000]))  # lines for recompute
    patch_session.queue(_mappings_result(row=_claim_row()))  # recompute UPDATE returning
    patch_session.queue(_scalar(120_000_000))  # cumulative_prev refresh
    patch_session.queue(
        _mappings_result(row=_claim_row(status="submitted", cumulative_prev_vnd=120_000_000))
    )

    resp = await client.post(
        f"/api/v1/thanhtoan/claims/{CLAIM_ID}/submit",
        json={"notes": "Submitted for April"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "submitted"
    assert body["cumulative_prev_vnd"] == 120_000_000


# ---------- sign ----------


async def test_sign_cdt_approve_moves_to_approved(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=CLAIM_ID, status="in_review")))
    patch_session.queue(_mappings_result(row=_claim_row(status="approved")))

    resp = await client.post(
        f"/api/v1/thanhtoan/claims/{CLAIM_ID}/sign",
        json={"role": "cdt", "decision": "approve"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "approved"


async def test_sign_cdt_reject_moves_to_rejected(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=CLAIM_ID, status="submitted")))
    patch_session.queue(_mappings_result(row=_claim_row(status="rejected")))

    resp = await client.post(
        f"/api/v1/thanhtoan/claims/{CLAIM_ID}/sign",
        json={"role": "cdt", "decision": "reject", "comment": "Sai khối lượng"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "rejected"


async def test_sign_tvgs_lifts_submitted_to_in_review(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=CLAIM_ID, status="submitted")))
    patch_session.queue(_mappings_result(row=_claim_row(status="in_review")))

    resp = await client.post(
        f"/api/v1/thanhtoan/claims/{CLAIM_ID}/sign",
        json={"role": "tvgs", "decision": "approve"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "in_review"


async def test_sign_blocked_when_not_in_review_lane(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=CLAIM_ID, status="draft")))
    resp = await client.post(
        f"/api/v1/thanhtoan/claims/{CLAIM_ID}/sign",
        json={"role": "cdt", "decision": "approve"},
    )
    assert resp.status_code == 409


# ---------- mark_paid ----------


async def test_mark_paid_only_from_approved(patch_session, client):
    # The UPDATE returns no row because status != 'approved' in the
    # WHERE clause — the route maps that to 409.
    patch_session.queue(_mappings_result())
    resp = await client.post(
        f"/api/v1/thanhtoan/claims/{CLAIM_ID}/mark-paid",
        json={"paid_at": "2026-05-10", "payment_reference": "VCB-20260510-001"},
    )
    assert resp.status_code == 409


async def test_mark_paid_succeeds_when_approved(patch_session, client):
    patch_session.queue(_mappings_result(row=_claim_row(status="paid", paid_at=date(2026, 5, 10))))
    resp = await client.post(
        f"/api/v1/thanhtoan/claims/{CLAIM_ID}/mark-paid",
        json={"paid_at": "2026-05-10", "payment_reference": "VCB-20260510-001"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "paid"


# ---------- evidence ----------


async def test_evidence_requires_pointer(patch_session, client):
    resp = await client.post(
        f"/api/v1/thanhtoan/claims/{CLAIM_ID}/evidence",
        json={"kind": "photo"},
    )
    assert resp.status_code == 400
