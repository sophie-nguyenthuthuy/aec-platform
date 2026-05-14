"""PDF renderers for project-level artefacts.

Two flows live in this module — they share the reportlab boilerplate
(margins, VN font registration, footer with generated_at stamp), so
keeping them together avoids the third "_pdf_common.py" abstraction:

  * `render_project_summary_pdf` — single-page snapshot of a project's
    current state: name + owner, schedule progress %, open task count,
    upcoming milestone, defects count. Printed by PMs for weekly
    stakeholder meetings. The data is fetched by the router and passed
    in as a shaped dict so this module stays decoupled from SQL.

  * `render_handover_certificate_pdf` — Biên bản bàn giao công trình:
    the legal handover document SOE customers need to formally
    transfer the asset to the end user (chủ đầu tư). Layout follows
    the QCVN-implied template: header, project + parties block, scope
    table, signature lines for both sides + date.

Why one module, not two: every field crew already knows the project's
"hồ sơ" comes from this page. Splitting "summary" + "handover" across
two services would only fragment imports for callers that need both
(weekly digest + warranty pack-out, both bundle multiple PDFs).
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ._pdf_fonts import ensure_unicode_fonts


_FONT_NORMAL, _FONT_BOLD = ensure_unicode_fonts()


def _style(name: str, **overrides: Any) -> ParagraphStyle:
    """Style factory mirroring services/codeguard_pdf.py — wires the
    VN-capable DejaVu font into every derived style so diacritics
    don't render as `?`.
    """
    base = getSampleStyleSheet()[name]
    overrides.setdefault("fontName", _FONT_NORMAL)
    return ParagraphStyle(name=f"{name}_proj", parent=base, **overrides)


def _fmt_vn_date(d: date | datetime | None) -> str:
    """Vietnamese-standard dd/mm/yyyy. None → em-dash."""
    if d is None:
        return "—"
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%d/%m/%Y")


def _fmt_pct(v: float | int | None) -> str:
    if v is None:
        return "—"
    return f"{round(float(v))}%"


def _fmt_vnd(amount: float | int | None) -> str:
    """Vietnamese dong with thousands separator. None → em-dash."""
    if amount is None:
        return "—"
    return f"{int(amount):,} ₫".replace(",", ".")


# ---------- Project summary ----------


def render_project_summary_pdf(
    *,
    organization_name: str,
    project: dict[str, Any],
    schedule_summary: dict[str, Any] | None,
    open_tasks: int,
    overdue_tasks: int,
    defects_open: int,
    upcoming_milestones: list[dict[str, Any]],
    generated_at: datetime,
) -> bytes:
    """One-page project status snapshot.

    Layout (top-to-bottom):
      * Header strip: org name (small caps), project name (h1),
        project status pill.
      * Two-column meta grid: city/district, budget, area, floors,
        owner email, start/finish dates.
      * KPI strip: schedule %, open tasks, overdue, defects.
      * Upcoming milestones table (top 5 by due_date).
      * Footer: generated_at + AEC Platform tagline.

    All inputs are plain dicts so the router can stitch SQL rows
    without dragging Pydantic schemas in.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Tóm tắt dự án — {project.get('name', '')}",
        author="AEC Platform",
    )

    org_label = _style("BodyText", fontSize=8, textColor=HexColor("#64748b"))
    h1 = _style("Heading1", fontSize=20, leading=24, spaceAfter=2)
    badge = _style("BodyText", fontSize=9, textColor=HexColor("#475569"))
    h2 = _style("Heading2", fontSize=12, leading=15, spaceBefore=10, spaceAfter=6)
    body = _style("BodyText", fontSize=10, leading=13)
    kpi_label = _style("BodyText", fontSize=8, textColor=HexColor("#64748b"))
    kpi_value = _style("Heading1", fontSize=16, leading=20)
    footer = _style("BodyText", fontSize=8, textColor=HexColor("#94a3b8"))

    elements: list[Any] = []
    elements.append(Paragraph(org_label_text(organization_name), org_label))
    elements.append(Paragraph(_escape(project.get("name", "(không có tên)")), h1))
    elements.append(Paragraph(
        f"Trạng thái: <b>{_status_label(project.get('status'))}</b>"
        f" &nbsp;·&nbsp; ID nội bộ: {project.get('external_id') or '—'}",
        badge,
    ))
    elements.append(Spacer(1, 6 * mm))

    # --- Meta grid ---
    addr = project.get("address") or {}
    meta_rows = [
        ["Địa điểm",
         _escape(", ".join(filter(None, [addr.get("district"), addr.get("city")])) or "—"),
         "Diện tích",
         _escape(_fmt_area(project.get("area_sqm")))],
        ["Loại công trình",
         _escape(project.get("type") or "—"),
         "Số tầng",
         str(project.get("floors") or "—")],
        ["Ngân sách",
         _escape(_fmt_vnd(project.get("budget_vnd"))),
         "Chủ đầu tư",
         _escape(project.get("owner_email") or "—")],
        ["Khởi công",
         _fmt_vn_date(project.get("start_date")),
         "Dự kiến hoàn thành",
         _fmt_vn_date(project.get("end_date"))],
    ]
    meta_table = Table(meta_rows, colWidths=[35 * mm, 55 * mm, 35 * mm, 50 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NORMAL),
        ("FONTNAME", (0, 0), (0, -1), _FONT_BOLD),
        ("FONTNAME", (2, 0), (2, -1), _FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), HexColor("#64748b")),
        ("TEXTCOLOR", (2, 0), (2, -1), HexColor("#64748b")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, HexColor("#e2e8f0")),
    ]))
    elements.append(meta_table)

    # --- KPI strip ---
    elements.append(Paragraph("Chỉ số nhanh", h2))
    schedule_pct = (schedule_summary or {}).get("percent_complete")
    schedule_slip = (schedule_summary or {}).get("slip_days")
    kpi_data = [
        [Paragraph("Tiến độ", kpi_label),
         Paragraph("Mở", kpi_label),
         Paragraph("Quá hạn", kpi_label),
         Paragraph("Tồn đọng", kpi_label)],
        [Paragraph(_fmt_pct(schedule_pct), kpi_value),
         Paragraph(str(open_tasks), kpi_value),
         Paragraph(str(overdue_tasks), kpi_value),
         Paragraph(str(defects_open), kpi_value)],
    ]
    kpi_table = Table(kpi_data, colWidths=[42 * mm] * 4, rowHeights=[6 * mm, 10 * mm])
    kpi_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.3, HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(kpi_table)

    if schedule_slip is not None and schedule_slip > 0:
        elements.append(Spacer(1, 3 * mm))
        elements.append(Paragraph(
            f"<b>Cảnh báo trễ:</b> đường găng đang chậm {int(schedule_slip)} ngày so với baseline.",
            _style("BodyText", fontSize=9, textColor=HexColor("#b91c1c")),
        ))

    # --- Upcoming milestones ---
    elements.append(Paragraph("Mốc tiến độ sắp tới", h2))
    if not upcoming_milestones:
        elements.append(Paragraph(
            "Chưa có mốc nào trong 30 ngày tới.",
            _style("BodyText", fontSize=9.5, textColor=HexColor("#64748b")),
        ))
    else:
        rows = [["Mã", "Tên hoạt động", "Dự kiến hoàn thành", "% Hoàn thành"]]
        for m in upcoming_milestones[:5]:
            rows.append([
                _escape(m.get("code") or "—"),
                _escape(m.get("name") or "—"),
                _fmt_vn_date(m.get("planned_finish")),
                _fmt_pct(m.get("percent_complete")),
            ])
        ms_table = Table(rows, colWidths=[22 * mm, 92 * mm, 32 * mm, 28 * mm], repeatRows=1)
        ms_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _FONT_NORMAL),
            ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#e2e8f0")),
            ("ALIGN", (3, 1), (3, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, HexColor("#e2e8f0")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
        ]))
        elements.append(ms_table)

    # --- Footer ---
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph(
        f"Tạo lúc {generated_at.strftime('%H:%M %d/%m/%Y')} · AEC Platform",
        footer,
    ))

    doc.build(elements)
    return buf.getvalue()


# ---------- Handover certificate ----------


def render_handover_certificate_pdf(
    *,
    organization_name: str,
    project_name: str,
    package_name: str,
    delivering_party: str,
    receiving_party: str,
    handover_location: str,
    delivered_at: date | datetime,
    scope_items: list[dict[str, Any]],
    attachments_count: int,
    generated_at: datetime,
) -> bytes:
    """Biên bản bàn giao công trình.

    Mimics the Vietnamese-construction-industry-standard handover
    certificate layout:

      * National header line ("CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM —
        Độc lập - Tự do - Hạnh phúc") — required by SOE convention.
      * Title "BIÊN BẢN BÀN GIAO CÔNG TRÌNH" centred.
      * Date + location line.
      * Parties block (Bên giao / Bên nhận).
      * Scope table.
      * Attachments count line.
      * Two signature blocks (left + right).
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Biên bản bàn giao — {project_name}",
        author="AEC Platform",
    )

    national = _style(
        "BodyText",
        fontSize=11,
        alignment=1,  # centre
        fontName=_FONT_BOLD,
    )
    national_sub = _style(
        "BodyText",
        fontSize=10,
        alignment=1,
        fontName=_FONT_BOLD,
    )
    title = _style(
        "Heading1",
        fontSize=18,
        leading=22,
        alignment=1,
        fontName=_FONT_BOLD,
        spaceBefore=8,
        spaceAfter=8,
    )
    meta = _style("BodyText", fontSize=10.5, alignment=1)
    section = _style("Heading2", fontSize=12, fontName=_FONT_BOLD, spaceBefore=10, spaceAfter=4)
    body = _style("BodyText", fontSize=10.5, leading=14)
    sig_label = _style("BodyText", fontSize=10.5, alignment=1, fontName=_FONT_BOLD)
    sig_hint = _style("BodyText", fontSize=9, alignment=1, textColor=HexColor("#64748b"))
    footer = _style("BodyText", fontSize=8, textColor=HexColor("#94a3b8"))

    elements: list[Any] = []

    # --- National header (SOE convention) ---
    elements.append(Paragraph("CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM", national))
    elements.append(Paragraph("Độc lập - Tự do - Hạnh phúc", national_sub))
    elements.append(Spacer(1, 2 * mm))
    # Underline under "Hạnh phúc" — drawn via a small horizontal rule
    line = Table([[""]], colWidths=[40 * mm], rowHeights=[1])
    line.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, black),
    ]))
    line.hAlign = "CENTER"
    elements.append(line)

    # --- Title ---
    elements.append(Paragraph("BIÊN BẢN BÀN GIAO CÔNG TRÌNH", title))

    # --- Location + date ---
    delivered_date = delivered_at.date() if isinstance(delivered_at, datetime) else delivered_at
    elements.append(Paragraph(
        f"<i>{_escape(handover_location)}, ngày {delivered_date.day:02d} "
        f"tháng {delivered_date.month:02d} năm {delivered_date.year}</i>",
        meta,
    ))
    elements.append(Spacer(1, 6 * mm))

    # --- Project block ---
    elements.append(Paragraph("Hôm nay, các bên gồm có:", body))
    elements.append(Spacer(1, 3 * mm))

    parties_data = [
        ["BÊN GIAO (Bên A):", _escape(delivering_party)],
        ["BÊN NHẬN (Bên B):", _escape(receiving_party)],
        ["Công trình bàn giao:", _escape(project_name)],
        ["Gói bàn giao:", _escape(package_name)],
    ]
    parties_table = Table(parties_data, colWidths=[50 * mm, 110 * mm])
    parties_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), _FONT_BOLD),
        ("FONTNAME", (1, 0), (1, -1), _FONT_NORMAL),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(parties_table)

    # --- Scope ---
    elements.append(Paragraph("Phạm vi bàn giao", section))
    if not scope_items:
        elements.append(Paragraph("Không có hạng mục được liệt kê.", body))
    else:
        scope_rows = [["STT", "Hạng mục", "Trạng thái", "Ghi chú"]]
        for i, item in enumerate(scope_items, start=1):
            scope_rows.append([
                str(i),
                _escape(item.get("title") or "—"),
                _escape(_handover_status_label(item.get("status"))),
                _escape(item.get("notes") or ""),
            ])
        scope_table = Table(
            scope_rows,
            colWidths=[12 * mm, 90 * mm, 28 * mm, 40 * mm],
            repeatRows=1,
        )
        scope_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _FONT_NORMAL),
            ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, HexColor("#94a3b8")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#475569")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(scope_table)

    # --- Attachments line ---
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(
        f"Kèm theo biên bản: <b>{attachments_count}</b> tệp tài liệu "
        f"(bản vẽ hoàn công, sổ tay vận hành, chứng chỉ bảo hành).",
        body,
    ))

    # --- Closing statement ---
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(
        "Hai bên đã cùng đối chiếu, xác nhận các hạng mục bàn giao "
        "theo nội dung trên và lập biên bản này thành 02 (hai) bản có "
        "giá trị pháp lý như nhau, mỗi bên giữ 01 (một) bản để theo dõi.",
        body,
    ))

    # --- Signature blocks ---
    elements.append(Spacer(1, 10 * mm))
    sig_data = [
        [Paragraph("ĐẠI DIỆN BÊN GIAO", sig_label),
         Paragraph("ĐẠI DIỆN BÊN NHẬN", sig_label)],
        [Paragraph("<i>(Ký, ghi rõ họ tên và đóng dấu)</i>", sig_hint),
         Paragraph("<i>(Ký, ghi rõ họ tên và đóng dấu)</i>", sig_hint)],
        [Paragraph("&nbsp;<br/>&nbsp;<br/>&nbsp;<br/>", body),
         Paragraph("&nbsp;<br/>&nbsp;<br/>&nbsp;<br/>", body)],
    ]
    sig_table = Table(sig_data, colWidths=[80 * mm, 80 * mm])
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(sig_table)

    # --- Footer ---
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph(
        f"Tổ chức: {_escape(organization_name)} · "
        f"Tạo bởi AEC Platform · {generated_at.strftime('%H:%M %d/%m/%Y')}",
        footer,
    ))

    doc.build(elements)
    return buf.getvalue()


# ---------- Display helpers ----------


def _escape(value: str | None) -> str:
    """Reportlab Paragraph uses pseudo-HTML; escape `<` / `&` so a stray
    `<3` or `&` in user data doesn't break the layout."""
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def org_label_text(name: str) -> str:
    return _escape(name).upper()


def _status_label(status: str | None) -> str:
    return {
        "planning": "Lập kế hoạch",
        "design": "Thiết kế",
        "bidding": "Đấu thầu",
        "construction": "Đang thi công",
        "handover": "Bàn giao",
        "completed": "Hoàn thành",
        "on_hold": "Tạm dừng",
        "cancelled": "Đã huỷ",
    }.get(status or "", status or "—")


def _handover_status_label(status: str | None) -> str:
    return {
        "pending": "Chưa làm",
        "in_progress": "Đang làm",
        "done": "Hoàn thành",
        "blocked": "Bị chặn",
        "not_applicable": "Không áp dụng",
    }.get(status or "", status or "—")


def _fmt_area(sqm: float | int | None) -> str:
    if sqm is None:
        return "—"
    return f"{float(sqm):,.0f} m²".replace(",", ".")
