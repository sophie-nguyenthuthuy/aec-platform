"""Audit row fingerprint generator (cycle RR3).

Compute a stable fingerprint hash for an audit row to detect
duplicate emits in the audit list view (collapses identical
retries that emitted the same logical event twice).

  fingerprint(org_id, actor_id, action, resource_id, payload_diff_hash)
                                  — 64-char SHA-256 hex

Composes with:
  * X1 (`audit_diff.summarize_diff`) — caller hashes the diff
    text and passes the hash to this function.
  * QQ1 (`webhook_dedup_key`) — reuses the same
    `PAYLOAD_HASH_TRUNCATE_CHARS` constant for cross-cycle
    consistency in dedup-class entropy assumptions.

Pinned invariants:
  * Same five-tuple input → same fingerprint.
  * `org_id` REQUIRED (cross-tenant guard, same pattern as QQ1
    `subscription_id`).
  * Pipe-separated stable order: `org|actor|action|resource|diff`.
  * Output 64-char lowercase hex.
  * `payload_diff_hash` truncated to first 16 chars (matches
    QQ1's `PAYLOAD_HASH_TRUNCATE_CHARS`).

Pure stdlib + QQ1 (constant import).
"""

from __future__ import annotations

import hashlib

from services.webhook_dedup_key import PAYLOAD_HASH_TRUNCATE_CHARS


def fingerprint(
    org_id: str,
    actor_id: str,
    action: str,
    resource_id: str,
    payload_diff_hash: str,
) -> str:
    """Compute a deterministic 64-char SHA-256 hex fingerprint.

    Composes the five inputs in canonical pipe-separated order
    and hashes via SHA-256.

    Raises:
      * ValueError if `org_id` is empty (cross-tenant guard —
        defends against fingerprints colliding across orgs).
    """
    if not org_id:
        raise ValueError("org_id is required (cross-tenant fingerprint guard)")

    truncated = (payload_diff_hash or "")[:PAYLOAD_HASH_TRUNCATE_CHARS]
    composite = f"{org_id}|{actor_id}|{action}|{resource_id}|{truncated}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()
