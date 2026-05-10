"""Webhook subscription event_type pattern validator (cycle WW3).

Validate event_type strings supplied to webhook subscription
endpoints. Today the subscription create endpoint validates
inline; the W1 wildcard match-preview helper assumes valid
input (no validation). This module is the single source of
truth for "is this event_type pattern valid for subscription?".

  is_valid_event_type(pattern)        — bool
  validate_event_types(patterns)      — (valid, rejected) tuple

Composes with Z2's `audit_action_meta.AUDIT_MODULES` (the closed
catalog of audit module prefixes).

Valid pattern shapes:
  * `*`              — universal wildcard (subscribe to all events)
  * `module.*`       — module wildcard (e.g. `pulse.*`); module
                       must be in Z2's AUDIT_MODULES
  * `module.literal` — literal pattern (e.g.
                       `pulse.change_order.approve`); module
                       prefix must be in AUDIT_MODULES

Pinned invariants:
  * Bare `*` always valid.
  * `module.*` valid iff module ∈ AUDIT_MODULES.
  * Literal patterns must have a known module prefix.
  * Whitespace-only / None / empty REJECTED.
  * Case-sensitive (audit actions are lowercase by convention).
  * Composes with Z2 explicitly via test.

Pure stdlib + Z2.
"""

from __future__ import annotations

from services.audit_action_meta import AUDIT_MODULES

# Non-audit modules that are still valid webhook subscription targets.
# "webhook" (singular) is the test-fire event module (`webhook.test`).
_WEBHOOK_NON_AUDIT_MODULES: frozenset[str] = frozenset({"webhook"})

# Combined valid module prefixes for webhook subscription patterns.
_VALID_SUBSCRIPTION_MODULES: frozenset[str] = AUDIT_MODULES | _WEBHOOK_NON_AUDIT_MODULES


def is_valid_event_type(pattern: str | None) -> bool:
    """True iff `pattern` is a valid webhook event_type.

    Pattern shapes:
      * `*`          → True
      * `module.*`   → True iff module ∈ _VALID_SUBSCRIPTION_MODULES
      * `module.X.Y` → True iff module ∈ _VALID_SUBSCRIPTION_MODULES
      * Anything else → False
    """
    if not pattern:
        return False
    s = pattern.strip()
    if not s:
        return False

    # Bare wildcard.
    if s == "*":
        return True

    # Module wildcard (e.g. `pulse.*`, `admin.cron.*`).
    if s.endswith(".*"):
        # Strip the trailing `.*` and take just the first segment as the module.
        prefix = s[:-2]
        module = prefix.split(".", 1)[0]
        return module in _VALID_SUBSCRIPTION_MODULES

    # Literal: must have known module prefix.
    if "." not in s:
        return False
    module = s.split(".", 1)[0]
    return module in _VALID_SUBSCRIPTION_MODULES


def validate_event_types(
    patterns: list[str],
) -> tuple[list[str], list[str]]:
    """Validate a list of event_type patterns.

    Returns `(valid, rejected)`:
      * `valid` — patterns that pass `is_valid_event_type`,
        whitespace-stripped.
      * `rejected` — patterns (verbatim) that failed validation,
        in input order.
    """
    valid: list[str] = []
    rejected: list[str] = []
    for p in patterns:
        if is_valid_event_type(p):
            valid.append(p.strip())
        else:
            rejected.append(p)
    return (valid, rejected)
