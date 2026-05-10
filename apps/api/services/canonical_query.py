"""HTTP query string canonical builder (cycle PP3).

Build a deterministic canonical query string from a dict of
params. Today Y2's webhook signature payload, the audit row's
`resource_url` builder, and the redirect-target URL helper each
build query strings inline with subtly different ordering and
None-handling. This module is the single source of truth.

  build_canonical_query(params)  — "key=val&key2=val2" or ""

Foundational for Y2 webhook signature determinism — the same
params dict must produce the same canonical string across
requests for the HMAC to verify.

Pinned invariants:
  * Keys sorted alphabetically (deterministic — pin against
    Python dict-iteration variance pre-3.7 / TS Map ordering).
  * Empty dict → "".
  * None values OMITTED (NOT serialized as `key=None`).
  * Empty-string values INCLUDED as `key=` (DISTINCT from None
    — pin pattern from MM3).
  * List values become repeated keys preserving original list
    order (`tags=a&tags=b`).
  * RFC 3986 percent-encoding (space → `%20`, NOT `+`).
  * Bool values render as `true` / `false` (lowercased — pin
    against Python's `True`/`False`).

Pure stdlib.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


def _render(value: Any) -> str:
    """Render a scalar value to its query-string form."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _encode(value: str) -> str:
    """RFC 3986 percent-encoding. Space → %20 (NOT +)."""
    return quote(value, safe="")


def build_canonical_query(params: dict[str, Any]) -> str:
    """Build a canonical query string from a dict of params.

    Algorithm:
      1. Sort keys alphabetically.
      2. For each key:
         - If value is None, SKIP entirely.
         - If value is a list, emit `key=v` for each non-None
           element in original order.
         - Otherwise, emit `key=value` with both percent-encoded.
      3. Join with `&`.

    Returns "" for an empty dict.
    """
    if not params:
        return ""

    parts: list[str] = []
    for key in sorted(params.keys()):
        value = params[key]
        if value is None:
            continue
        encoded_key = _encode(str(key))
        if isinstance(value, list):
            for item in value:
                if item is None:
                    continue
                parts.append(f"{encoded_key}={_encode(_render(item))}")
        else:
            parts.append(f"{encoded_key}={_encode(_render(value))}")

    return "&".join(parts)
