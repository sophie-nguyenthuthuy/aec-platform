"""Tests for `GET /api/v1/codeguard/permit-checklist/{id}/pdf`.

Covers two layers:
  1. The PDF renderer in isolation — given a synthesised checklist,
     does it emit a non-empty PDF whose extracted text contains the
     expected item titles, regulation refs, and progress summary?
  2. The route — does it 404 cleanly for unknown ids and for
     cross-org access? does it return `application/pdf` with the
     right Content-Disposition?

The PDF text extraction uses `pdfplumber` (already a dep — see
apps/api/requirements.txt). We don't try to assert exact byte
sequences because reportlab's output isn't byte-stable across
versions; text extraction is the right contract level.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.asyncio


# ---------- Renderer in isolation -----------------------------------------


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Pull all text out of a PDF — used to assert specific strings
    appear without depending on byte-level layout. `pdfplumber` is
    pinned in apps/api/requirements.txt so CI has it; local dev
    environments without it cleanly skip the extraction-dependent
    assertions."""
    try:
        import pdfplumber
    except ImportError:
        pytest.skip("pdfplumber not installed in this environment")

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def test_renderer_emits_non_empty_pdf_with_item_titles():
    """Happy path: a multi-item checklist produces a PDF whose text
    contains every item title, the jurisdiction, and the progress
    summary line."""
    from services.codeguard_pdf import render_permit_checklist_pdf

    items = [
        {
            "id": "site-survey",
            "title": "Khao sat hien trang",
            "description": "Ban ve khao sat dia hinh va dia chat.",
            "regulation_ref": "QCVN 06:2022 §1.1",
            "required": True,
            "status": "done",
        },
        {
            "id": "fire-approval",
            "title": "Phe duyet PCCC",
            "description": None,
            "regulation_ref": None,
            "required": True,
            "status": "in_progress",
            "notes": "Cho ket qua tham dinh.",
        },
        {
            "id": "env-impact",
            "title": "Danh gia moi truong",
            "description": "DTM cap 1.",
            "regulation_ref": None,
            "required": False,
            "status": "pending",
        },
    ]
    pdf = render_permit_checklist_pdf(
        checklist_id="00000000-0000-0000-0000-000000000abc",
        project_id="proj-42",
        jurisdiction="Ha Noi",
        project_type="residential",
        items=items,
        generated_at=datetime(2026, 4, 28, 10, 0, tzinfo=UTC),
    )

    # Sanity: PDF has the right magic header and is meaningfully sized.
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1500  # less than this would mean the renderer dropped content

    text = _extract_pdf_text(pdf)
    # Every item title surfaces.
    assert "Khao sat hien trang" in text
    assert "Phe duyet PCCC" in text
    assert "Danh gia moi truong" in text
    # Jurisdiction + project_type from the header block.
    assert "Ha Noi" in text
    assert "residential" in text
    # Progress summary: 1 of 3 done = 33%.
    assert "1/3" in text
    assert "33%" in text
    # Notes from the in_progress item surface so the export captures
    # the user's annotations, not just the LLM-generated structure.
    assert "Cho ket qua tham dinh" in text


def test_renderer_handles_empty_items():
    """Empty checklist (LLM returned no items) renders the "trống"
    advisory rather than crashing on the loop. Mirrors the in-browser
    empty-state UX so the PDF is honest about what was generated."""
    from services.codeguard_pdf import render_permit_checklist_pdf

    pdf = render_permit_checklist_pdf(
        checklist_id="11111111-1111-1111-1111-111111111111",
        project_id=None,
        jurisdiction="HCM",
        project_type="commercial",
        items=[],
        generated_at=datetime(2026, 4, 28, 10, 0, tzinfo=UTC),
    )
    assert pdf[:4] == b"%PDF"
    text = _extract_pdf_text(pdf)
    assert "Checklist trống" in text
    assert "0/0" in text


def test_renderer_escapes_xml_special_chars_in_user_text():
    """Reportlab Paragraphs interpret a subset of XML; user-supplied
    text containing `<`, `>`, `&` would otherwise break parsing or
    inject markup. Pin the escape contract so an item with `<script>`
    in its title doesn't blow up the renderer."""
    from services.codeguard_pdf import render_permit_checklist_pdf

    items = [
        {
            "id": "x",
            "title": "Item with <special> & ampersand",
            "description": None,
            "regulation_ref": None,
            "required": True,
            "status": "pending",
        }
    ]
    pdf = render_permit_checklist_pdf(
        checklist_id="22222222-2222-2222-2222-222222222222",
        project_id=None,
        jurisdiction="HCM",
        project_type="residential",
        items=items,
        generated_at=datetime(2026, 4, 28, 10, 0, tzinfo=UTC),
    )
    text = _extract_pdf_text(pdf)
    # The literal characters appear in the extracted text — proves
    # the escape preserved them rather than dropping or mis-rendering.
    assert "<special>" in text
    assert "&" in text


# ---------- Route ---------------------------------------------------------


async def test_pdf_route_returns_pdf_for_org_owned_checklist(client, fake_db, fake_auth, monkeypatch):
    """Happy path: the route loads the org-owned checklist, calls the
    renderer, returns `application/pdf`. Pin the Content-Disposition
    shape so dashboards or download trackers can rely on the filename
    pattern."""
    from models.codeguard import PermitChecklist as PermitChecklistModel

    checklist_id = uuid4()
    checklist = MagicMock(spec=PermitChecklistModel)
    checklist.id = checklist_id
    checklist.organization_id = fake_auth.organization_id
    checklist.project_id = uuid4()
    checklist.jurisdiction = "Ha Noi"
    checklist.project_type = "residential"
    checklist.generated_at = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    checklist.completed_at = None
    checklist.items = [
        {
            "id": "x",
            "title": "Test Item",
            "description": "abc",
            "regulation_ref": None,
            "required": True,
            "status": "pending",
        }
    ]
    fake_db.set_get(PermitChecklistModel, checklist_id, checklist)

    res = await client.get(f"/api/v1/codeguard/permit-checklist/{checklist_id}/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    cd = res.headers.get("content-disposition", "")
    assert "attachment" in cd
    # Filename includes the checklist id so multiple exports don't
    # collide in a downloads folder.
    assert str(checklist_id) in cd
    # Body is a real PDF (matches magic header, meaningful size).
    body = res.content
    assert body[:4] == b"%PDF"
    assert len(body) > 1500


async def test_pdf_route_returns_404_for_unknown_id(client, fake_db):
    """Unknown UUID → 404. Pin so a path-traversal-style probe gets a
    clean 404 envelope rather than leaking that the id format is
    valid."""
    res = await client.get(f"/api/v1/codeguard/permit-checklist/{uuid4()}/pdf")
    assert res.status_code == 404


async def test_pdf_route_returns_404_for_cross_org_access(client, fake_db, fake_auth):
    """Tenant isolation: a checklist belonging to another org returns
    404, NOT 403, so the route doesn't leak the existence of cross-org
    rows. Same shape as `mark_checklist_item`'s check."""
    from models.codeguard import PermitChecklist as PermitChecklistModel

    checklist_id = uuid4()
    other_org = UUID("99999999-9999-9999-9999-999999999999")
    foreign = MagicMock(spec=PermitChecklistModel)
    foreign.organization_id = other_org  # not the caller's org
    fake_db.set_get(PermitChecklistModel, checklist_id, foreign)

    res = await client.get(f"/api/v1/codeguard/permit-checklist/{checklist_id}/pdf")
    assert res.status_code == 404
    assert fake_auth.organization_id != other_org  # sanity
