"""Router tests for /api/v1/nghiemthu/*."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")
RECORD_ID = UUID("44444444-4444-4444-4444-444444444444")
SIGNATORY_ID = UUID("55555555-5555-5555-5555-555555555555")


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
        self.added: list[Any] = []

    def queue(self, result: Any) -> _ProgrammableSession:
        self._queue.append(result)
        return self

    def add(self, obj: Any) -> None:
        self.added.append(obj)

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

    class _Fake:
        def __init__(self, _o: Any) -> None: ...
        async def __aenter__(self):
            return s

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr("routers.nghiemthu.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import nghiemthu as router_mod

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


def _record_row(**overrides: Any) -> dict[str, Any]:
    base = dict(
        id=RECORD_ID,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        reference_no="BBNT-2026-04-001",
        acceptance_level="cong_viec",
        title="Nghiệm thu cốt thép cột T5",
        status="draft",
        acceptance_date=date(2026, 4, 28),
        location="Tầng 5 — trục A-D",
        work_item_codes=["RC.COL.05.A-D"],
        quantities=[],
        basis={},
        conclusion=None,
        pdf_file_id=None,
        superseded_by_id=None,
        finalized_at=None,
        created_by=USER_ID,
        created_at=datetime(2026, 4, 28, tzinfo=UTC),
        updated_at=datetime(2026, 4, 28, tzinfo=UTC),
    )
    base.update(overrides)
    return base


def _signatory_row(**overrides: Any) -> dict[str, Any]:
    base = dict(
        id=SIGNATORY_ID,
        organization_id=ORG_ID,
        record_id=RECORD_ID,
        role="tvgs",
        org_name="Công ty TNHH Giám sát ABC",
        representative_name="Nguyễn Văn A",
        position="Trưởng đoàn giám sát",
        required=True,
        decision="pending",
        comment=None,
        signed_at=None,
        signature_file_id=None,
        signed_by_user_id=None,
        sort_order=1,
        created_at=datetime(2026, 4, 28, tzinfo=UTC),
    )
    base.update(overrides)
    return base


# ---------- create_record ----------


async def test_create_record_returns_draft(patch_session, client):
    patch_session.queue(_mappings_result(row=_record_row()))
    resp = await client.post(
        "/api/v1/nghiemthu/records",
        json={
            "project_id": str(PROJECT_ID),
            "reference_no": "BBNT-2026-04-001",
            "acceptance_level": "cong_viec",
            "title": "Nghiệm thu cốt thép cột T5",
            "acceptance_date": "2026-04-28",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["data"]["status"] == "draft"
    assert body["data"]["acceptance_level"] == "cong_viec"


# ---------- get_record ----------


async def test_get_record_nests_signatories_and_evidence(patch_session, client):
    patch_session.queue(_mappings_result(row=_record_row()))
    patch_session.queue(_mappings_result(rows=[_signatory_row()]))
    patch_session.queue(_mappings_result(rows=[]))

    resp = await client.get(f"/api/v1/nghiemthu/records/{RECORD_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]["signatories"]) == 1
    assert body["data"]["signatories"][0]["role"] == "tvgs"
    assert body["data"]["evidence"] == []


# ---------- update_record ----------


async def test_update_record_locked_after_signature(patch_session, client):
    patch_session.queue(_scalar(1))  # any non-pending decision exists
    resp = await client.patch(
        f"/api/v1/nghiemthu/records/{RECORD_ID}",
        json={"title": "Updated title"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert "record_locked_by_signature" in body["errors"][0]["message"] or body["errors"][0]["code"] == "409"


async def test_update_record_succeeds_when_no_signatures(patch_session, client):
    patch_session.queue(_scalar(0))
    patch_session.queue(_mappings_result(row=_record_row(title="Updated title")))
    resp = await client.patch(
        f"/api/v1/nghiemthu/records/{RECORD_ID}",
        json={"title": "Updated title"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "Updated title"


# ---------- sign_signatory ----------


async def test_sign_lifts_draft_to_in_signoff(patch_session, client):
    """First non-pending decision flips draft → in_signoff."""
    patch_session.queue(_mappings_result(row=_signatory_row(record_status="draft")))
    patch_session.queue(_mappings_result(row=_signatory_row(decision="approve")))
    patch_session.queue(MagicMock())  # UPDATE record status → in_signoff

    resp = await client.post(
        f"/api/v1/nghiemthu/signatories/{SIGNATORY_ID}/sign",
        json={"decision": "approve"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["decision"] == "approve"


async def test_sign_required_reject_terminates_record(patch_session, client):
    """A `reject` from a required role moves the record to `rejected`."""
    patch_session.queue(
        _mappings_result(row=_signatory_row(record_status="in_signoff", required=True))
    )
    patch_session.queue(
        _mappings_result(row=_signatory_row(decision="reject"))
    )
    patch_session.queue(MagicMock())  # UPDATE record → rejected

    resp = await client.post(
        f"/api/v1/nghiemthu/signatories/{SIGNATORY_ID}/sign",
        json={"decision": "reject", "comment": "Không đạt chất lượng"},
    )
    assert resp.status_code == 200


async def test_sign_rejected_on_already_final(patch_session, client):
    patch_session.queue(_mappings_result(row=_signatory_row(record_status="accepted")))
    resp = await client.post(
        f"/api/v1/nghiemthu/signatories/{SIGNATORY_ID}/sign",
        json={"decision": "approve"},
    )
    assert resp.status_code == 409


# ---------- finalize ----------


async def test_finalize_blocks_when_mandatory_missing(patch_session, client):
    """When CĐT/TVGS/NT aren't all attached + approved, finalize stays pending."""
    patch_session.queue(_mappings_result(row=dict(id=RECORD_ID, status="in_signoff")))
    # Only TVGS approve attached — CĐT and NT still missing.
    patch_session.queue(
        _mappings_result(rows=[dict(role="tvgs", decision="approve", required=True)])
    )

    resp = await client.post(f"/api/v1/nghiemthu/records/{RECORD_ID}/finalize")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "in_signoff"
    pending = set(body["mandatory_pending_roles"])
    assert pending == {"cdt", "nt"}


async def test_finalize_succeeds_when_all_required_approve(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=RECORD_ID, status="in_signoff")))
    patch_session.queue(
        _mappings_result(
            rows=[
                dict(role="cdt", decision="approve", required=True),
                dict(role="tvgs", decision="approve", required=True),
                dict(role="nt", decision="approve", required=True),
            ]
        )
    )
    patch_session.queue(MagicMock())  # final UPDATE → accepted

    resp = await client.post(f"/api/v1/nghiemthu/records/{RECORD_ID}/finalize")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "accepted"


async def test_finalize_idempotent_on_terminal(patch_session, client):
    """Calling finalize on already-accepted record returns same state."""
    patch_session.queue(_mappings_result(row=dict(id=RECORD_ID, status="accepted")))
    resp = await client.post(f"/api/v1/nghiemthu/records/{RECORD_ID}/finalize")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "accepted"


async def test_finalize_returns_rejected_when_required_rejected(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=RECORD_ID, status="in_signoff")))
    patch_session.queue(
        _mappings_result(
            rows=[
                dict(role="cdt", decision="approve", required=True),
                dict(role="tvgs", decision="reject", required=True),
                dict(role="nt", decision="pending", required=True),
            ]
        )
    )
    patch_session.queue(MagicMock())  # UPDATE → rejected

    resp = await client.post(f"/api/v1/nghiemthu/records/{RECORD_ID}/finalize")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "rejected"
    assert body["rejected_by_roles"] == ["tvgs"]


# ---------- evidence ----------


async def test_add_evidence_rejects_when_no_pointer(patch_session, client):
    resp = await client.post(
        f"/api/v1/nghiemthu/records/{RECORD_ID}/evidence",
        json={"kind": "photo"},
    )
    assert resp.status_code == 400


async def test_add_evidence_succeeds_with_file_id(patch_session, client):
    patch_session.queue(_scalar(RECORD_ID))
    file_id = uuid4()
    new_ev = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        record_id=RECORD_ID,
        kind="photo",
        file_id=file_id,
        external_ref=None,
        caption="Mặt cắt cột tầng 5",
        captured_at=None,
        sort_order=0,
        created_at=datetime(2026, 4, 28, tzinfo=UTC),
    )
    patch_session.queue(_mappings_result(row=new_ev))

    resp = await client.post(
        f"/api/v1/nghiemthu/records/{RECORD_ID}/evidence",
        json={"kind": "photo", "file_id": str(file_id), "caption": "Mặt cắt cột tầng 5"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["kind"] == "photo"


# ---------- supersede ----------


async def test_supersede_blocks_cross_project(patch_session, client):
    other_project = uuid4()
    rows = [
        dict(id=RECORD_ID, project_id=PROJECT_ID, status="accepted"),
        dict(id=uuid4(), project_id=other_project, status="draft"),
    ]
    replacement_id = rows[1]["id"]
    patch_session.queue(_mappings_result(rows=rows))

    resp = await client.post(
        f"/api/v1/nghiemthu/records/{RECORD_ID}/supersede?replacement_id={replacement_id}"
    )
    assert resp.status_code == 422
