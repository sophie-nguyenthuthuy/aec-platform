"""Integration tests for POST /api/v1/codeguard/permit-checklist
and POST /api/v1/codeguard/checks/{id}/mark-item."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest


pytestmark = pytest.mark.asyncio


def _make_item(**overrides):
    from schemas.codeguard import ChecklistItem, ChecklistItemStatus

    base = dict(
        id="fire-approval",
        title="Thẩm duyệt thiết kế PCCC",
        description="Nộp hồ sơ tại Cục Cảnh sát PCCC",
        regulation_ref="QCVN 06:2022 §A.1",
        required=True,
        status=ChecklistItemStatus.pending,
    )
    base.update(overrides)
    return ChecklistItem(**base)


async def test_permit_checklist_persists_and_returns_items(
    client, fake_db, mock_llm, fake_auth
):
    from models.codeguard import PermitChecklist as PermitChecklistModel

    items = [_make_item(), _make_item(id="structural-calc", title="Bản tính kết cấu")]
    mock_llm.checklist(items=items)

    res = await client.post(
        "/api/v1/codeguard/permit-checklist",
        json={
            "project_id": str(uuid4()),
            "jurisdiction": "Hồ Chí Minh",
            "project_type": "residential",
        },
    )

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["jurisdiction"] == "Hồ Chí Minh"
    assert data["project_type"] == "residential"
    assert len(data["items"]) == 2
    assert {i["id"] for i in data["items"]} == {"fire-approval", "structural-calc"}

    records = [c for c in fake_db.added if isinstance(c, PermitChecklistModel)]
    assert len(records) == 1
    assert records[0].organization_id == fake_auth.organization_id
    assert len(records[0].items) == 2


async def test_permit_checklist_surfaces_pipeline_failure_as_502(client, mock_llm):
    mock = mock_llm.checklist(items=[])
    mock.side_effect = RuntimeError("LLM call failed")

    res = await client.post(
        "/api/v1/codeguard/permit-checklist",
        json={
            "project_id": str(uuid4()),
            "jurisdiction": "Hà Nội",
            "project_type": "commercial",
        },
    )
    assert res.status_code == 502
    assert res.json()["errors"][0]["message"].startswith("Checklist generation failed")


async def test_mark_item_updates_status_and_completed_at(
    client, fake_db, fake_auth
):
    from models.codeguard import PermitChecklist as PermitChecklistModel

    checklist_id = uuid4()
    checklist = PermitChecklistModel(
        id=checklist_id,
        organization_id=fake_auth.organization_id,
        project_id=uuid4(),
        jurisdiction="Hồ Chí Minh",
        project_type="residential",
        items=[
            {"id": "a", "title": "A", "required": True, "status": "pending"},
            {"id": "b", "title": "B", "required": True, "status": "done"},
        ],
        generated_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    fake_db.set_get(PermitChecklistModel, checklist_id, checklist)

    res = await client.post(
        f"/api/v1/codeguard/checks/{checklist_id}/mark-item",
        json={"item_id": "a", "status": "done", "notes": "signed off"},
    )

    assert res.status_code == 200
    updated = res.json()["data"]
    item_a = next(i for i in updated["items"] if i["id"] == "a")
    assert item_a["status"] == "done"
    assert item_a["notes"] == "signed off"
    # Both items are now "done" → completed_at should be set.
    assert updated["completed_at"] is not None


async def test_mark_item_returns_404_when_checklist_wrong_org(
    client, fake_db
):
    from models.codeguard import PermitChecklist as PermitChecklistModel

    checklist_id = uuid4()
    foreign = PermitChecklistModel(
        id=checklist_id,
        organization_id=uuid4(),  # different org
        project_id=uuid4(),
        jurisdiction="Hà Nội",
        project_type="commercial",
        items=[{"id": "a", "title": "A", "required": True, "status": "pending"}],
        generated_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    fake_db.set_get(PermitChecklistModel, checklist_id, foreign)

    res = await client.post(
        f"/api/v1/codeguard/checks/{checklist_id}/mark-item",
        json={"item_id": "a", "status": "done"},
    )
    assert res.status_code == 404


async def test_mark_item_returns_404_for_unknown_item(
    client, fake_db, fake_auth
):
    from models.codeguard import PermitChecklist as PermitChecklistModel

    checklist_id = uuid4()
    checklist = PermitChecklistModel(
        id=checklist_id,
        organization_id=fake_auth.organization_id,
        project_id=uuid4(),
        jurisdiction="Hồ Chí Minh",
        project_type="residential",
        items=[{"id": "a", "title": "A", "required": True, "status": "pending"}],
        generated_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    fake_db.set_get(PermitChecklistModel, checklist_id, checklist)

    res = await client.post(
        f"/api/v1/codeguard/checks/{checklist_id}/mark-item",
        json={"item_id": "nonexistent", "status": "done"},
    )
    assert res.status_code == 404
