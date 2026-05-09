"""Static check: `services.audit.AuditAction` ⊆ `services.webhooks._KNOWN_EVENT_TYPES`.

Why this test exists: both sets carry a "keep in sync" comment but
nothing enforces it. When someone adds a new audit action, they
have to remember to mirror it in `_KNOWN_EVENT_TYPES`; if they
forget, the webhook delivery silently no-ops on the
"webhooks.enqueue_event: unknown type" warning. The audit row
still lands, but every webhook subscriber misses the event — a
silent compliance / integration failure.

This test is the same shape as `test_apifetch_routes_match.py`:
catch the cross-set drift at CI time so the next engineer can't
forget.
"""

from __future__ import annotations

from typing import get_args


def test_every_audit_action_is_a_known_webhook_event_type():
    """Every entry in the `AuditAction` Literal must appear in
    `_KNOWN_EVENT_TYPES`.

    The other direction (webhook events that are NOT audit actions)
    is intentionally allowed — `_KNOWN_EVENT_TYPES` also carries
    pure-webhook event types like `project.created` and
    `siteeye.safety_incident.detected` that aren't gated by RBAC and
    don't carry an actor diff.
    """
    from services.audit import AuditAction
    from services.webhooks import _KNOWN_EVENT_TYPES

    audit_actions = set(get_args(AuditAction))
    missing = audit_actions - _KNOWN_EVENT_TYPES
    assert not missing, (
        "These `AuditAction` Literal entries are NOT in "
        "`services.webhooks._KNOWN_EVENT_TYPES`. Add them, or webhook "
        f"deliveries will silently no-op for these event types: {sorted(missing)}"
    )


def test_audit_action_literal_is_non_empty():
    """Sanity: if the literal collapsed to no args (e.g. someone
    accidentally typed `Literal[]`), the subset check would pass
    vacuously. Keep it honest."""
    from services.audit import AuditAction

    assert len(get_args(AuditAction)) > 0
