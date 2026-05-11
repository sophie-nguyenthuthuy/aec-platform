"""Audit context builder (cycle ZZ3 — 30th-cycle capstone).

The canonical context that flows through every audit emit:
`(org_id, actor_id, request_id, resource_id)`. Composes:

  * XX3 (`tenant_id.belongs_to_org`) — cross-tenant guard.
  * QQ1 (`webhook_dedup_key.dedup_key`) — dedup primitive.
  * RR3 (`audit_fingerprint.fingerprint`) — fingerprint primitive.

The capstone for the 30-cycle helper family: a single frozen
dataclass that holds the cross-cycle state every audit emit
needs, and helper methods that compose the prior cycles
without the caller having to import three modules.

  AuditContext                              — frozen dataclass
  from_request(org_id, actor_id, req_id)    — factory
  with_resource(ctx, resource_id)           — derive new ctx
  dedup_key_for(ctx, event_type, hash)      — composes QQ1
  fingerprint_for(ctx, action, hash)        — composes RR3
  validate_resource_belongs(ctx, resource)  — composes XX3

Pinned invariants:
  * `org_id` REQUIRED at construction (cross-tenant guard —
    raises ValueError if empty).
  * `request_id` is correlation-only (NOT used in dedup/
    fingerprint inputs — those are content-keyed, NOT
    request-keyed; pin so a refactor that includes request_id
    in fingerprint surfaces here, since it would prevent dedup
    across request retries which is the whole point).
  * `with_resource` returns a NEW context (frozen — immutable
    update via field replacement).
  * Composes XX3 + QQ1 + RR3 directly via helper imports.

Pure stdlib + XX3 + QQ1 + RR3.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from services.audit_fingerprint import fingerprint as _fingerprint
from services.tenant_id import belongs_to_org as _belongs_to_org
from services.webhook_dedup_key import dedup_key as _dedup_key


@dataclass(frozen=True)
class AuditContext:
    """The cross-cycle context for an audit emit.

    Fields:
      * `org_id`      — tenant; required (cross-tenant guard).
      * `actor_id`    — who performed the action (email or user-id).
      * `request_id`  — correlation token; NOT used in dedup/fp.
      * `resource_id` — optional, set via `with_resource`.
    """

    org_id: str
    actor_id: str
    request_id: str
    resource_id: str = ""


def from_request(
    org_id: str,
    actor_id: str,
    request_id: str,
) -> AuditContext:
    """Construct an AuditContext from request fields.

    Raises ValueError if `org_id` is empty (cross-tenant guard
    at construction time — fail fast at request parse).
    """
    if not org_id:
        raise ValueError("org_id is required (cross-tenant guard)")
    return AuditContext(
        org_id=org_id,
        actor_id=actor_id,
        request_id=request_id,
        resource_id="",
    )


def with_resource(ctx: AuditContext, resource_id: str) -> AuditContext:
    """Return a new AuditContext with `resource_id` set.

    Original `ctx` unchanged (frozen — immutable update).
    """
    return replace(ctx, resource_id=resource_id)


def dedup_key_for(
    ctx: AuditContext,
    event_type: str,
    payload_hash: str,
) -> str:
    """Compute QQ1's dedup key using `org_id` as the dedup
    namespace.

    Audit dedup is per-org (the `subscription_id` parameter of
    QQ1 is generic — we pass org_id for audit-level dedup).
    """
    return _dedup_key(
        subscription_id=ctx.org_id,
        event_type=event_type,
        resource_id=ctx.resource_id,
        payload_hash=payload_hash,
    )


def fingerprint_for(
    ctx: AuditContext,
    action: str,
    payload_diff_hash: str,
) -> str:
    """Compute RR3's audit fingerprint."""
    return _fingerprint(
        org_id=ctx.org_id,
        actor_id=ctx.actor_id,
        action=action,
        resource_id=ctx.resource_id,
        payload_diff_hash=payload_diff_hash,
    )


def validate_resource_belongs(
    ctx: AuditContext,
    resource_id: str,
) -> bool:
    """True iff `resource_id` carries `ctx.org_id` tenant prefix.

    Composes XX3's `belongs_to_org` for cross-tenant defense.
    """
    return _belongs_to_org(resource_id, ctx.org_id)
