"""File MIME type allowlist (cycle II2, Python half).

Server-side mirror of `apps/web/lib/mime-allowlist.ts`. Used by:

  * The upload endpoint validator (rejects malformed MIME with
    HTTP 422 before the file lands in storage).
  * The avatar uploader API.
  * The audit-evidence attach endpoint.

  is_allowed_mime(type, category)  — bool
  accepted_extensions(category)    — tuple[str, ...]
  MIME_CATEGORIES                  — closed tuple
  MIME_ALLOWLIST                   — frozen category → frozenset

Pinned defenses:
  * SVG explicitly NOT in `photo` (XSS via embedded `<script>`).
  * `application/octet-stream` rejected for ALL categories.
  * HEIC accepted in `photo` (iPhone uploads dominant in VN).

Pure stdlib.
"""

from __future__ import annotations

from typing import Literal

MimeCategory = Literal["photo", "document", "cad", "archive"]


MIME_CATEGORIES: tuple[MimeCategory, ...] = (
    "photo",
    "document",
    "cad",
    "archive",
)


# Closed allowlist. All entries lowercased. Adding a new MIME
# requires touching this AND the TS half AND adding the
# extension to _ACCEPTED_EXTENSIONS — three-way pin enforced
# by tests.
MIME_ALLOWLIST: dict[MimeCategory, frozenset[str]] = {
    "photo": frozenset(
        {
            "image/jpeg",
            "image/png",
            "image/heic",
            "image/webp",
        }
    ),
    "document": frozenset(
        {
            "application/pdf",
        }
    ),
    "cad": frozenset(
        {
            "application/acad",
            "image/vnd.dwg",
            "application/vnd.dxf",
        }
    ),
    "archive": frozenset(
        {
            "application/zip",
        }
    ),
}


_ACCEPTED_EXTENSIONS: dict[MimeCategory, tuple[str, ...]] = {
    "photo": (".jpg", ".jpeg", ".png", ".heic", ".webp"),
    "document": (".pdf",),
    "cad": (".dwg", ".dxf"),
    "archive": (".zip",),
}


def is_allowed_mime(
    mime_type: str | None,
    category: MimeCategory,
) -> bool:
    """True iff `mime_type` is in the allowlist for `category`.

    Defensive normalisation:
      * Lowercased on comparison.
      * Whitespace stripped.
      * MIME parameters stripped (`image/jpeg; charset=binary`
        → `image/jpeg`).
      * Empty / None → False.
    """
    if not mime_type:
        return False
    lower = mime_type.lower().strip()
    base_type = lower.split(";")[0].strip()
    return base_type in MIME_ALLOWLIST.get(category, frozenset())


def accepted_extensions(category: MimeCategory) -> tuple[str, ...]:
    """File extensions accepted by `category`. Used by the API
    `accept=` hint emitted in upload-config endpoints."""
    return _ACCEPTED_EXTENSIONS.get(category, ())
