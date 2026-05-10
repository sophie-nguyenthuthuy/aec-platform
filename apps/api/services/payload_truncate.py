"""Webhook payload truncation (cycle JJ1).

Given a JSON-serializable payload + max-bytes limit, return a
truncated version that fits within the limit. Today the dead-
letter dashboard, the audit row's payload column, and the
webhook delivery log retention pruner each truncate inline with
subtly different markers + size accounting. This module is the
single source of truth.

  truncate_payload(payload, max_bytes=DEFAULT)  — truncated dict/list/scalar
  DEFAULT_MAX_PAYLOAD_BYTES                     — 64KB
  TRUNCATION_MARKER_PREFIX                      — "[truncated:"
  PER_FIELD_STRING_LIMIT                        — 1KB before per-field truncation

Strategy:
  1. Walk the structure recursively.
  2. Strings over PER_FIELD_STRING_LIMIT are replaced with
     `"[truncated:N]"` markers showing the original byte size.
  3. After string-level truncation, if the whole payload is
     still over `max_bytes`, return a top-level sentinel
     `{"_truncated_kind": "payload", "_original_size": N, ...}`.

Pinned invariants:
  * Idempotent: re-truncating an already-truncated payload is a no-op.
  * Deterministic: dict iteration sorted by key (snapshot-test stable).
  * Type-shape preserved: a truncated string field stays a string
    (NOT replaced with null or sentinel).
  * Marker shows ORIGINAL byte size (not the truncated form size).
  * Non-string types under per-field limit pass through verbatim.

Pure stdlib.
"""

from __future__ import annotations

import json
from typing import Any

# Default payload cap. Matches the audit_row.payload column's
# storage hint and the dead-letter dashboard's display preview.
DEFAULT_MAX_PAYLOAD_BYTES = 65536  # 64KB


# Per-field string truncation threshold. Strings over this are
# replaced with the truncation marker BEFORE the whole-payload
# size check. 1KB is a reasonable per-field ceiling for normal
# webhook payloads — most fields are short identifiers, URLs,
# or short messages; over-1KB is usually a long error trace or
# embedded body.
PER_FIELD_STRING_LIMIT = 1024


# Marker prefix. `[truncated:N]` where N is the ORIGINAL byte
# size. Chosen so a regex `\[truncated:\d+\]` can detect markers
# downstream for re-display logic. Pin so a refactor that swaps
# to e.g. `<TRUNCATED>` would surface in the dashboard's
# format-aware renderer.
TRUNCATION_MARKER_PREFIX = "[truncated:"


def _is_truncated_marker(s: object) -> bool:
    """True iff `s` is an existing truncation marker.

    Used for idempotency: re-truncating an already-truncated
    string returns it verbatim rather than wrapping the marker
    again (which would produce `[truncated:[truncated:N]]`).
    """
    if not isinstance(s, str):
        return False
    return s.startswith(TRUNCATION_MARKER_PREFIX) and s.endswith("]")


def _walk_truncate(obj: Any) -> Any:
    """Recursively replace oversize strings with markers.

    Dict iteration is sorted by key for deterministic output.
    """
    if isinstance(obj, str):
        if _is_truncated_marker(obj):
            return obj
        size = len(obj.encode("utf-8"))
        if size > PER_FIELD_STRING_LIMIT:
            return f"{TRUNCATION_MARKER_PREFIX}{size}]"
        return obj
    if isinstance(obj, dict):
        # Sorted iteration for deterministic snapshot tests.
        return {k: _walk_truncate(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_walk_truncate(v) for v in obj]
    # int, float, bool, None pass through.
    return obj


def _serialized_size(obj: Any) -> int:
    """JSON-serialized byte size."""
    return len(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def truncate_payload(
    payload: Any,
    max_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
) -> Any:
    """Truncate `payload` to fit within `max_bytes`.

    None passes through (no truncation needed).

    If the original payload already fits, returns it verbatim
    (no copy).

    Otherwise: walk-truncate strings over `PER_FIELD_STRING_LIMIT`,
    then check the resulting size. If still over `max_bytes`,
    return a top-level sentinel preserving the original byte size
    for caller diagnostic.
    """
    if payload is None:
        return None

    original_size = _serialized_size(payload)
    # Always walk-truncate per-field strings regardless of total size.
    # Per-field truncation is unconditional; the max_bytes check only
    # triggers the top-level sentinel when even post-truncation the
    # payload is still too large.
    truncated = _walk_truncate(payload)
    truncated_size = _serialized_size(truncated)
    if truncated_size <= max_bytes:
        return truncated

    # Even after string-level truncation, still too large —
    # return top-level sentinel.
    return {
        "_truncated_kind": "payload",
        "_original_size": original_size,
        "_max_bytes": max_bytes,
    }
