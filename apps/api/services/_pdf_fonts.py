"""Shared reportlab font registration — Vietnamese-capable.

reportlab's default Helvetica uses WinAnsiEncoding, which can't render
precomposed Vietnamese diacritics (ố, ạ, ữ, ố, ầ…). Without registering
a Unicode-aware TTF, those characters silently become `?` glyphs in the
rendered PDF.

This module bundles DejaVu Sans (full Vietnamese coverage, public-domain
license — see ``fonts/LICENSE.md``) and registers it once per process.
TTFont registration is process-global, so repeated calls hit reportlab's
cache and are effectively free.

Used by:
  * ``services.codeguard_pdf`` — permit-checklist export
  * ``services.boq_io.pdf`` — BOQ export

Returns a ``(normal, bold)`` tuple of the registered font names. On any
failure (missing TTFs, TTFont read error) it falls back to
``("Helvetica", "Helvetica-Bold")`` and logs at WARNING — degraded but
non-fatal so a misplaced `fonts/` directory doesn't 5xx the export
endpoint.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Stable identifiers in reportlab's process-global font table.
_FONT_NORMAL = "AECDejaVuSans"
_FONT_BOLD = "AECDejaVuSans-Bold"

# Bundled fonts live alongside this module so the helper has zero
# external knowledge of where it sits in the import tree.
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")


def ensure_unicode_fonts() -> tuple[str, str]:
    """Register the bundled Vietnamese-capable TTFs once per process.

    Returns ``(normal_font_name, bold_font_name)`` to use in
    reportlab ``ParagraphStyle(fontName=…)`` and ``TableStyle('FONTNAME', …)``
    declarations.
    """
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:  # pragma: no cover — gated by reportlab being installed
        return "Helvetica", "Helvetica-Bold"

    # Already registered? `getRegisteredFontNames` returns a set on
    # modern reportlab; tolerate the older list shape defensively.
    try:
        registered = set(pdfmetrics.getRegisteredFontNames())
    except Exception:  # pragma: no cover — defensive
        registered = set()
    if _FONT_NORMAL in registered and _FONT_BOLD in registered:
        return _FONT_NORMAL, _FONT_BOLD

    normal_path = os.path.join(_FONTS_DIR, "DejaVuSans.ttf")
    bold_path = os.path.join(_FONTS_DIR, "DejaVuSans-Bold.ttf")

    if not (os.path.exists(normal_path) and os.path.exists(bold_path)):
        logger.warning(
            "_pdf_fonts: bundled DejaVu fonts not found at %s — "
            "Vietnamese diacritics will be mangled. Re-deploy with the fonts/ "
            "directory present.",
            _FONTS_DIR,
        )
        return "Helvetica", "Helvetica-Bold"

    try:
        pdfmetrics.registerFont(TTFont(_FONT_NORMAL, normal_path))
        pdfmetrics.registerFont(TTFont(_FONT_BOLD, bold_path))
        # Family registration so reportlab's `<b>...</b>` markup picks
        # the bold variant automatically inside `Paragraph` text. Without
        # this, inline-bold passages fall back to Helvetica-Bold + WinAnsi
        # and the diacritics inside them mangle even though the surrounding
        # paragraph is Unicode-clean.
        pdfmetrics.registerFontFamily(
            _FONT_NORMAL,
            normal=_FONT_NORMAL,
            bold=_FONT_BOLD,
            italic=_FONT_NORMAL,  # no italic variant bundled
            boldItalic=_FONT_BOLD,
        )
    except Exception as exc:  # pragma: no cover — TTFont read errors
        logger.warning(
            "_pdf_fonts: TTFont registration failed (%s); falling back to Helvetica",
            exc,
        )
        return "Helvetica", "Helvetica-Bold"

    return _FONT_NORMAL, _FONT_BOLD
