"""Pin the exact set of `services.webhooks._KNOWN_EVENT_TYPES`.

Why this exists: this set gates which event_type strings the webhook
dispatcher will fire on. A subscriber can register for any string,
but `enqueue_event(event_type, ...)` logs a warning + treats the
event as unknown when the type isn't in this set. So:

  * **Adding** a type without code that fires it → subscribers see
    a switch, never get pinged.
  * **Removing** a type while subscribers have it in their
    `event_types[]` → those subscriptions silently stop receiving
    matching events, even though their config implies otherwise.
  * **Renaming** a type → the matching subset of subscribers
    silently misses every future event.

The set is the source-of-truth bridge between three layers:

  * Audit-mirrored types (every value of `services.audit.AuditAction`).
  * Non-audit creation events (handover.defect.reported, etc.).
  * `webhook.test` for the test-fire endpoint.

A separate sync test (`test_audit_action_webhooks_in_sync.py`)
already asserts that `AuditAction ⊆ _KNOWN_EVENT_TYPES`. THIS test
pins the absolute set — including the non-audit additions — so a
revert that drops `siteeye.safety_incident.detected` (a non-audit
event with no AuditAction counterpart) is still caught.

If you intentionally change the set, update `EXPECTED` below in
the same PR.
"""

from __future__ import annotations

from services.webhooks import _KNOWN_EVENT_TYPES

# Source of truth, pinned 2026-05-04. Grouped to mirror the
# layout in `services.webhooks._KNOWN_EVENT_TYPES` for side-by-side
# review.
EXPECTED: frozenset[str] = frozenset(
    {
        # ---- Audit-mirrored — must stay in lockstep with
        # `services.audit.AuditAction`. The sync test asserts that
        # ⊆ relationship; this set lists them explicitly so a future
        # silent removal of either side is caught.
        "costpulse.estimate.approve",
        "costpulse.boq.import",
        "costpulse.suppliers.import",
        "costpulse.rfq.slots_expired",
        "pulse.change_order.approve",
        "pulse.change_order.reject",
        "org.member.role_change",
        "org.member.remove",
        "org.invitation.create",
        "org.invitation.revoke",
        "org.invitation.accept",
        "notifications.preference.update",
        "handover.package.deliver",
        "punchlist.list.sign_off",
        "submittals.review.approve",
        "submittals.review.approve_as_noted",
        "submittals.review.revise_resubmit",
        "submittals.review.reject",
        "admin.normalizer_rule.create",
        "admin.normalizer_rule.update",
        "admin.normalizer_rule.delete",
        "webhooks.subscription.rotate_secret",
        "admin.cron.run_now",
        # ---- Non-audit creations (not gated by RBAC; carry no actor
        # before/after diff, so they're awkward to log to audit but
        # high-value to webhook).
        "project.created",
        "siteeye.safety_incident.detected",
        "handover.defect.reported",
        # ---- Test-fire from `/webhooks/{id}/test`.
        "webhook.test",
    }
)


def test_known_event_types_matches_expected_set_exactly():
    """Hard equality. Asymmetric diff makes the failure message name
    exactly which entries are off — drop, addition, or rename.
    """
    missing = EXPECTED - _KNOWN_EVENT_TYPES
    unexpected = _KNOWN_EVENT_TYPES - EXPECTED
    assert not missing, (
        f"_KNOWN_EVENT_TYPES lost entries vs the pinned set: {sorted(missing)}. "
        "If this is intentional, remove from EXPECTED in the same PR. Subscribers "
        "with the dropped type in their event_types[] will silently stop firing."
    )
    assert not unexpected, (
        f"_KNOWN_EVENT_TYPES gained entries the pin doesn't know about: "
        f"{sorted(unexpected)}. If this is intentional, add to EXPECTED in the "
        "same PR + verify there's a code path that actually fires the new type "
        "(otherwise subscribers see a switch with no underlying delivery)."
    )


def test_known_event_types_count_matches_expected():
    """Belt-and-suspenders against duplicates / miscount."""
    assert len(_KNOWN_EVENT_TYPES) == len(EXPECTED), (
        f"_KNOWN_EVENT_TYPES has {len(_KNOWN_EVENT_TYPES)} entries; "
        f"EXPECTED has {len(EXPECTED)}. The diff test above will name which "
        "side is off."
    )


def test_known_event_types_values_are_dotted_module_verbs():
    """Same convention as `AuditAction`: `<module>.<resource>.<verb>`.
    The webhook subscription UI groups types by first dotted segment;
    a value without dots would land in an "Other" bucket.

    Also rejects the `XX...XX` mangling that's appeared on sibling
    closed sets during upstream-revert events.
    """
    for value in _KNOWN_EVENT_TYPES:
        assert isinstance(value, str), f"non-string in _KNOWN_EVENT_TYPES: {value!r}"
        assert "." in value, (
            f"_KNOWN_EVENT_TYPES value {value!r} is missing the dotted-module "
            "prefix. Convention is `<module>.<resource>.<verb>` so the dashboard "
            "can group by module."
        )
        assert not value.startswith("XX"), (
            f"_KNOWN_EVENT_TYPES value {value!r} looks mangled (`XX...` prefix). "
            "If this is intentional, document the rationale and remove the XX."
        )


def test_known_event_types_includes_audit_action_universe():
    """Cross-reference with `AuditAction`: every audit verb MUST also
    be a known webhook event type. This duplicates
    `test_audit_action_webhooks_in_sync.py` intentionally — the
    other test pins ⊆, this one pins the actual set; a regression
    that breaks ⊆ should fail BOTH tests, making the diagnosis
    redundant + hard to miss.
    """
    from typing import get_args

    from services.audit import AuditAction

    audit_actions = set(get_args(AuditAction))
    missing = audit_actions - _KNOWN_EVENT_TYPES
    assert not missing, (
        "AuditAction has values not in _KNOWN_EVENT_TYPES — webhook "
        "deliveries for these audit events would silently no-op: "
        f"{sorted(missing)}"
    )


def test_known_event_types_includes_webhook_test():
    """The `/webhooks/{id}/test` endpoint fires `webhook.test` — this
    must be in the known set or the dispatcher logs an "unknown
    event_type" warning on every test-fire. Pinned separately because
    it's the only entry without a paired AuditAction and easy to lose
    on a "let's clean up the imports" refactor.
    """
    assert "webhook.test" in _KNOWN_EVENT_TYPES
