"""File path safety validator (cycle ZZ1).

Defend against path traversal attacks. Today the file upload
filename validator, audit row attachment-ref builder, and the
resource-link builder each implement traversal checks inline.
This module is the single source of truth.

  is_safe_subpath(base, candidate)  — bool
  safe_join(base, candidate)        — str or None

Pinned defenses (against `..` traversal, absolute escape, null
byte truncation, URL-encoded smuggling, cross-OS path confusion):
  * `..` segments REJECTED — post-normalization can't escape base.
  * Absolute candidate paths REJECTED — must be relative.
  * Null bytes (`\\x00`) REJECTED — defends against C-string
    truncation in downstream tools.
  * URL-encoded `%2e` / `%2f` REJECTED — defends against
    callers that fail to pre-decode.
  * Backslashes REJECTED — defends against cross-OS confusion
    where Windows tools interpret `..\\` as a separator.
  * Empty / whitespace-only candidate REJECTED.
  * `.` (current dir) REJECTED (degenerate).

Pure stdlib (posixpath for OS-independent normalization).
"""

from __future__ import annotations

import os.path
import posixpath


def is_safe_subpath(
    base: str | None,
    candidate: str | None,
) -> bool:
    """True iff `candidate`, after normalization, stays inside `base`.

    See module docstring for full defense list.
    """
    if not base or not candidate:
        return False

    # Null byte truncation defense.
    if "\x00" in candidate:
        return False

    # Cross-OS confusion: backslash rejected.
    if "\\" in candidate:
        return False

    # URL-encoded smuggling defense (caller should pre-decode,
    # but defensively reject these patterns post-decode-failure).
    lower = candidate.lower()
    if "%2e" in lower or "%2f" in lower or "%5c" in lower:
        return False

    # Absolute path rejected (must be relative to base).
    if os.path.isabs(candidate):
        return False

    cleaned = candidate.strip()
    if not cleaned:
        return False

    # Normalize via posixpath for OS-independent behaviour.
    normalized = posixpath.normpath(cleaned)

    # Degenerate / current-dir.
    if normalized == ".":
        return False

    # `..` at top-level after normalization → escapes base.
    if normalized.startswith("..") and (len(normalized) == 2 or normalized[2] in ("/", ".")):
        return False

    # Build full path; verify it stays inside base.
    base_normalized = posixpath.normpath(base)
    full = posixpath.normpath(posixpath.join(base_normalized, normalized))

    base_with_slash = base_normalized.rstrip("/") + "/"
    if full == base_normalized:
        # Candidate normalized to "." — already rejected above.
        return False
    return full.startswith(base_with_slash)


def safe_join(
    base: str | None,
    candidate: str | None,
) -> str | None:
    """Join `base` + `candidate` safely. Returns the joined
    normalized path, or None if the candidate is unsafe.
    """
    if not is_safe_subpath(base, candidate):
        return None
    if base is None or candidate is None:  # already verified by is_safe_subpath
        raise RuntimeError("safe_join: base or candidate is None after safety check")
    base_normalized = posixpath.normpath(base)
    return posixpath.normpath(posixpath.join(base_normalized, candidate.strip()))
