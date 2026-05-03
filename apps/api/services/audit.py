"""Audit log writer.

Pairs with the RBAC layer in `middleware.rbac`. Every endpoint gated
by `require_min_role(...)` should emit one audit row when its write
succeeds. The contract is intentionally narrow:

  * `record(...)` takes the SAME session the handler used to do its
    write so the audit row is committed in the SAME transaction. If
    the handler rolls back, the audit row rolls back too — we never
    record a "phantom" approval for a write that didn't happen.

  * `before` / `after` are *minimal* JSON diffs. Don't dump the full
    row — that risks logging PII. Stick to the fields that semantically
    changed (e.g. `{"role": "member"}` for a role change, NOT the
    user's email/avatar/etc.).

  * Actions are typed via `AuditAction` so a typo at the call site
    surfaces as a typecheck failure instead of a silent string in the
    audit table.
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.auth import AuthContext
from models.audit import AuditEvent

logger = logging.getLogger(__name__)


# Closed set of audit-action names. Adding a new one is one edit here +
# one call site. Listed in dotted form (`module.verb`) so a UI can
# group/filter by module.
AuditAction = Literal[
    # CostPulse
    "costpulse.estimate.approve",
    # Bulk-load actions are auditable because they touch tens of rows
    # at once — a "who imported the wrong supplier list?" question
    # otherwise has no answer.
    "costpulse.boq.import",
    "costpulse.suppliers.import",
    # Cron-driven side effects with governance bearing — when a slot
    # auto-expires, the buyer's RFQ inbox loses a row; we want a
    # trail. Actor is null (system).
    "costpulse.rfq.slots_expired",
    # ProjectPulse
    "pulse.change_order.approve",
    "pulse.change_order.reject",
    # Org / RBAC
    "org.member.role_change",
    "org.member.remove",
    "org.invitation.create",
    "org.invitation.revoke",
    "org.invitation.accept",
    # Notifications — opt-out has compliance bearing (GDPR / VN
    # personal-data law), so we audit when a user toggles a channel.
    "notifications.preference.update",
    # Handover
    "handover.package.deliver",
    # Punch list
    #
    # `sign_off` is the terminal "owner has accepted the closeout" gate.
    # The list-level transition is the auditable event (item-level marks
    # are too noisy and aren't governance-bearing on their own).
    "punchlist.list.sign_off",
    # Submittals
    #
    # The four reviewer verdicts. Resubmittal is also tracked because it
    # carries a binding "this version is a no-go" decision even though
    # the submittal stays open.
    "submittals.review.approve",
    "submittals.review.approve_as_noted",
    "submittals.review.revise_resubmit",
    "submittals.review.reject",
    # Cross-tenant platform admin
    #
    # `normalizer_rules` is GLOBAL — a single edit affects every
    # tenant's price scrapes. That's a meaningful trust transfer that
    # absolutely needs an audit trail; an enterprise security review
    # would (rightly) flag silent global config mutations as a red
    # flag. The audit row is attributed to the actor's org so that
    # org's admins can see what their members did, even though the
    # resource itself doesn't belong to any one tenant.
    "admin.normalizer_rule.create",
    "admin.normalizer_rule.update",
    "admin.normalizer_rule.delete",
]


async def record(
    session: AsyncSession,
    *,
    organization_id: UUID,
    auth: AuthContext | None,
    action: AuditAction,
    resource_type: str,
    resource_id: UUID | None,
    before: dict | None = None,
    after: dict | None = None,
    request: Request | None = None,
) -> AuditEvent:
    """Append one audit row.

    `auth` is the caller's auth context, or None for system-driven
    events (cron jobs, queue workers). When `auth.role == "api_key"`,
    `auth.user_id` is actually the api_keys.id — we route it to the
    `actor_api_key_id` column so the FK to `users.id` doesn't trip,
    and the read endpoint can surface the key's name. Otherwise it's a
    real user UUID and goes to `actor_user_id`. Exactly one of the
    two is non-NULL on a row with a known actor.

    `request` is optional but recommended — it gives us caller IP +
    User-Agent without the call site needing to pluck them off itself.
    Inside test contexts where there's no real request, callers just
    omit it and the network-metadata columns stay NULL.

    The row is `add()`-ed but NOT committed: callers commit as part of
    their own transaction so a failed handler rolls back the audit
    too.
    """
    actor_user_id: UUID | None = None
    actor_api_key_id: UUID | None = None
    if auth is not None:
        if auth.role == "api_key":
            actor_api_key_id = auth.user_id
        else:
            actor_user_id = auth.user_id

    event = AuditEvent(
        id=uuid4(),
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_api_key_id=actor_api_key_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before=before or {},
        after=after or {},
        ip=_client_ip(request) if request else None,
        user_agent=_user_agent(request) if request else None,
    )
    session.add(event)

    # Mirror to the webhook outbox in the same transaction. If the
    # caller's surrounding write rolls back, both the audit row AND
    # the webhook delivery row roll back — the customer never gets
    # notified about a write that didn't actually commit. Lazy import
    # to avoid a circular at module load (webhooks → audit → webhooks).
    from services.webhooks import enqueue_event as _webhook_enqueue

    await _webhook_enqueue(
        session,
        organization_id=organization_id,
        event_type=action,
        payload={
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "actor_api_key_id": str(actor_api_key_id) if actor_api_key_id else None,
            "before": before or {},
            "after": after or {},
        },
    )
    return event


def _client_ip(request: Request) -> str | None:
    """Honor a single layer of `X-Forwarded-For` if present (the LB
    sets it). Falls back to the direct peer. Never returns the empty
    string — that'd index ugly in audit queries."""
    fwd = request.headers.get("x-forwarded-for", "").split(",")
    if fwd and fwd[0].strip():
        return fwd[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return None


def _user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:500] if ua else None  # cap at 500 — UAs can be obscene
