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

from models.audit import AuditEvent

logger = logging.getLogger(__name__)


# Closed set of audit-action names. Adding a new one is one edit here +
# one call site. Listed in dotted form (`module.verb`) so a UI can
# group/filter by module.
AuditAction = Literal[
    # CostPulse
    "costpulse.estimate.approve",
    # ProjectPulse
    "pulse.change_order.approve",
    "pulse.change_order.reject",
    # Org / RBAC
    "org.member.role_change",
    "org.member.remove",
    "org.invitation.create",
    "org.invitation.revoke",
    "org.invitation.accept",
    # Handover
    "handover.package.deliver",
]


async def record(
    session: AsyncSession,
    *,
    organization_id: UUID,
    actor_user_id: UUID | None,
    action: AuditAction,
    resource_type: str,
    resource_id: UUID | None,
    before: dict | None = None,
    after: dict | None = None,
    request: Request | None = None,
) -> AuditEvent:
    """Append one audit row.

    `request` is optional but recommended — it gives us caller IP +
    User-Agent without the call site needing to pluck them off itself.
    Inside test contexts where there's no real request, callers just
    omit it and the network-metadata columns stay NULL.

    The row is `add()`-ed but NOT committed: callers commit as part of
    their own transaction so a failed handler rolls back the audit
    too.
    """
    event = AuditEvent(
        id=uuid4(),
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before=before or {},
        after=after or {},
        ip=_client_ip(request) if request else None,
        user_agent=_user_agent(request) if request else None,
    )
    session.add(event)
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
