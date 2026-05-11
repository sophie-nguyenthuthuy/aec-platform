"""File hash prefix display (cycle PP1, Python half).

Server-side mirror of `apps/web/lib/format-hash-prefix.ts`.
Used by the audit row plaintext export, the webhook payload's
file-reference rendering, and the email digest's attachment
list.

  format_hash_prefix(digest, length)  — "a1b2c3d…" or ""

Pinned invariants:
  * Lowercased on output.
  * Whitespace + outer quotes stripped.
  * Non-hex → "".
  * Length out of [MIN, MAX] → "" (NOT clamped).
  * ELLIPSIS is U+2026 single char.
  * Cross-language byte-for-byte parity.

Pure stdlib.
"""

from __future__ import annotations

import re

MIN_HASH_PREFIX_LENGTH = 4
MAX_HASH_PREFIX_LENGTH = 64
DEFAULT_HASH_PREFIX_LENGTH = 7


# Unicode horizontal ellipsis (U+2026). Single char.
ELLIPSIS = "…"


_HEX_RE = re.compile(r"^[0-9a-f]+$")


def format_hash_prefix(
    digest: str | None,
    length: int = DEFAULT_HASH_PREFIX_LENGTH,
) -> str:
    """Format a hex digest as a short display prefix.

    * format_hash_prefix("a1b2c3d4e5f6")     → "a1b2c3d…"
    * format_hash_prefix("A1B2C3D4E5F6")     → "a1b2c3d…"
    * format_hash_prefix("a1b2c3", 7)        → "a1b2c3"
    * format_hash_prefix("not-hex")          → ""
    * format_hash_prefix(None)               → ""
    """
    if not digest:
        return ""
    if not (MIN_HASH_PREFIX_LENGTH <= length <= MAX_HASH_PREFIX_LENGTH):
        return ""

    cleaned = digest.strip()

    # Strip outer matching quotes (both `"` and `'`).
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1]

    cleaned = cleaned.lower()

    if not _HEX_RE.match(cleaned):
        return ""

    if len(cleaned) <= length:
        return cleaned
    return cleaned[:length] + ELLIPSIS
