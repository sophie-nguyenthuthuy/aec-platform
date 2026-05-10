"""Webhook secret rotation grace window (cycle KK2).

When rotating a webhook subscription's signing secret, the old
secret remains valid for a grace window so in-flight deliveries
don't break. Today the webhook delivery verifier checks current
+ previous inline; the audit row's "signature mismatch" detector
duplicates the grace logic; a future replay-protection rotation
will need a third copy. This module is the single source of truth.

  is_signature_valid_during_rotation(...)  — (valid, matched_label) tuple
  DEFAULT_GRACE_SECONDS                    — 86400 (24 hours)
  MAX_GRACE_SECONDS                        — 604800 (7 days)

Decoupled from Y2's specific signature scheme via a `matches`
callback — the helper's job is to decide WHICH secret to try,
not HOW to compute the signature. Composes with any verifier
(HMAC-SHA256 from Y2, or future schemes).

Pinned invariants:
  * Outside grace window, ONLY `current_secret` validates —
    `previous_secret` explicitly REJECTED (NOT silently allowed).
  * Inside grace window, BOTH secrets accepted; matched label
    tells the caller which one was used.
  * `previous_secret=None` or `rotated_at=None` → no rotation
    in progress, only current path.
  * Strict `>=` boundary: `now >= grace_end` is OUT of grace.
  * Grace clamped to `[0, MAX_GRACE_SECONDS]`.
  * `matches` called at most twice (cost / observability pin).

Pure stdlib + caller-supplied verify callback.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

# Default grace window. 24 hours is the operationally common
# choice — long enough that in-flight retries finish; short
# enough that the previous secret isn't a long-tail liability.
DEFAULT_GRACE_SECONDS = 86400


# Legal ceiling. 7 days matches the standard "we honoured your
# old secret for a week" disclosure language. Pin so a refactor
# that bumps to e.g. 30 days surfaces in review — the longer
# the grace, the longer a leaked previous secret stays valid.
MAX_GRACE_SECONDS = 604800


def is_signature_valid_during_rotation(
    matches: Callable[[str], bool],
    current_secret: str,
    previous_secret: str | None,
    rotated_at: datetime | None,
    now: datetime,
    grace_seconds: int = DEFAULT_GRACE_SECONDS,
) -> tuple[bool, str | None]:
    """Validate a webhook signature against current + (optional) previous secret.

    `matches(secret)` is a caller-supplied callable that returns
    True iff the signature verifies with the given secret. This
    decouples the helper from the specific signing scheme — the
    caller composes Y2's `verify_with_trace` (or any other
    verifier) into the callback.

    Returns `(valid, matched_label)`:
      * `(True, "current")`  — current_secret matched.
      * `(True, "previous")` — previous_secret matched and now
        is within the grace window.
      * `(False, None)`      — neither matched, or previous
        out of grace.

    Why return the matched label: the audit trail emits a
    different event when the previous secret matched (operator
    visibility into "we honoured the rotated-out key — caller
    hasn't redeployed yet").
    """
    # Try current secret first — happy path.
    if matches(current_secret):
        return (True, "current")

    # No rotation in progress — current path only.
    if previous_secret is None or rotated_at is None:
        return (False, None)

    # Clamp grace into legal band.
    effective_grace = grace_seconds
    if effective_grace < 0:
        effective_grace = 0
    if effective_grace > MAX_GRACE_SECONDS:
        effective_grace = MAX_GRACE_SECONDS

    grace_end = rotated_at + timedelta(seconds=effective_grace)
    # Strict `>=` boundary: a request at exactly grace_end is OUT.
    if now >= grace_end:
        return (False, None)

    if matches(previous_secret):
        return (True, "previous")

    return (False, None)
