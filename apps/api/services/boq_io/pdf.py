"""PDF BOQ adapter — lazy `reportlab` import + thin core delegation.

`render_boq_pdf` lays out a one-page-or-many BOQ report using
reportlab's Platypus stack. The shape is deliberately spartan:

  * Title (the estimate name) at the top, with the export timestamp.
  * One Platypus `Table` containing the full BOQ. reportlab handles
    page-break splitting automatically — long BOQs flow across pages.
  * Total row at the bottom, in bold.

We don't try to reproduce the buyer's full estimate styling because
the output is meant for sharing with suppliers / authorities, where a
clean tabular dump is more useful than a designed report.

**Font embedding**: reportlab's default Helvetica uses WinAnsiEncoding,
which doesn't include Vietnamese precomposed diacritics ("ố", "ạ",
"ữ", etc.). Material descriptions like "Bê tông cốt thép" get
silently mangled to "Bê tông c?t thép" in the rendered PDF. We bundle
DejaVu Sans (full Vietnamese coverage, public-domain license — see
`fonts/LICENSE.md`) and register it on first use; reportlab's
TTFont registration is process-global, so the second call is free.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from decimal import Decimal

from .core import BoqIOError, BoqRow, rows_to_grid

logger = logging.getLogger(__name__)


def render_boq_pdf(estimate_name: str, rows: list[BoqRow]) -> bytes:
    """Render `rows` to a styled PDF. Raises `BoqIOError` if reportlab missing."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover — deployed env always has it
        raise BoqIOError("reportlab not installed; cannot render .pdf") from exc

    font_normal, font_bold = _ensure_unicode_fonts()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"BOQ — {estimate_name}",
    )
    styles = getSampleStyleSheet()
    # Re-point the styles we use at the registered Unicode fonts.
    # Otherwise reportlab keeps its default Helvetica references and the
    # title / timestamp paragraphs render diacritics as `?`. The body
    # `<b>` tag in `Paragraph` resolves the bold variant via the font
    # family registration done in `_ensure_unicode_fonts`.
    for style_name in ("Heading1", "Heading3", "Italic", "Normal"):
        if style_name in styles.byName:
            styles.byName[style_name].fontName = font_normal

    story = []

    story.append(Paragraph(f"<b>BOQ — {estimate_name}</b>", styles["Heading1"]))
    story.append(
        Paragraph(
            f"Exported {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            styles["Italic"],
        )
    )
    story.append(Spacer(1, 6 * mm))

    header_cells, body_cells = rows_to_grid(rows)
    pretty_body = [[_pretty_cell(c) for c in row] for row in body_cells]
    table_data = [header_cells, *pretty_body]

    # Column widths chosen for A4 portrait minus 30mm margins ≈ 180mm.
    # Description gets the lion's share; numerics are sized for VND
    # totals (10-digit scale).
    col_widths_mm = [18, 60, 14, 18, 22, 22, 26]
    col_widths = [w * mm for w in col_widths_mm]

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                # Body uses the Unicode font; header overrides to bold.
                # Both must be the registered DejaVu names — otherwise
                # the cells fall back to Helvetica + WinAnsi and
                # Vietnamese diacritics render as `?` again.
                ("FONTNAME", (0, 0), (-1, -1), font_normal),
                ("FONTNAME", (0, 0), (-1, 0), font_bold),
                # Header.
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                # Body.
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                # Numeric columns right-aligned (matches _EXPORT_HEADERS).
                ("ALIGN", (3, 1), (5, -1), "RIGHT"),
                # Row separator lines.
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
            ]
        )
    )
    story.append(table)

    # Total row.
    total = _grand_total(rows)
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            f"<b>Grand total: {_format_vnd(total)}</b>",
            styles["Heading3"],
        )
    )

    doc.build(story)
    return buffer.getvalue()


# ---------- Unicode font registration ----------


# Font registration moved to `services._pdf_fonts` so the codeguard PDF
# renderer can share the same DejaVu Sans setup. The thin alias below
# preserves the existing call-sites in this module without paying the
# import-cycle cost of pulling `_pdf_fonts` at module top.
def _ensure_unicode_fonts() -> tuple[str, str]:
    from .._pdf_fonts import ensure_unicode_fonts

    return ensure_unicode_fonts()


def _pretty_cell(value: object) -> str:
    """Render a row cell for the PDF table.

    Numbers get thousand separators; non-numerics pass through. We avoid
    using a Paragraph wrapper here because the table is large and the
    extra boxing would balloon page-render time.
    """
    if value == "" or value is None:
        return ""
    if isinstance(value, (int, float)):
        return _format_number(value)
    return str(value)


def _format_number(n: float) -> str:
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.2f}"
    return f"{int(n):,}"


def _format_vnd(amount: Decimal | None) -> str:
    if amount is None:
        return "—"
    return f"{int(amount):,} VND"


def _grand_total(rows: list[BoqRow]) -> Decimal | None:
    total = Decimal("0")
    seen_any = False
    for r in rows:
        candidate = r.total_price_vnd
        if candidate is None and r.quantity is not None and r.unit_price_vnd is not None:
            try:
                candidate = r.quantity * r.unit_price_vnd
            except Exception:  # pragma: no cover — defensive
                candidate = None
        if candidate is None:
            continue
        total += candidate
        seen_any = True
    return total if seen_any else None
