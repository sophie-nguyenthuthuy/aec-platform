"""File extension validator (cycle TT2).

Composes II2's `accepted_extensions(category)`. Used by the
upload endpoint as defense-in-depth: server validates BOTH the
file extension (what users see) AND the MIME type (what content
claims). Today the upload validator and the audit row's
attachment-type detector each parse extensions inline.

  extension_of(filename)                — ".jpg" / ""
  is_allowed_extension(filename, cat)   — bool against II2 allowlist

Pinned invariants:
  * Last `.` in basename is the extension separator. `foo.tar.gz`
    → `.gz` (NOT `.tar.gz` — pin so a refactor that handles
    compound extensions doesn't slip past).
  * Hidden files (`.gitignore`, `.env`) → no extension. The
    leading `.` is a hidden-file marker, NOT an extension.
  * `.env.local` → `.local` (hidden file with extension).
  * Case-insensitive comparison; output lowercased with leading `.`.
  * Empty / None → "".
  * Composes with II2 — direct import in tests.

Pure stdlib + II2.
"""

from __future__ import annotations

import os.path

from services.mime_allowlist import MimeCategory, accepted_extensions


def extension_of(filename: str | None) -> str:
    """Return the file extension (with leading `.`, lowercased)
    or empty string.

      * extension_of("photo.jpg")     → ".jpg"
      * extension_of("photo.JPG")     → ".jpg"
      * extension_of("foo.tar.gz")    → ".gz"   (last dot only)
      * extension_of(".gitignore")    → ""      (hidden file)
      * extension_of(".env.local")    → ".local"
      * extension_of("noext")         → ""
      * extension_of("path/to/file.pdf") → ".pdf"
    """
    if not filename:
        return ""
    basename = os.path.basename(filename)
    if not basename:
        return ""
    # Last `.` in basename is the separator. If at position 0,
    # the file is a hidden file (`.gitignore`) and has no extension.
    last_dot = basename.rfind(".")
    if last_dot <= 0:
        return ""
    return basename[last_dot:].lower()


def is_allowed_extension(
    filename: str | None,
    category: MimeCategory,
) -> bool:
    """True iff the filename's extension is in II2's category
    allowlist.

    Defensive: empty / no-extension filenames return False (the
    upload widget should always have a filename for legitimate
    files).
    """
    ext = extension_of(filename)
    if not ext:
        return False
    allowed = accepted_extensions(category)
    if not allowed:
        return False
    # II2 stores extensions lowercased — direct compare.
    return ext in allowed
