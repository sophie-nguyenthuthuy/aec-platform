"""Webhook delivery dedup key generator (cycle QQ1).

Generate a deterministic dedup key for webhook deliveries to
detect duplicate emits within a sliding window. Today the
webhook delivery worker dedups inline; the audit row's
duplicate-emit detector duplicates the logic. This module is
the single source of truth.

  dedup_key(subscription_id, event_type, resource_id, payload_hash)
                                          — 64-char SHA-256 hex

Composes with PP1 (`format_hash_prefix`) for log-line display.

Pinned invariants:
  * Deterministic — same input always yields same key. NO
    timestamps in the input (a retry after backoff is the same
    logical event).
  * `subscription_id` REQUIRED. Empty raises ValueError.
    Defends against cross-tenant dedup (a security risk —
    deliveries from different subscriptions must never collide).
  * `payload_hash` truncated to first 16 chars (caller passes
    full SHA-256, but only ~64 bits of entropy needed for AEC-
    scale dedup).
  * Output is always 64-char lowercase hex (full SHA-256).
  * Stable serialization: `subscription_id|event_type|resource_id|payload_truncated`
    pipe-separated (pin so a refactor that changes separator
    invalidates existing dedup state).

Pure stdlib.
"""

from __future__ import annotations

import hashlib

# Number of payload-hash characters fed into dedup. 16 hex chars
# = 64 bits ≈ 1.8e19 distinct values, collision-resistant at AEC
# scale. Pin so a refactor that bumps to 32 (or drops to 8)
# surfaces — would change every existing dedup key in the DB.
PAYLOAD_HASH_TRUNCATE_CHARS = 16


def dedup_key(
    subscription_id: str,
    event_type: str,
    resource_id: str,
    payload_hash: str,
) -> str:
    """Generate a deterministic SHA-256 hex dedup key.

    Composes the four inputs in canonical pipe-separated order
    and hashes via SHA-256. The result is a stable 64-char
    lowercase hex string suitable for a unique-index column.

    Raises:
      * ValueError if `subscription_id` is empty (cross-tenant
        guard).
    """
    if not subscription_id:
        raise ValueError("subscription_id is required (cross-tenant dedup guard)")

    truncated = (payload_hash or "")[:PAYLOAD_HASH_TRUNCATE_CHARS]
    composite = f"{subscription_id}|{event_type}|{resource_id}|{truncated}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()
