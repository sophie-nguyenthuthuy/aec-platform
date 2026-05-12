"""Router tests for /api/v1/einvoice/* + MST + tax math."""

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
INV_ID = UUID("44444444-4444-4444-4444-444444444444")


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
            return r
        return self._queue.pop(0)

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


@pytest.fixture
def patch_session(monkeypatch):
    s = _ProgrammableSession()

    class _FakeTenant:
        def __init__(self, _o: Any) -> None: ...
        async def __aenter__(self):
            return s

        async def __aexit__(self, *_a):
            return None

    class _FakeAdmin:
        def __init__(self) -> None: ...
        async def __aenter__(self):
            return s

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr("routers.einvoice.TenantAwareSession", _FakeTenant)
    monkeypatch.setattr("routers.einvoice.AdminSessionFactory", _FakeAdmin)
    return s


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import einvoice as router_mod

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


def _inv_row(**overrides: Any) -> dict[str, Any]:
    base = dict(
        id=INV_ID,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        direction="issued",
        invoice_no="0000123",
        template_no="1/001",
        serial_no="C25TAA",
        status="draft",
        issuer_mst="0312345678",
        issuer_name="Công ty TNHH AEC",
        issuer_address="123 Lê Lợi, Q1, TPHCM",
        issuer_bank_account=None,
        buyer_mst="0309876543",
        buyer_name="Chủ đầu tư X",
        buyer_address=None,
        buyer_email=None,
        issue_date=date(2026, 5, 1),
        due_date=None,
        paid_at=None,
        currency="VND",
        exchange_rate=Decimal("1"),
        subtotal=0,
        vat_breakdown=[],
        vat_total=0,
        total=0,
        gdt_code=None,
        gdt_submitted_at=None,
        gdt_accepted_at=None,
        gdt_rejection_reason=None,
        payment_method=None,
        payment_reference=None,
        adjustment_for_id=None,
        adjustment_reason=None,
        xml_file_id=None,
        pdf_file_id=None,
        notes=None,
        created_by=USER_ID,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return base


# ---------- Pure math + validators ----------


def test_validate_mst_accepts_10_and_13_digit_forms():
    from schemas.einvoice import validate_mst

    assert validate_mst("0312345678") == "0312345678"
    assert validate_mst("0312345678-001") == "0312345678-001"


def test_validate_mst_rejects_garbage():
    import pytest as _p

    from schemas.einvoice import validate_mst

    for bad in ("", "12345", "abcdefghij", "0312345678-01", "0312345678-0001"):
        with _p.raises(ValueError):
            validate_mst(bad)


def test_compute_line_8pct_construction_vat():
    from decimal import Decimal as D

    from schemas.einvoice import compute_line

    line_total, vat = compute_line(D("10"), 100_000, D("0"), D("0.08"))
    assert line_total == 1_000_000
    assert vat == 80_000


def test_compute_line_with_discount_and_exempt_vat():
    from decimal import Decimal as D

    from schemas.einvoice import compute_line

    # 5 × 200k = 1m; 20% discount → 800k; exempt → no VAT.
    line_total, vat = compute_line(D("5"), 200_000, D("0.20"), None)
    assert line_total == 800_000
    assert vat == 0


def test_build_vat_breakdown_groups_by_rate():
    from decimal import Decimal as D

    from schemas.einvoice import build_vat_breakdown

    rows = build_vat_breakdown(
        [
            (1_000_000, 80_000, D("0.08")),
            (500_000, 40_000, D("0.08")),
            (200_000, 20_000, D("0.10")),
            (50_000, 0, None),
        ]
    )
    # 10% first (highest non-null), then 8%, then exempt last.
    assert [r["rate"] for r in rows] == [0.1, 0.08, None]
    eight = next(r for r in rows if r["rate"] == 0.08)
    assert eight["base"] == 1_500_000
    assert eight["vat_amount"] == 120_000


# ---------- Schema validation ----------


async def test_create_invoice_rejects_invalid_mst(patch_session, client):
    resp = await client.post(
        "/api/v1/einvoice/invoices",
        json={
            "direction": "issued",
            "invoice_no": "0000123",
            "template_no": "1/001",
            "serial_no": "C25TAA",
            "issue_date": "2026-05-01",
            "issuer_mst": "not-a-mst",
            "issuer_name": "AEC",
            "buyer_name": "X",
        },
    )
    assert resp.status_code == 422


async def test_create_invoice_rejects_unknown_vat_rate(patch_session, client):
    """A 13% VAT rate isn't in the known set — must 422."""
    resp = await client.post(
        "/api/v1/einvoice/invoices",
        json={
            "direction": "issued",
            "invoice_no": "0000124",
            "template_no": "1/001",
            "serial_no": "C25TAA",
            "issue_date": "2026-05-01",
            "issuer_mst": "0312345678",
            "issuer_name": "AEC",
            "buyer_name": "X",
            "lines": [
                {
                    "description": "Bad rate line",
                    "unit": "cái",
                    "qty": "1",
                    "unit_price": 1000,
                    "vat_rate": "0.13",
                }
            ],
        },
    )
    assert resp.status_code == 422


# ---------- create_invoice happy path ----------


async def test_create_invoice_computes_totals_server_side(patch_session, client):
    new_row = _inv_row(subtotal=1_000_000, vat_total=80_000, total=1_080_000)
    patch_session.queue(_mappings_result(row=new_row))  # INSERT einvoices
    patch_session.queue(MagicMock())  # INSERT einvoice_lines (1 line)

    resp = await client.post(
        "/api/v1/einvoice/invoices",
        json={
            "direction": "issued",
            "invoice_no": "0000123",
            "template_no": "1/001",
            "serial_no": "C25TAA",
            "issue_date": "2026-05-01",
            "issuer_mst": "0312345678",
            "issuer_name": "AEC",
            "buyer_name": "X",
            "lines": [
                {
                    "description": "Xi măng PCB40",
                    "unit": "bao",
                    "qty": "100",
                    "unit_price": 10_000,
                    "vat_rate": "0.08",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["subtotal"] == 1_000_000
    assert body["vat_total"] == 80_000
    assert body["total"] == 1_080_000


# ---------- issue (state transitions) ----------


async def test_issue_blocks_received_invoices(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(direction="received", status="draft")))
    resp = await client.post(f"/api/v1/einvoice/invoices/{INV_ID}/issue", json={})
    assert resp.status_code == 422


async def test_issue_requires_at_least_one_line(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(direction="issued", status="draft")))
    patch_session.queue(_scalar(0))
    resp = await client.post(f"/api/v1/einvoice/invoices/{INV_ID}/issue", json={})
    assert resp.status_code == 422


async def test_issue_succeeds(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(direction="issued", status="draft")))
    patch_session.queue(_scalar(2))  # line count
    patch_session.queue(_mappings_result(row=_inv_row(status="issued")))
    resp = await client.post(f"/api/v1/einvoice/invoices/{INV_ID}/issue", json={})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "issued"


# ---------- GDT callback ----------


async def test_gdt_callback_accepted_persists_code(patch_session, client):
    patch_session.queue(_mappings_result(row=_inv_row(status="accepted_gdt", gdt_code="0G2-2026-12345")))
    resp = await client.post(
        f"/api/v1/einvoice/invoices/{INV_ID}/gdt-callback",
        json={"accepted": True, "gdt_code": "0G2-2026-12345"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "accepted_gdt"
    assert body["gdt_code"] == "0G2-2026-12345"


async def test_gdt_callback_rejection_persists_reason(patch_session, client):
    patch_session.queue(
        _mappings_result(
            row=_inv_row(
                status="rejected_gdt",
                gdt_rejection_reason="Sai mã số thuế",
            )
        )
    )
    resp = await client.post(
        f"/api/v1/einvoice/invoices/{INV_ID}/gdt-callback",
        json={"accepted": False, "rejection_reason": "Sai mã số thuế"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "rejected_gdt"


# ---------- MST validate ----------


async def test_mst_validate_creates_not_found_when_cache_miss(patch_session, client):
    patch_session.queue(_mappings_result())  # cache miss
    new_row = dict(
        mst="0312345678",
        gdt_status="not_found",
        legal_name=None,
        address=None,
        registered_at=None,
        business_type=None,
        last_checked_at=datetime(2026, 5, 12, tzinfo=UTC),
    )
    patch_session.queue(_mappings_result(row=new_row))

    resp = await client.post(
        "/api/v1/einvoice/mst/validate",
        json={"mst": "0312345678"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["gdt_status"] == "not_found"


async def test_mst_validate_rejects_bad_format(patch_session, client):
    resp = await client.post("/api/v1/einvoice/mst/validate", json={"mst": "abc"})
    assert resp.status_code == 422
