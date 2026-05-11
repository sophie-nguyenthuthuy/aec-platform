"""Pagination cursor encoder/decoder (cycle VV3).

Foundational helper for cursor-based pagination across audit
list, deliveries list, dead-letter list, member list. Cursors
are URL-safe base64 strings encoding `(last_id, last_sort_value)`
tuples — opaque to clients (don't promise stability across deploys).

  Cursor                   — frozen dataclass: (last_id, last_sort_value)
  encode_cursor(cursor)    — URL-safe base64 string or ""
  decode_cursor(s)         — Cursor or None

Pinned invariants:
  * Cursors are OPAQUE — internal JSON shape is NOT promised.
  * Base64url variant (`-_` not `+/`); no `=` padding (URL friendly).
  * Deterministic encoding (`json.dumps(sort_keys=True)`) — same
    input always yields same cursor.
  * Round-trip stable: `decode_cursor(encode_cursor(c)) == c`.
  * Malformed / corrupt input → None.
  * `last_id` must be str or int; `last_sort_value` must be a
    JSON-serializable scalar (str / int / float / bool / None).
  * None Cursor → "" cursor; empty/None cursor string → None Cursor.

Pure stdlib.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Cursor:
    """Pagination cursor. `last_id` is the unique row identifier
    of the last row in the previous page; `last_sort_value` is
    the corresponding value of the sort column (used to break
    ties when sort values are non-unique)."""

    last_id: str | int
    last_sort_value: Any  # scalar: str/int/float/bool/None


def encode_cursor(cursor: Cursor | None) -> str:
    """Encode a Cursor as a URL-safe base64 string.

    Returns "" for None cursor or for cursors with non-JSON-
    serializable values.
    """
    if cursor is None:
        return ""
    try:
        payload = json.dumps(
            {"id": cursor.last_id, "v": cursor.last_sort_value},
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return ""
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8"))
    # Strip padding for URL-friendliness (RFC 4648 §5).
    return encoded.rstrip(b"=").decode("ascii")


def decode_cursor(s: str | None) -> Cursor | None:
    """Decode a URL-safe base64 cursor string back to Cursor.

    Returns None for empty / malformed / corrupt input.
    """
    if not s:
        return None
    # Re-add padding before base64 decode (RFC 4648 §5).
    pad_len = (-len(s)) % 4
    padded = s + ("=" * pad_len)
    try:
        decoded_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, binascii.Error):
        return None
    try:
        decoded_str = decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        payload = json.loads(decoded_str)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if "id" not in payload or "v" not in payload:
        return None
    last_id = payload["id"]
    last_sort_value = payload["v"]
    if not isinstance(last_id, (str, int)) or isinstance(last_id, bool):
        # bool is a subclass of int — exclude.
        return None
    if not isinstance(last_sort_value, (str, int, float, bool, type(None))):
        return None
    return Cursor(last_id=last_id, last_sort_value=last_sort_value)
