"""Integration tests for /api/v1/pulse/* endpoints.

Covers the router + schema wiring for tasks, change orders, meeting notes,
and client reports. The AI pipelines (`ml.pipelines.pulse.*`) are mocked so
tests never reach a real LLM provider.

Uses the `FakeAsyncSession` from the shared conftest to record model writes
without needing Postgres.
"""
from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient


# Stub the heavy LangChain / LangGraph modules so `ml.pipelines.pulse` can be
# imported without them installed. Tests never exercise the real LLM — they
# monkeypatch the three pipeline entrypoints.
def _install_langchain_stubs() -> None:
    if "langchain_anthropic" in sys.modules:
        return
    anthropic_mod = ModuleType("langchain_anthropic")
    anthropic_mod.ChatAnthropic = type("ChatAnthropic", (), {"__init__": lambda *a, **k: None})
    sys.modules["langchain_anthropic"] = anthropic_mod

    core_mod = ModuleType("langchain_core")
    messages_mod = ModuleType("langchain_core.messages")
    messages_mod.HumanMessage = type("HumanMessage", (), {})
    messages_mod.SystemMessage = type("SystemMessage", (), {})
    parsers_mod = ModuleType("langchain_core.output_parsers")
    parsers_mod.JsonOutputParser = type("JsonOutputParser", (), {})
    prompts_mod = ModuleType("langchain_core.prompts")
    prompts_mod.ChatPromptTemplate = type("ChatPromptTemplate", (), {})
    sys.modules["langchain_core"] = core_mod
    sys.modules["langchain_core.messages"] = messages_mod
    sys.modules["langchain_core.output_parsers"] = parsers_mod
    sys.modules["langchain_core.prompts"] = prompts_mod

    langgraph_mod = ModuleType("langgraph")
    graph_mod = ModuleType("langgraph.graph")
    graph_mod.END = "__end__"

    class _FakeStateGraph:
        def __init__(self, *a, **k):
            pass
        def add_node(self, *a, **k):
            return self
        def add_edge(self, *a, **k):
            return self
        def set_entry_point(self, *a, **k):
            return self
        def compile(self, *a, **k):
            return MagicMock()

    graph_mod.StateGraph = _FakeStateGraph
    sys.modules["langgraph"] = langgraph_mod
    sys.modules["langgraph.graph"] = graph_mod


_install_langchain_stubs()


pytestmark = pytest.mark.asyncio


# ---------- Local app fixture (overrides codeguard-only app from conftest) ----------

@pytest.fixture
def app(fake_auth, fake_db) -> Iterator[FastAPI]:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from middleware.auth import require_auth
    from routers import pulse as pulse_router

    async def _override_db() -> AsyncIterator:
        yield fake_db

    test_app = FastAPI()
    test_app.add_exception_handler(HTTPException, http_exception_handler)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)
    test_app.include_router(pulse_router.router)
    test_app.dependency_overrides[require_auth] = lambda: fake_auth
    test_app.dependency_overrides[get_db] = _override_db
    try:
        yield test_app
    finally:
        test_app.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Helpers ----------

def _execute_result(
    *,
    scalars_all: list | None = None,
    scalar_one_or_none: object | None = None,
    scalar_one: object | None = None,
    one: tuple | None = None,
    rows: list | None = None,
):
    """Build a MagicMock mimicking an AsyncSession.execute() result."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = list(scalars_all or [])
    r.scalars.return_value.first.return_value = (scalars_all or [None])[0] if scalars_all else None
    r.scalar_one_or_none.return_value = scalar_one_or_none
    r.scalar_one.return_value = scalar_one if scalar_one is not None else 0
    # For routes that do `.one()` and index into the tuple (e.g. dashboard CO row).
    r.one.return_value = one if one is not None else (0, 0)
    r.all.return_value = list(rows or [])
    r.mappings.return_value.all.return_value = list(rows or [])
    return r


def _task_factory(**overrides):
    from models.pulse import Task as TaskModel

    base = dict(
        id=overrides.pop("id", uuid4()),
        organization_id=UUID("22222222-2222-2222-2222-222222222222"),
        project_id=uuid4(),
        title="Sample task",
        status="todo",
        priority="normal",
        phase=None,
        discipline=None,
        description=None,
        assignee_id=None,
        parent_id=None,
        start_date=None,
        due_date=None,
        completed_at=None,
        position=None,
        tags=[],
        created_by=None,
        created_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    t = TaskModel(**base)
    return t


# ---------- Dashboard ----------

async def test_dashboard_empty_project_returns_green_rag(client, fake_db):
    # counts + overdue + milestones + COs + last_report all empty
    fake_db.set_execute_result(_execute_result(rows=[]))   # counts
    fake_db.set_execute_result(_execute_result(scalar_one=0))  # overdue count
    fake_db.set_execute_result(_execute_result(scalars_all=[]))  # milestones
    fake_db.set_execute_result(_execute_result(one=(0, 0)))  # open CO: (count, sum)
    fake_db.set_execute_result(_execute_result(scalar_one_or_none=None))  # last report

    res = await client.get(f"/api/v1/pulse/projects/{uuid4()}/dashboard")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["errors"] is None
    data = body["data"]
    assert data["rag_status"] == "green"
    assert data["progress_pct"] == 0.0
    assert data["task_counts"] == {"todo": 0, "in_progress": 0, "review": 0, "done": 0, "blocked": 0}
    assert data["overdue_tasks"] == 0
    assert data["open_change_orders"] == 0
    assert data["alerts"] == []


async def test_dashboard_aggregates_counts_and_flags_overdue_red(client, fake_db):
    # 10 done, 2 in_progress, 3 todo, 5 overdue (≥5 overdue → red)
    fake_db.set_execute_result(_execute_result(rows=[
        ("done", 10), ("in_progress", 2), ("todo", 3),
    ]))
    fake_db.set_execute_result(_execute_result(scalar_one=5))  # overdue
    fake_db.set_execute_result(_execute_result(scalars_all=[]))  # milestones
    fake_db.set_execute_result(_execute_result(one=(0, 0)))  # open CO
    fake_db.set_execute_result(_execute_result(scalar_one_or_none=None))  # last report

    res = await client.get(f"/api/v1/pulse/projects/{uuid4()}/dashboard")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["task_counts"]["done"] == 10
    assert data["overdue_tasks"] == 5
    assert data["rag_status"] == "red"
    assert data["progress_pct"] == pytest.approx(66.7, abs=0.1)
    assert any("overdue" in a for a in data["alerts"])


# ---------- Tasks CRUD ----------

async def test_create_task_persists_with_auth_context(client, fake_db, fake_auth):
    from models.pulse import Task as TaskModel

    project_id = uuid4()
    payload = {
        "project_id": str(project_id),
        "title": "Pour slab on grade",
        "phase": "construction",
        "priority": "high",
        "due_date": "2026-05-01",
    }
    res = await client.post("/api/v1/pulse/tasks", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["title"] == "Pour slab on grade"
    assert data["phase"] == "construction"
    assert data["status"] == "todo"
    assert data["organization_id"] == str(fake_auth.organization_id)
    assert data["created_by"] == str(fake_auth.user_id)

    added = [o for o in fake_db.added if isinstance(o, TaskModel)]
    assert len(added) == 1
    assert added[0].project_id == project_id


async def test_create_task_rejects_bad_phase(client):
    res = await client.post(
        "/api/v1/pulse/tasks",
        json={"project_id": str(uuid4()), "title": "X", "phase": "foundation"},
    )
    assert res.status_code == 422
    # Error shape: either FastAPI's default {"detail": [...]} or the envelope.
    body = res.json()
    assert "phase" in res.text


async def test_update_task_sets_completed_at_when_done(client, fake_db):
    from models.pulse import Task as TaskModel

    tid = uuid4()
    existing = _task_factory(id=tid, status="in_progress", completed_at=None)
    fake_db.set_get(TaskModel, tid, existing)

    res = await client.patch(
        f"/api/v1/pulse/tasks/{tid}", json={"status": "done"}
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["status"] == "done"
    assert data["completed_at"] is not None
    assert existing.completed_at is not None  # mutated in place


async def test_update_task_clears_completed_at_when_reopened(client, fake_db):
    from models.pulse import Task as TaskModel

    tid = uuid4()
    existing = _task_factory(
        id=tid, status="done", completed_at=datetime.now(timezone.utc)
    )
    fake_db.set_get(TaskModel, tid, existing)

    res = await client.patch(
        f"/api/v1/pulse/tasks/{tid}", json={"status": "in_progress"}
    )
    assert res.status_code == 200
    assert res.json()["data"]["completed_at"] is None


async def test_update_task_returns_404_for_missing(client, fake_db):
    res = await client.patch(
        f"/api/v1/pulse/tasks/{uuid4()}", json={"status": "done"}
    )
    assert res.status_code == 404


async def test_bulk_update_tasks_applies_partial_patch(client, fake_db):
    from models.pulse import Task as TaskModel

    t1 = _task_factory(id=uuid4(), status="todo", phase="design")
    t2 = _task_factory(id=uuid4(), status="todo", phase="design")
    # Router does: SELECT tasks WHERE id IN (...)  -> scalars().all()
    fake_db.set_execute_result(_execute_result(scalars_all=[t1, t2]))

    res = await client.post(
        "/api/v1/pulse/tasks/bulk",
        json={
            "items": [
                {"id": str(t1.id), "status": "review", "position": "1.0"},
                {"id": str(t2.id), "phase": "construction"},
            ]
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert len(data) == 2
    by_id = {d["id"]: d for d in data}
    assert by_id[str(t1.id)]["status"] == "review"
    assert by_id[str(t2.id)]["phase"] == "construction"
    # t2 should retain its original status since we didn't patch it
    assert by_id[str(t2.id)]["status"] == "todo"


async def test_bulk_update_skips_unknown_ids(client, fake_db):
    # No tasks matched → router should return [] and not error
    fake_db.set_execute_result(_execute_result(scalars_all=[]))

    res = await client.post(
        "/api/v1/pulse/tasks/bulk",
        json={"items": [{"id": str(uuid4()), "status": "done"}]},
    )
    assert res.status_code == 200
    assert res.json()["data"] == []


# ---------- Change orders ----------

async def test_create_change_order_sets_draft_status(client, fake_db, fake_auth):
    from models.pulse import ChangeOrder as ChangeOrderModel

    res = await client.post(
        "/api/v1/pulse/change-orders",
        json={
            "project_id": str(uuid4()),
            "number": "CO-001",
            "title": "Upgrade HVAC",
            "cost_impact_vnd": 150_000_000,
            "schedule_impact_days": 7,
            "initiator": "client",
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["status"] == "draft"
    assert data["number"] == "CO-001"
    added = [o for o in fake_db.added if isinstance(o, ChangeOrderModel)]
    assert len(added) == 1
    assert added[0].organization_id == fake_auth.organization_id


async def test_approve_change_order_marks_approved(client, fake_db, fake_auth):
    from models.pulse import ChangeOrder as ChangeOrderModel

    co_id = uuid4()
    existing = ChangeOrderModel(
        id=co_id,
        organization_id=fake_auth.organization_id,
        project_id=uuid4(),
        number="CO-001",
        title="Upgrade HVAC",
        description=None,
        status="submitted",
        initiator="client",
        cost_impact_vnd=150_000_000,
        schedule_impact_days=7,
        ai_analysis=None,
        submitted_at=datetime.now(timezone.utc),
        approved_at=None,
        approved_by=None,
        created_at=datetime.now(timezone.utc),
    )
    fake_db.set_get(ChangeOrderModel, co_id, existing)

    res = await client.patch(
        f"/api/v1/pulse/change-orders/{co_id}/approve",
        json={"decision": "approve", "notes": "OK"},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["status"] == "approved"
    assert data["approved_at"] is not None
    assert data["approved_by"] == str(fake_auth.user_id)


async def test_approve_change_order_supports_reject(client, fake_db, fake_auth):
    from models.pulse import ChangeOrder as ChangeOrderModel

    co_id = uuid4()
    existing = ChangeOrderModel(
        id=co_id,
        organization_id=fake_auth.organization_id,
        project_id=uuid4(),
        number="CO-002",
        title="Extra parking",
        description=None,
        status="submitted",
        initiator="contractor",
        cost_impact_vnd=None,
        schedule_impact_days=None,
        ai_analysis=None,
        submitted_at=datetime.now(timezone.utc),
        approved_at=None,
        approved_by=None,
        created_at=datetime.now(timezone.utc),
    )
    fake_db.set_get(ChangeOrderModel, co_id, existing)

    res = await client.patch(
        f"/api/v1/pulse/change-orders/{co_id}/approve",
        json={"decision": "reject", "notes": "Out of scope"},
    )
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "rejected"


async def test_approve_rejects_invalid_decision(client):
    res = await client.patch(
        f"/api/v1/pulse/change-orders/{uuid4()}/approve",
        json={"decision": "approved"},  # wrong: must be "approve"
    )
    assert res.status_code == 422


async def test_analyze_change_order_persists_ai_output(
    client, fake_db, monkeypatch, fake_auth
):
    from models.pulse import ChangeOrder as ChangeOrderModel
    from schemas.pulse import ChangeOrderAIAnalysis

    co_id = uuid4()
    existing = ChangeOrderModel(
        id=co_id,
        organization_id=fake_auth.organization_id,
        project_id=uuid4(),
        number="CO-003",
        title="Waterproofing delta",
        description="Add extra layer for basement",
        status="draft",
        initiator="contractor",
        cost_impact_vnd=50_000_000,
        schedule_impact_days=3,
        ai_analysis=None,
        submitted_at=None,
        approved_at=None,
        approved_by=None,
        created_at=datetime.now(timezone.utc),
    )
    fake_db.set_get(ChangeOrderModel, co_id, existing)

    ai_result = ChangeOrderAIAnalysis(
        root_cause="scope_creep",
        cost_breakdown={"materials": 30_000_000, "labor": 20_000_000},
        schedule_analysis={"days": 3, "critical_path": False},
        contract_clauses=["Section 4.2"],
        recommendation="approve",
        reasoning="Minor cost impact, low risk; proceed.",
        confidence=0.82,
    )
    ai_mock = AsyncMock(return_value=ai_result)
    monkeypatch.setattr("ml.pipelines.pulse.analyze_change_order", ai_mock)

    res = await client.post(f"/api/v1/pulse/change-orders/{co_id}/analyze")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["ai_analysis"]["root_cause"] == "scope_creep"
    assert data["ai_analysis"]["recommendation"] == "approve"
    assert data["ai_analysis"]["confidence"] == pytest.approx(0.82)
    ai_mock.assert_awaited_once()


# ---------- Meeting notes ----------

async def test_structure_meeting_notes_persists_when_requested(
    client, fake_db, monkeypatch, fake_auth
):
    from models.pulse import MeetingNote as MeetingNoteModel
    from schemas.pulse import MeetingStructured, ActionItem

    structured = MeetingStructured(
        summary="Discussed HVAC change",
        decisions=["Switch to VRF"],
        action_items=[
            ActionItem(title="Confirm VRF unit model", owner=None, deadline=None)
        ],
        risks=[],
        next_meeting=None,
    )
    ai_mock = AsyncMock(return_value=structured)
    monkeypatch.setattr("ml.pipelines.pulse.structure_meeting_notes", ai_mock)

    project_id = uuid4()
    res = await client.post(
        "/api/v1/pulse/meeting-notes/structure",
        json={
            "raw_notes": "Meeting on 2026-04-22. Decided to switch to VRF...",
            "project_id": str(project_id),
            "persist": True,
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["ai_structured"]["summary"] == "Discussed HVAC change"
    assert len(data["ai_structured"]["action_items"]) == 1
    # persist=True should have added a MeetingNote to the session
    added = [o for o in fake_db.added if isinstance(o, MeetingNoteModel)]
    assert len(added) == 1
    assert added[0].project_id == project_id
    ai_mock.assert_awaited_once()


async def test_structure_meeting_notes_does_not_persist_without_project(
    client, fake_db, monkeypatch
):
    from models.pulse import MeetingNote as MeetingNoteModel
    from schemas.pulse import MeetingStructured

    ai_mock = AsyncMock(return_value=MeetingStructured(
        summary="hello", decisions=[], action_items=[], risks=[], next_meeting=None,
    ))
    monkeypatch.setattr("ml.pipelines.pulse.structure_meeting_notes", ai_mock)

    res = await client.post(
        "/api/v1/pulse/meeting-notes/structure",
        json={"raw_notes": "short note", "persist": False},
    )
    assert res.status_code == 200
    # Nothing persisted
    assert [o for o in fake_db.added if isinstance(o, MeetingNoteModel)] == []


# ---------- Client reports ----------

async def test_generate_report_persists_and_renders_html(
    client, fake_db, monkeypatch, fake_auth
):
    """WeasyPrint isn't installed → route should fall back to HTML-only."""
    from models.pulse import ClientReport as ClientReportModel
    from schemas.pulse import ClientReportContent

    content = ClientReportContent(
        header_summary="Week 16 progress report",
        progress_section={"overall_pct": 42.0, "highlights": ["Slab poured"]},
        photos_section=[],
        financials={"budget_used_pct": 38.0},
        issues=[],
        next_steps=["Wall framing"],
    )
    gen_mock = AsyncMock(return_value=content)
    render_mock = AsyncMock(return_value="<html><body>Report</body></html>")
    monkeypatch.setattr("ml.pipelines.pulse.generate_client_report", gen_mock)
    monkeypatch.setattr("ml.pipelines.pulse.render_report_html", render_mock)

    # Force the "WeasyPrint missing" fall-back so we don't hit S3 from tests.
    from ml.pipelines.pulse import PDFRendererUnavailable

    async def _no_pdf(*_args, **_kwargs):
        raise PDFRendererUnavailable("test: weasyprint unavailable")

    monkeypatch.setattr("ml.pipelines.pulse.render_report_pdf", _no_pdf)

    project_id = uuid4()
    res = await client.post(
        "/api/v1/pulse/client-reports/generate",
        json={
            "project_id": str(project_id),
            "period": "2026-04",
            "language": "en",
        },
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()["data"]
    assert data["status"] == "draft"
    assert data["rendered_html"].startswith("<html>")
    assert data["content"]["header_summary"].startswith("Week 16")
    # PDF path should degrade gracefully to null, not 5xx.
    assert data["pdf_url"] is None

    added = [o for o in fake_db.added if isinstance(o, ClientReportModel)]
    assert len(added) == 1
    assert added[0].project_id == project_id
    assert added[0].pdf_url is None
    gen_mock.assert_awaited_once()
    render_mock.assert_called_once()


async def test_generate_report_stores_pdf_when_weasyprint_available(
    client, fake_db, monkeypatch, fake_auth
):
    """Happy path: PDF renders and uploads, pdf_url is populated."""
    from models.pulse import ClientReport as ClientReportModel
    from schemas.pulse import ClientReportContent

    content = ClientReportContent(
        header_summary="Week 17 report",
        progress_section={"overall_pct": 50.0, "highlights": []},
        photos_section=[],
        financials=None,
        issues=[],
        next_steps=[],
    )
    monkeypatch.setattr(
        "ml.pipelines.pulse.generate_client_report",
        AsyncMock(return_value=content),
    )
    monkeypatch.setattr(
        "ml.pipelines.pulse.render_report_html",
        AsyncMock(return_value="<html/>"),
    )

    pdf_mock = AsyncMock(return_value=b"%PDF-1.4 fake bytes")
    monkeypatch.setattr("ml.pipelines.pulse.render_report_pdf", pdf_mock)

    # Capture what the route tries to upload, return a deterministic URL.
    upload_calls: list[dict] = []

    async def _fake_upload(settings, *, organization_id, report_id, pdf_bytes):
        upload_calls.append(
            dict(org=organization_id, report=report_id, size=len(pdf_bytes))
        )
        return f"https://cdn.test/{organization_id}/pulse/reports/{report_id}.pdf"

    monkeypatch.setattr("services.pdf_storage.upload_report_pdf", _fake_upload)

    project_id = uuid4()
    res = await client.post(
        "/api/v1/pulse/client-reports/generate",
        json={"project_id": str(project_id), "period": "2026-04", "language": "en"},
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()["data"]
    assert data["pdf_url"].startswith("https://cdn.test/")
    assert data["pdf_url"].endswith(f"/{data['id']}.pdf")

    assert len(upload_calls) == 1
    assert upload_calls[0]["org"] == fake_auth.organization_id
    assert upload_calls[0]["size"] == len(b"%PDF-1.4 fake bytes")
    pdf_mock.assert_awaited_once()

    [row] = [o for o in fake_db.added if isinstance(o, ClientReportModel)]
    assert row.pdf_url == data["pdf_url"]


async def test_generate_report_tolerates_pdf_upload_failure(
    client, fake_db, monkeypatch, fake_auth
):
    """S3 failure after a successful PDF render should still persist the report."""
    from schemas.pulse import ClientReportContent

    content = ClientReportContent(
        header_summary="x",
        progress_section={"overall_pct": 0.0},
        photos_section=[], financials=None, issues=[], next_steps=[],
    )
    monkeypatch.setattr(
        "ml.pipelines.pulse.generate_client_report",
        AsyncMock(return_value=content),
    )
    monkeypatch.setattr(
        "ml.pipelines.pulse.render_report_html",
        AsyncMock(return_value="<html/>"),
    )
    monkeypatch.setattr(
        "ml.pipelines.pulse.render_report_pdf",
        AsyncMock(return_value=b"%PDF-1.4"),
    )

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("s3 429")

    monkeypatch.setattr("services.pdf_storage.upload_report_pdf", _boom)

    res = await client.post(
        "/api/v1/pulse/client-reports/generate",
        json={"project_id": str(uuid4()), "period": "2026-04", "language": "en"},
    )
    # Upload died, but the report must still be saved (HTML-only).
    assert res.status_code in (200, 201)
    assert res.json()["data"]["pdf_url"] is None


async def test_send_report_updates_status_and_recipients(client, fake_db, fake_auth):
    from models.pulse import ClientReport as ClientReportModel

    rid = uuid4()
    existing = ClientReportModel(
        id=rid,
        organization_id=fake_auth.organization_id,
        project_id=uuid4(),
        report_date=date(2026, 4, 22),
        period="2026-04",
        content={"header_summary": "x", "progress_section": {"overall_pct": 0.0}},
        rendered_html="<p>x</p>",
        pdf_url=None,
        status="draft",
        sent_at=None,
        sent_to=None,
        created_at=datetime.now(timezone.utc),
    )
    fake_db.set_get(ClientReportModel, rid, existing)

    res = await client.post(
        f"/api/v1/pulse/client-reports/{rid}/send",
        json={"recipients": ["client@example.com", "pm@example.com"]},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["status"] == "sent"
    assert data["sent_at"] is not None
    assert data["sent_to"] == ["client@example.com", "pm@example.com"]


async def test_send_report_rejects_empty_recipients(client, fake_db, fake_auth):
    from models.pulse import ClientReport as ClientReportModel

    rid = uuid4()
    existing = ClientReportModel(
        id=rid,
        organization_id=fake_auth.organization_id,
        project_id=uuid4(),
        report_date=date(2026, 4, 22),
        period="2026-04",
        content=None,
        rendered_html=None,
        pdf_url=None,
        status="draft",
        sent_at=None,
        sent_to=None,
        created_at=datetime.now(timezone.utc),
    )
    fake_db.set_get(ClientReportModel, rid, existing)

    res = await client.post(
        f"/api/v1/pulse/client-reports/{rid}/send", json={"recipients": []}
    )
    assert res.status_code == 422
