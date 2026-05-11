"""File extension validator (cycle TT2).

Pinned seams:
  1. Last `.` in basename is the separator.
  2. Hidden files (`.gitignore`) → no extension.
  3. Hidden files with extension (`.env.local`) → `.local`.
  4. Case-insensitive (output lowercase).
  5. Composes with II2 accepted_extensions.
"""

from __future__ import annotations

from services.file_extension import extension_of, is_allowed_extension
from services.mime_allowlist import accepted_extensions

# ---------- extension_of ----------


def test_simple_extension():
    assert extension_of("photo.jpg") == ".jpg"


def test_extension_lowercased():
    assert extension_of("photo.JPG") == ".jpg"
    assert extension_of("photo.JpG") == ".jpg"


def test_compound_extension_takes_last():
    """Cardinal pin: `foo.tar.gz` → `.gz` (NOT `.tar.gz`).
    Pin so a refactor that special-cases compound extensions
    surfaces here. Most filesystems / OSes treat the LAST dot
    as the extension separator."""
    assert extension_of("backup.tar.gz") == ".gz"
    assert extension_of("file.min.js") == ".js"


def test_no_extension():
    assert extension_of("noext") == ""
    assert extension_of("README") == ""


def test_hidden_file_no_extension():
    """Cardinal pin: `.gitignore` → "" (hidden file, no extension).
    The leading `.` marks a hidden file, NOT an extension separator."""
    assert extension_of(".gitignore") == ""
    assert extension_of(".env") == ""
    assert extension_of(".bashrc") == ""


def test_hidden_file_with_extension():
    """Pin: `.env.local` → `.local`. The leading `.` is the
    hidden-file marker; the SECOND `.` is the extension separator."""
    assert extension_of(".env.local") == ".local"
    assert extension_of(".config.json") == ".json"


def test_basename_extracted():
    """Path components stripped — only basename's extension."""
    assert extension_of("path/to/file.pdf") == ".pdf"
    assert extension_of("/absolute/path/file.pdf") == ".pdf"


def test_empty_returns_empty():
    assert extension_of("") == ""


def test_none_returns_empty():
    assert extension_of(None) == ""


def test_whitespace_filename():
    """Whitespace-only filename has no useful basename."""
    # path.basename("  ") on POSIX is "  ". rfind('.') is -1. → ""
    assert extension_of("   ") == ""


def test_dot_only():
    """`.` alone is just a dot — no extension."""
    assert extension_of(".") == ""


def test_multiple_dots():
    assert extension_of("a.b.c.d.e") == ".e"


# ---------- is_allowed_extension ----------


def test_jpg_allowed_in_photo():
    assert is_allowed_extension("photo.jpg", "photo") is True


def test_jpg_uppercase_allowed_in_photo():
    """Case-insensitive against II2 allowlist."""
    assert is_allowed_extension("photo.JPG", "photo") is True


def test_jpeg_allowed_in_photo():
    assert is_allowed_extension("photo.jpeg", "photo") is True


def test_png_allowed_in_photo():
    assert is_allowed_extension("photo.png", "photo") is True


def test_heic_allowed_in_photo():
    """Cardinal pin: HEIC accepted (iPhone uploads dominant in VN)."""
    assert is_allowed_extension("photo.heic", "photo") is True


def test_pdf_allowed_in_document():
    assert is_allowed_extension("doc.pdf", "document") is True


def test_pdf_NOT_allowed_in_photo():
    """Cross-category isolation."""
    assert is_allowed_extension("doc.pdf", "photo") is False


def test_dwg_allowed_in_cad():
    assert is_allowed_extension("plan.dwg", "cad") is True


def test_dxf_allowed_in_cad():
    assert is_allowed_extension("plan.dxf", "cad") is True


def test_zip_allowed_in_archive():
    assert is_allowed_extension("backup.zip", "archive") is True


# ---------- Rejected extensions ----------


def test_svg_NOT_allowed_in_photo():
    """Pin: SVG explicitly excluded (XSS risk per II2)."""
    assert is_allowed_extension("photo.svg", "photo") is False


def test_exe_NOT_allowed_anywhere():
    """Pin: arbitrary executables rejected everywhere."""
    for category in ("photo", "document", "cad", "archive"):
        assert is_allowed_extension("malware.exe", category) is False


def test_compound_archive_rejected():
    """`foo.tar.gz` → `.gz` extension. II2 only allows `.zip`
    for archive — `.gz` rejected. Pin so a refactor that
    handles compound archives without updating II2 surfaces."""
    assert is_allowed_extension("backup.tar.gz", "archive") is False


# ---------- Defensive ----------


def test_empty_filename_rejected():
    assert is_allowed_extension("", "photo") is False


def test_none_filename_rejected():
    assert is_allowed_extension(None, "photo") is False


def test_no_extension_rejected():
    assert is_allowed_extension("README", "photo") is False
    assert is_allowed_extension(".gitignore", "document") is False


# ---------- Cross-cycle composition with II2 ----------


def test_composes_with_ii2_accepted_extensions():
    """Cross-cycle pin: this module's `is_allowed_extension`
    delegates to II2's `accepted_extensions`. Verify that adding
    an extension to II2 makes it pass here."""
    photo_exts = accepted_extensions("photo")
    for ext in photo_exts:
        filename = f"file{ext}"
        assert is_allowed_extension(filename, "photo") is True, (
            f"II2 says {ext} allowed in photo; this module disagrees"
        )


def test_ii2_alignment_for_all_categories():
    """Pin: every II2-allowed extension passes this module's check."""
    for category in ("photo", "document", "cad", "archive"):
        for ext in accepted_extensions(category):
            filename = f"file{ext}"
            assert is_allowed_extension(filename, category) is True
