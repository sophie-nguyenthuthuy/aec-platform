"""Notification preference matcher (cycle CC2).

Given a user's notification preferences and an incoming event,
return whether to deliver and via which channels. Today the
notification dispatcher (in-app + email), the Slack alert routing,
and the email digest scheduler each duplicate this match logic
inline with subtly different mute / wildcard semantics. This
module is the single source of truth.

  CHANNELS                 — closed channel set
  REASON_*                 — match-result reason codes
  NotificationPreference   — frozen dataclass: (channels, muted_until, event_types)
  MatchResult              — frozen dataclass: (should_deliver, channels, reason)
  match_event(prefs, ev, now)  — main entry point

Wildcard semantics (mirrors `services.webhook_match_preview`):
  * `"*"` — universal wildcard, matches every event type.
  * `"module.*"` — matches everything starting with `module.`,
    at any depth.
  * Literal — exact match.
  * Empty event_types — matches NOTHING (explicit subscribe model:
    a user with no patterns has not opted in to any event).

Mute semantics:
  * `muted_until is None` — not muted.
  * `muted_until > now` — muted (suppress delivery).
  * `muted_until <= now` — mute expired, deliver as normal.

Both `muted_until` and `now` must have the same tz-awareness
(both naive UTC or both aware). The caller is responsible —
mismatched datetimes raise TypeError, which is the right
posture (the dispatcher should crash visibly on a bug, not
silently mis-deliver).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Closed channel set. Adding a new channel (e.g. "sms") requires
# touching the dispatcher, the user preferences page, and the
# CSV export — pin so a sneaky add doesn't slip past three-way
# review.
CHANNELS: frozenset[str] = frozenset({"email", "slack", "webhook", "in_app"})


# Reason codes — the caller logs these for delivery audit. Pin
# the closed set so a refactor that introduces a new reason
# without updating the dispatcher's logging doesn't silently slip.
REASON_EMPTY_SUBSCRIPTION = "empty_subscription"
REASON_NO_VALID_CHANNELS = "no_valid_channels"
REASON_MUTED = "muted"
REASON_NO_PATTERN_MATCH = "no_pattern_match"
REASON_MATCHED = "matched"

REASON_CODES: frozenset[str] = frozenset(
    {
        REASON_EMPTY_SUBSCRIPTION,
        REASON_NO_VALID_CHANNELS,
        REASON_MUTED,
        REASON_NO_PATTERN_MATCH,
        REASON_MATCHED,
    }
)


@dataclass(frozen=True)
class NotificationPreference:
    """A user's notification preference snapshot.

    All fields are required — there is no concept of "defaults"
    at this layer. Defaults are applied upstream (the API that
    loads the row from DB) so the matcher sees a fully resolved
    snapshot.
    """

    channels: frozenset[str]
    muted_until: datetime | None
    event_types: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    """Result of a single match. `channels` is empty unless
    `should_deliver` is True. `reason` is one of REASON_CODES."""

    should_deliver: bool
    channels: frozenset[str]
    reason: str


def _wildcard_match(patterns: tuple[str, ...], event_type: str) -> bool:
    """True iff any pattern in `patterns` matches `event_type`.

    Mirrors `services.webhook_match_preview` semantics:
      * `"*"` matches everything.
      * Literal pattern matches the exact event_type.
      * `"module.*"` matches any event_type starting with `module.`
        (multi-level wildcard — `pulse.*` matches
        `pulse.change_order.approve`).
    """
    if "*" in patterns:
        return True
    if event_type in patterns:
        return True
    for p in patterns:
        if p.endswith(".*"):
            prefix = p[:-2]
            if event_type == prefix or event_type.startswith(prefix + "."):
                return True
    return False


def match_event(
    prefs: NotificationPreference,
    event_type: str,
    now: datetime,
) -> MatchResult:
    """Decide whether to deliver `event_type` to the user with
    the given preferences, at the given wall-clock time.

    Order of checks (pinned by tests — a refactor that reorders
    would break the audit trail's reason classification):
      1. Empty event_types → REASON_EMPTY_SUBSCRIPTION.
      2. No valid channels (after intersect with CHANNELS) →
         REASON_NO_VALID_CHANNELS.
      3. Muted → REASON_MUTED.
      4. No pattern match → REASON_NO_PATTERN_MATCH.
      5. Matched → REASON_MATCHED with valid channels.
    """
    if not prefs.event_types:
        return MatchResult(False, frozenset(), REASON_EMPTY_SUBSCRIPTION)
    valid_channels = prefs.channels & CHANNELS
    if not valid_channels:
        return MatchResult(False, frozenset(), REASON_NO_VALID_CHANNELS)
    if prefs.muted_until is not None and prefs.muted_until > now:
        return MatchResult(False, frozenset(), REASON_MUTED)
    if not _wildcard_match(prefs.event_types, event_type):
        return MatchResult(False, frozenset(), REASON_NO_PATTERN_MATCH)
    return MatchResult(True, valid_channels, REASON_MATCHED)
