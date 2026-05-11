"""HTTP Idempotency-Key header validator (cycle HH3).

Validate the `Idempotency-Key` header on POST endpoints. Today
the RFQ create, change order create, and webhook delivery
enqueue endpoints each validate the header inline with subtly
different rules (one accepts 8-char keys; another silently
strips internal whitespace). This module is the single source
of truth.

  parse_idempotency_key(input)    — lowercased canonical or None
  is_valid_idempotency_key(input) — bool
  MIN_IDEMPOTENCY_KEY_LENGTH      — 16 (anti-guess floor)
  MAX_IDEMPOTENCY_KEY_LENGTH      — 128 (DoS guard)

Allowed character class: `[a-zA-Z0-9_-]` (URL-safe). Rejects:
  * Whitespace (internal or trailing).
  * Special characters (slashes, dots, plus signs).
  * Under MIN length (too easy to guess in a malicious replay).
  * Over MAX length (defends against an attacker filling the
    dedup table with giant keys).

Lowercased on storage so a UUID v4 in either case (`550E84...`
vs `550e84...`) deduplicates against the same key. Pin so a
refactor that preserves case introduces a duplicate-key risk.

Pure stdlib.
"""

from __future__ import annotations

import re

# Anti-guess floor. UUID v4 is 36 chars; this is the minimum
# practical length for any reasonable client. A 16-char key has
# ~95 bits of entropy if drawn from [a-zA-Z0-9], well above the
# ~64 bits at which exhaustive search becomes feasible.
MIN_IDEMPOTENCY_KEY_LENGTH = 16


# DoS guard. A 128-char limit is generous (UUID v4 + namespace
# prefix fits comfortably) while bounding the per-row storage
# cost in the dedup table. An attacker submitting 1MB-keyed
# requests would otherwise consume disk linearly.
MAX_IDEMPOTENCY_KEY_LENGTH = 128


# URL-safe character class: alphanumeric, underscore, hyphen.
# Pin so a refactor that allows e.g. dots (`550e8400.uuid`) or
# slashes (`/api/req/123`) doesn't break URL-safe assumptions
# downstream.
_KEY_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def parse_idempotency_key(input_str: str | None) -> str | None:
    """Validate and lowercase-canonicalize an Idempotency-Key.

    Returns canonical lowercased form or None.

    Boundary whitespace is stripped before validation; internal
    whitespace causes rejection (a key with internal whitespace
    is a client bug worth surfacing).
    """
    if input_str is None:
        return None
    s = input_str.strip()
    if not s:
        return None
    if len(s) < MIN_IDEMPOTENCY_KEY_LENGTH:
        return None
    if len(s) > MAX_IDEMPOTENCY_KEY_LENGTH:
        return None
    if not _KEY_RE.match(s):
        return None
    return s.lower()


def is_valid_idempotency_key(input_str: str | None) -> bool:
    """True iff `parse_idempotency_key(input)` returns non-None."""
    return parse_idempotency_key(input_str) is not None
