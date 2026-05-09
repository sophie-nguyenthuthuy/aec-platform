"""PDF rendering for CODEGUARD permit checklists.

Compliance officers preparing a real permit application need the
checklist as a portable artifact — readable offline, printable,
sharable with stakeholders who don't have access to the platform.
This module renders a `PermitChecklistModel` row to a PDF byte
stream using `reportlab` (already a dep, see apps/api/requirements.txt
where it ships alongside weasyprint).

Why reportlab not weasyprint: the layout is tabular and structured —
no CSS gymnastics needed. Reportlab's flowable model fits the per-
item card layout naturally and keeps the rendering deterministic
(same input → same byte stream), which makes the smoke test trivial.

The PDF is generated lazily per request, never cached. Permit
checklists are typically small (10–30 items) and exported once at
the end of preparation, so the cost of regeneration is negligible
and freshness matters more than compute.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.lib.colors import HexColor
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

# Status string → display tag. Mirrors the Vietnamese labels the
# frontend uses so the PDF reads consistently with what a user saw
# in the browser before exporting.
_STATUS_LABEL = {
    "pending": "Chưa làm",
    "in_progress": "Đang làm",
    "done": "Hoàn thành",
    "not_applicable": "Không áp dụng",
}

# Status → fill colour for the leading status chip. Picked to print
# legibly on b/w printers (mid-saturation, high-contrast text).
_STATUS_COLOR = {
    "done": HexColor("#10b981"),
    "in_progress": HexColor("#3b82f6"),
    "not_applicable": HexColor("#94a3b8"),
    "pending": HexColor("#cbd5e1"),
}


def _style(name: str, **overrides: Any) -> ParagraphStyle:
    """Get a base style by name and apply overrides — saves typing
    `getSampleStyleSheet()[...]` six times in the layout below.

    The base ``getSampleStyleSheet`` styles default to Helvetica with
    WinAnsiEncoding, which mangles Vietnamese diacritics (ố → ?). We
    register DejaVu Sans on first call and force every derived style
    to use it, including bold variant for inline ``<b>...</b>`` markup
    inside ``Paragraph`` text.
    """
    normal_font, bold_font = ensure_unicode_fonts()
    base = getSampleStyleSheet()[name]
    # If the caller hasn't pinned a font, default to the Unicode-capable
    # one. ``fontName`` controls the *base* run; ``<b>...</b>`` inline
    # picks the bold variant via the family registration in
    # ``ensure_unicode_fonts``.
    overrides.setdefault("fontName", normal_font)
    return ParagraphStyle(name=f"{name}_codeguard", parent=base, **overrides)


# Bold font name for places we set ``FONTNAME`` directly on a Table cell
# — exposed at module scope so the table-style construction below can
# reference it without re-running registration each call.
_FONT_NORMAL, _FONT_BOLD = ensure_unicode_fonts()


def render_permit_checklist_pdf(
    *,
    checklist_id: str,
    project_id: str | None,
    jurisdiction: str,
    project_type: str,
    items: list[dict[str, Any]],
    generated_at: datetime,
    completed_at: datetime | None = None,
) -> bytes:
    """Render a PermitChecklist into a PDF byte stream.

    `items` is the raw JSONB list off `PermitChecklistModel.items`,
    not a list of Pydantic schemas — keeps this module decoupled from
    the API schema layer so it can be reused for batch export jobs
    or tests that synthesise checklist data directly.

    Returns: raw PDF bytes ready to write to a `Response` body.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="CODEGUARD — Checklist cấp phép",
        author="CODEGUARD",
    )

    h1 = _style("Heading1", fontSize=16, leading=20, spaceAfter=4)
    body = _style("BodyText", fontSize=10, leading=13)
    meta = _style("BodyText", fontSize=9, leading=12, textColor=HexColor("#475569"))
    item_title = _style("Heading3", fontSize=11, leading=14, spaceAfter=2)
    item_body = _style("BodyText", fontSize=9, leading=12)
    item_chip = _style("BodyText", fontSize=8, leading=10, textColor=HexColor("#1e293b"))

    flow: list[Any] = []

    # ---------- Header ----------
    flow.append(Paragraph("Checklist cấp phép xây dựng", h1))
    meta_lines = [
        f"<b>Địa phương:</b> {_escape(jurisdiction)}",
        f"<b>Loại công trình:</b> {_escape(project_type)}",
    ]
    if project_id:
        meta_lines.append(f"<b>Mã dự án:</b> {_escape(project_id)}")
    meta_lines.append(f"<b>Tạo lúc:</b> {generated_at.strftime('%Y-%m-%d %H:%M')}")
    if completed_at:
        meta_lines.append(f"<b>Hoàn tất:</b> {completed_at.strftime('%Y-%m-%d %H:%M')}")
    flow.append(Paragraph("<br/>".join(meta_lines), meta))
    flow.append(Spacer(1, 6 * mm))

    # Progress summary — done / total + percent. Mirrors the
    # `<ChecklistView>` header the user sees in-browser.
    done = sum(1 for i in items if i.get("status") == "done")
    total = len(items)
    pct = round((done / total) * 100) if total else 0
    flow.append(
        Paragraph(
            f"<b>Tiến độ:</b> {done}/{total} ({pct}%)",
            body,
        )
    )
    flow.append(Spacer(1, 4 * mm))

    # ---------- Items ----------
    if not items:
        flow.append(
            Paragraph(
                "<i>Checklist trống — chưa có mục nào được tạo.</i>",
                body,
            )
        )
    else:
        for idx, item in enumerate(items, 1):
            flow.append(_render_item(idx, item, item_title, item_body, item_chip))
            flow.append(Spacer(1, 3 * mm))

    # ---------- Footer note ----------
    flow.append(Spacer(1, 8 * mm))
    flow.append(
        Paragraph(
            f"<i>Xuất từ CODEGUARD · Checklist ID: {checklist_id}</i>",
            meta,
        )
    )

    doc.build(flow)
    return buf.getvalue()


def _render_item(
    idx: int,
    item: dict[str, Any],
    title_style: ParagraphStyle,
    body_style: ParagraphStyle,
    chip_style: ParagraphStyle,
) -> Table:
    """Render a single checklist row as a 2-column table:
    status chip on the left, content (title + description + meta) on
    the right. Using a Table rather than a nested layout keeps the
    chip vertically aligned with the title across long descriptions
    that wrap to multiple lines.
    """
    status = item.get("status", "pending") or "pending"
    status_label = _STATUS_LABEL.get(status, status)
    status_colour = _STATUS_COLOR.get(status, HexColor("#cbd5e1"))

    title = item.get("title") or "(không tiêu đề)"
    description = item.get("description")
    regulation_ref = item.get("regulation_ref")
    required = bool(item.get("required", True))
    notes = item.get("notes")

    title_html = f"<b>{idx}. {_escape(title)}</b>"
    if required:
        title_html += " <font color='#b91c1c'>· Bắt buộc</font>"
    if regulation_ref:
        title_html += f" <font color='#475569'>· {_escape(regulation_ref)}</font>"

    content_paragraphs: list[Any] = [Paragraph(title_html, title_style)]
    if description:
        content_paragraphs.append(Paragraph(_escape(description), body_style))
    if notes:
        content_paragraphs.append(Paragraph(f"<b>Ghi chú:</b> {_escape(notes)}", body_style))

    chip = Paragraph(
        f"<b>{_escape(status_label)}</b>",
        chip_style,
    )

    table = Table(
        [[chip, content_paragraphs]],
        colWidths=[28 * mm, None],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, 0), status_colour),
                # Soft outer border on the content cell — keeps items
                # visually distinct without being noisy on print.
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, HexColor("#e2e8f0")),
                ("LEFTPADDING", (0, 0), (0, 0), 6),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
            ]
        )
    )
    return table


def _escape(value: str) -> str:
    """Reportlab Paragraphs interpret a small subset of XML — escape
    the unsafe chars to literal entities so user-supplied text (like
    project_id or regulation_ref) renders verbatim instead of getting
    parsed as malformed markup."""
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
