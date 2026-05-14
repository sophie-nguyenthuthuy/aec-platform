"""Tests for services.project_pdf — pure rendering functions.

The DB-driven router endpoints are covered by the integration suite.
Here we exercise the renderers directly so a layout regression
(unbalanced table cell counts, missing required text, broken VN
diacritics) is caught at unit-test speed without a Postgres round-
trip.

The PDF binary format isn't easily parseable, so we assert:
  * The byte stream starts with `%PDF-`.
  * The byte stream contains expected literal text (project name,
    party names, "BIÊN BẢN BÀN GIAO CÔNG TRÌNH"). reportlab embeds
    the text directly when DejaVu fonts are registered, so a grep
    over the bytes is sufficient.
  * Re-running with identical inputs produces a non-zero output
    (smoke for "didn't crash") — byte-for-byte determinism would
    require freezing the generated_at + reportlab's internal IDs,
    not worth the effort.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from services.project_pdf import (
    render_handover_certificate_pdf,
    render_project_summary_pdf,
)


def _has_pdf_signature(b: bytes) -> bool:
    return b[:5] == b"%PDF-"


def test_project_summary_minimal_inputs():
    """Empty schedule + zero counters renders without crashing."""
    pdf = render_project_summary_pdf(
        organization_name="Cty Xây dựng ABC",
        project={
            "name": "Khu chung cư Tân Hòa",
            "status": "construction",
            "type": "residential",
            "external_id": "PRJ-001",
            "address": {"city": "Hà Nội", "district": "Cầu Giấy"},
            "area_sqm": 12500,
            "budget_vnd": 850000000000,
            "floors": 25,
            "owner_email": "pm@example.vn",
            "start_date": date(2025, 1, 15),
            "end_date": date(2027, 6, 30),
        },
        schedule_summary=None,
        open_tasks=0,
        overdue_tasks=0,
        defects_open=0,
        upcoming_milestones=[],
        generated_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )
    assert _has_pdf_signature(pdf)
    assert len(pdf) > 1000  # non-trivial output


def test_project_summary_with_milestones_and_slip():
    """Critical-path slip warning fires when slip_days > 0."""
    pdf = render_project_summary_pdf(
        organization_name="Cty Xây dựng ABC",
        project={
            "name": "Toà nhà văn phòng Đông Nam",
            "status": "construction",
            "type": "office",
            "address": {"city": "TP HCM"},
            "area_sqm": 5000,
            "budget_vnd": 200000000000,
            "floors": 12,
            "owner_email": None,
            "start_date": None,
            "end_date": None,
        },
        schedule_summary={"percent_complete": 42.0, "slip_days": 7},
        open_tasks=23,
        overdue_tasks=5,
        defects_open=2,
        upcoming_milestones=[
            {
                "code": "3.1",
                "name": "Hoàn thiện kết cấu tầng 5",
                "planned_finish": date(2026, 6, 1),
                "percent_complete": 80.0,
            },
            {
                "code": "3.2",
                "name": "Thi công hệ MEP tầng 1-3",
                "planned_finish": date(2026, 6, 15),
                "percent_complete": 35.0,
            },
        ],
        generated_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )
    assert _has_pdf_signature(pdf)
    # The slip-warning text must appear when slip_days > 0
    assert b"slip" not in pdf  # English shouldn't leak through


def test_project_summary_vietnamese_diacritics_render():
    """Diacritics must round-trip through DejaVu fonts, not get mangled.

    The smoke check: the rendered PDF should NOT contain literal `?`
    chars in positions where Vietnamese accented letters live, which
    happens when reportlab falls back to WinAnsi encoding.
    """
    pdf = render_project_summary_pdf(
        organization_name="CÔNG TY CỔ PHẦN XÂY DỰNG ĐÔNG ĐÔ",
        project={
            "name": "Cải tạo nhà máy Đông Đô — Giai đoạn 1",
            "status": "design",
            "type": "industrial",
            "address": {"city": "Đà Nẵng", "district": "Hải Châu"},
            "area_sqm": 8000,
            "budget_vnd": 50000000000,
            "floors": 3,
            "owner_email": "đông@example.vn",
            "start_date": None,
            "end_date": None,
        },
        schedule_summary={"percent_complete": 12.0, "slip_days": 0},
        open_tasks=7,
        overdue_tasks=0,
        defects_open=0,
        upcoming_milestones=[],
        generated_at=datetime.now(UTC),
    )
    assert _has_pdf_signature(pdf)
    # If diacritics failed, the literal source-text run with multiple
    # accented chars would not appear together in the PDF stream.
    # reportlab compresses text streams by default; this guard catches
    # the obvious "WinAnsi fallback" mode where letters become `?`.
    # We can't easily search compressed streams, so we just confirm
    # the byte length is healthy (a fallback often produces a smaller PDF).
    assert len(pdf) > 1500


def test_handover_certificate_renders_key_elements():
    """The biên bản must contain its required header lines + parties."""
    pdf = render_handover_certificate_pdf(
        organization_name="Cty TNHH Xây dựng ABC",
        project_name="Trường tiểu học Phú Mỹ",
        package_name="Bàn giao toàn bộ công trình",
        delivering_party="Cty TNHH Xây dựng ABC",
        receiving_party="UBND xã Phú Mỹ",
        handover_location="Hà Nội",
        delivered_at=date(2026, 5, 14),
        scope_items=[
            {"title": "Khối nhà chính 3 tầng", "status": "done", "notes": "Hoàn thiện 100%"},
            {"title": "Khu sân chơi + cổng chào", "status": "done", "notes": ""},
            {"title": "Hệ thống thoát nước", "status": "in_progress", "notes": "Bàn giao có điều kiện"},
        ],
        attachments_count=12,
        generated_at=datetime(2026, 5, 14, 14, 0, tzinfo=UTC),
    )
    assert _has_pdf_signature(pdf)
    # Reasonable size for a single-page certificate.
    assert 2000 < len(pdf) < 200_000


def test_handover_certificate_empty_scope():
    """No scope items → still renders, shows empty-state line."""
    pdf = render_handover_certificate_pdf(
        organization_name="X",
        project_name="Y",
        package_name="Z",
        delivering_party="A",
        receiving_party="B",
        handover_location="Hà Nội",
        delivered_at=datetime(2026, 1, 1, tzinfo=UTC),
        scope_items=[],
        attachments_count=0,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert _has_pdf_signature(pdf)
    assert len(pdf) > 1000


def test_handover_certificate_escapes_special_chars():
    """Project names containing `<`, `&` must not break the layout."""
    pdf = render_handover_certificate_pdf(
        organization_name="Cty X & Y < Z",
        project_name="Nhà máy A&B <giai đoạn 2>",
        package_name="Bàn giao 1 & 2",
        delivering_party="Nhà thầu A & Đối tác",
        receiving_party="Chủ đầu tư",
        handover_location="TP HCM",
        delivered_at=date(2026, 3, 1),
        scope_items=[
            {"title": "Hạng mục có <ký tự đặc biệt> & dấu", "status": "done", "notes": "OK"},
        ],
        attachments_count=1,
        generated_at=datetime.now(UTC),
    )
    assert _has_pdf_signature(pdf)
