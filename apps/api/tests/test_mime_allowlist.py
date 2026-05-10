"""File MIME type allowlist (cycle II2, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/mime-allowlist.test.ts`):
  1. MIME_CATEGORIES = (photo, document, cad, archive).
  2. SVG NOT in photo (XSS guard).
  3. application/octet-stream rejected for ALL categories.
  4. HEIC accepted in photo (iPhone uploads).
  5. Comparison case-insensitive.
  6. MIME parameters stripped before comparison.
  7. None / empty → False.
"""

from __future__ import annotations

from services.mime_allowlist import (
    MIME_ALLOWLIST,
    MIME_CATEGORIES,
    accepted_extensions,
    is_allowed_mime,
)

# ---------- MIME_CATEGORIES ----------


def test_mime_categories_canonical():
    assert MIME_CATEGORIES == ("photo", "document", "cad", "archive")


# ---------- photo ----------


def test_photo_accepts_jpeg():
    assert is_allowed_mime("image/jpeg", "photo") is True


def test_photo_accepts_png():
    assert is_allowed_mime("image/png", "photo") is True


def test_photo_accepts_heic():
    """Cardinal pin: HEIC is iPhone's default. Rejecting would
    block VN's iPhone-heavy user base from uploading photos."""
    assert is_allowed_mime("image/heic", "photo") is True


def test_photo_accepts_webp():
    assert is_allowed_mime("image/webp", "photo") is True


def test_photo_rejects_svg():
    """Cardinal pin: SVG carries executable JS. A refactor that
    re-adds it would silently re-introduce an XSS path."""
    assert is_allowed_mime("image/svg+xml", "photo") is False


def test_photo_rejects_bmp():
    assert is_allowed_mime("image/bmp", "photo") is False


def test_photo_rejects_gif():
    assert is_allowed_mime("image/gif", "photo") is False


# ---------- document ----------


def test_document_accepts_pdf():
    assert is_allowed_mime("application/pdf", "document") is True


def test_document_rejects_word_doc():
    """Word/Excel docs out of allowlist for now."""
    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert is_allowed_mime(docx_mime, "document") is False


def test_document_rejects_text_plain():
    assert is_allowed_mime("text/plain", "document") is False


# ---------- cad ----------


def test_cad_accepts_dwg_via_acad():
    assert is_allowed_mime("application/acad", "cad") is True


def test_cad_accepts_dwg_via_image_vnd_dwg():
    assert is_allowed_mime("image/vnd.dwg", "cad") is True


def test_cad_accepts_dxf():
    assert is_allowed_mime("application/vnd.dxf", "cad") is True


# ---------- archive ----------


def test_archive_accepts_zip():
    assert is_allowed_mime("application/zip", "archive") is True


def test_archive_rejects_rar():
    assert is_allowed_mime("application/vnd.rar", "archive") is False


# ---------- octet-stream universal rejection ----------


def test_octet_stream_rejected_for_all_categories():
    """Cardinal pin: type-confusion guard. A malicious file
    spoofing `application/octet-stream` could otherwise bypass
    the type allowlist — pin so a refactor that adds it to
    any category surfaces here."""
    for category in MIME_CATEGORIES:
        assert is_allowed_mime("application/octet-stream", category) is False, (
            f"octet-stream should be rejected for category {category!r}"
        )


def test_no_octet_stream_in_allowlist_data():
    """Defense at the data layer: the allowlist itself never
    contains octet-stream."""
    for _category, mimes in MIME_ALLOWLIST.items():
        assert "application/octet-stream" not in mimes


def test_no_svg_in_any_allowlist():
    """Defense at the data layer: SVG never in any category."""
    for _category, mimes in MIME_ALLOWLIST.items():
        assert "image/svg+xml" not in mimes


# ---------- Cross-category isolation ----------


def test_pdf_allowed_for_document_not_photo():
    assert is_allowed_mime("application/pdf", "document") is True
    assert is_allowed_mime("application/pdf", "photo") is False


def test_jpeg_allowed_for_photo_not_document():
    assert is_allowed_mime("image/jpeg", "photo") is True
    assert is_allowed_mime("image/jpeg", "document") is False


# ---------- Normalisation ----------


def test_case_insensitive():
    assert is_allowed_mime("IMAGE/JPEG", "photo") is True
    assert is_allowed_mime("Image/Jpeg", "photo") is True


def test_strips_mime_parameters():
    assert is_allowed_mime("image/jpeg; charset=binary", "photo") is True
    assert is_allowed_mime("image/jpeg;name=foo.jpg", "photo") is True


def test_strips_surrounding_whitespace():
    assert is_allowed_mime("  image/jpeg  ", "photo") is True


# ---------- Defensive ----------


def test_returns_false_for_none_and_empty():
    assert is_allowed_mime(None, "photo") is False
    assert is_allowed_mime("", "photo") is False


# ---------- accepted_extensions ----------


def test_accepted_extensions_photo():
    assert accepted_extensions("photo") == (
        ".jpg",
        ".jpeg",
        ".png",
        ".heic",
        ".webp",
    )


def test_accepted_extensions_document():
    assert accepted_extensions("document") == (".pdf",)


def test_accepted_extensions_cad():
    assert accepted_extensions("cad") == (".dwg", ".dxf")


def test_accepted_extensions_archive():
    assert accepted_extensions("archive") == (".zip",)


# ---------- MIME_ALLOWLIST invariants ----------


def test_allowlist_covers_every_category():
    for category in MIME_CATEGORIES:
        assert category in MIME_ALLOWLIST


def test_photo_has_four_entries():
    assert len(MIME_ALLOWLIST["photo"]) == 4


def test_allowlist_values_are_frozen():
    """Each category's allowlist is a frozenset — pin so a
    refactor can't `MIME_ALLOWLIST['photo'].add(...)` and
    silently broaden the allowlist."""
    for mimes in MIME_ALLOWLIST.values():
        assert isinstance(mimes, frozenset)
