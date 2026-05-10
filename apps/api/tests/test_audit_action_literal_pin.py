"""Pin the exact set of `services.audit.AuditAction` literal values.

Why this exists: the `AuditAction` Literal has been silently mutated
across recent batches — values renamed, mangled (e.g.
`"XXnotifications.preference.updateXX"`), or dropped. The existing
`test_audit_action_webhooks_in_sync.py` only checks that
`AuditAction ⊆ _KNOWN_EVENT_TYPES` — a *shrinking* AuditAction
still passes that subset check even though it represents a
real-world regression (an audit verb the codebase used to record
silently disappears, breaking compliance trails).

This test pins the absolute set, so:

  * **Adding** a verb requires updating this file's `EXPECTED` set
    in the same PR — the explicit signal that a new compliance
    surface is being introduced.
  * **Removing** a verb fails loudly. Compliance verbs aren't
    removed silently — they're either renamed (which also fails
    here) or replaced (which adds the new one to EXPECTED).
  * **Renaming** a verb fails twice (once for the old name being
    missing, once for the new name being unexpected).

If you intentionally change the AuditAction set, update `EXPECTED`
below in the same PR. That's the explicit auditability gate.
"""

from __future__ import annotations

from typing import get_args

from services.audit import AuditAction

# Source of truth, pinned 2026-05-10. Each entry's grouping comment
# mirrors the ordering in `services.audit.AuditAction` so a reviewer
# can scan the two files side-by-side. Keep the comments in lockstep
# with the literal — they're load-bearing for human review.
EXPECTED: frozenset[str] = frozenset(
    {
        # CostPulse
        "costpulse.estimate.approve",
        "costpulse.boq.import",
        "costpulse.suppliers.import",
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
        # Notifications
        "notifications.preference.update",
        # Handover
        "handover.package.deliver",
        # Punch list
        "punchlist.list.sign_off",
        # Submittals
        "submittals.review.approve",
        "submittals.review.approve_as_noted",
        "submittals.review.revise_resubmit",
        "submittals.review.reject",
        # Cross-tenant platform admin
        "admin.normalizer_rule.create",
        "admin.normalizer_rule.update",
        "admin.normalizer_rule.delete",
        # Webhook secret rotation
        "webhooks.subscription.rotate_secret",
        # Operator-triggered manual cron run
        "admin.cron.run_now",
    }
)


def test_audit_action_literal_matches_expected_set_exactly():
    """Hard equality. Asymmetric set diffs make the failure message
    actionable: if a verb went missing the diff names it; if a new
    one slipped in unannounced the diff names it. Either way the
    message tells the reviewer exactly what to investigate.
    """
    actual = frozenset(get_args(AuditAction))
    missing = EXPECTED - actual
    unexpected = actual - EXPECTED
    assert not missing, (
        f"AuditAction lost entries vs the pinned set: {sorted(missing)}. "
        "If this is intentional, remove from EXPECTED in the same PR."
    )
    assert not unexpected, (
        f"AuditAction gained entries the pin doesn't know about: {sorted(unexpected)}. "
        "If this is intentional, add to EXPECTED in the same PR — that's the "
        "explicit auditability signal that a new compliance verb landed."
    )


def test_audit_action_literal_count_matches_expected():
    """Belt-and-suspenders: catches the pathological case where two
    EXPECTED entries collide because a typo introduced a duplicate
    on either side. An exact count check surfaces that even when
    the set-diff is empty.
    """
    actual = get_args(AuditAction)
    # `tuple` of the literal's args — duplicates would survive here
    # but get deduped by `set()`.
    assert len(actual) == len(set(actual)), (
        f"AuditAction has duplicate entries: {sorted(a for a in actual if list(actual).count(a) > 1)}"
    )
    assert len(actual) == len(EXPECTED), (
        f"AuditAction has {len(actual)} unique entries; EXPECTED has "
        f"{len(EXPECTED)}. The diff test above will name which side is off."
    )


def test_audit_action_values_are_dotted_module_verbs():
    """Every audit action follows the `<module>.<resource>.<verb>` or
    `<module>.<verb>` shape. The dashboard's filter dropdown groups
    by the first dotted segment (see `audit/page.tsx::ACTION_FILTERS`);
    a value without dots would land in an "Other" bucket nobody
    expects to use.

    Raw values like `"approve_estimate"` (no dots) would silently
    pass the set-diff above but break the UI grouping. This test
    catches that class of typo at the test layer rather than via
    a manual UI check.
    """
    for value in get_args(AuditAction):
        assert isinstance(value, str), f"non-string in AuditAction: {value!r}"
        assert "." in value, (
            f"AuditAction value {value!r} is missing the dotted-module prefix. "
            "Convention is `<module>.<resource>.<verb>` so the audit dashboard "
            "can group by module."
        )
        # Reject the `XX...XX` mangling that's appeared in past
        # upstream-revert events. A string starting with XX strongly
        # implies a sabotaged value, not an intentional one.
        assert not value.startswith("XX"), (
            f"AuditAction value {value!r} looks mangled (`XX...` prefix). "
            "If this is intentional, document the rationale and remove the XX."
        )
