"""Notification preference matcher (cycle CC2).

Pinned seams:
  1. CHANNELS = {email, slack, webhook, in_app}.
  2. REASON_CODES has exactly 5 members.
  3. Empty event_types → empty_subscription (NOT match-everything).
  4. Channels filtered by intersection with CHANNELS.
  5. Mute window: muted_until > now → suppress.
  6. Mute expired (muted_until <= now) → deliver as normal.
  7. Wildcard "*" matches everything.
  8. "module.*" matches multi-level (e.g. "pulse.change_order.approve").
  9. Literal pattern wins over wildcard structure.
 10. Order of checks: empty → no_channels → muted → pattern → match.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.notification_match import (
    CHANNELS,
    REASON_CODES,
    REASON_EMPTY_SUBSCRIPTION,
    REASON_MATCHED,
    REASON_MUTED,
    REASON_NO_PATTERN_MATCH,
    REASON_NO_VALID_CHANNELS,
    MatchResult,
    NotificationPreference,
    match_event,
)

NOW = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)


def _prefs(
    channels: frozenset[str] = frozenset({"email", "slack"}),
    muted_until: datetime | None = None,
    event_types: tuple[str, ...] = ("pulse.change_order.approve",),
) -> NotificationPreference:
    return NotificationPreference(
        channels=channels,
        muted_until=muted_until,
        event_types=event_types,
    )


# ---------- Constants ----------


def test_channels_canonical_set():
    """4-channel closed set. Adding e.g. 'sms' requires touching
    the dispatcher + preferences page + CSV export — pin so the
    sneaky add doesn't slip past three-way review."""
    assert frozenset({"email", "slack", "webhook", "in_app"}) == CHANNELS


def test_channels_is_frozen():
    assert isinstance(CHANNELS, frozenset)


def test_reason_codes_has_exactly_five():
    """Five reasons — empty_subscription, no_valid_channels,
    muted, no_pattern_match, matched. Pin so a refactor that
    introduces a 6th without updating the dispatcher's logging
    surfaces here."""
    assert len(REASON_CODES) == 5
    assert (
        frozenset(
            {
                REASON_EMPTY_SUBSCRIPTION,
                REASON_NO_VALID_CHANNELS,
                REASON_MUTED,
                REASON_NO_PATTERN_MATCH,
                REASON_MATCHED,
            }
        )
        == REASON_CODES
    )


# ---------- Empty subscription ----------


def test_empty_event_types_is_empty_subscription():
    """Pin: empty event_types means "not subscribed to anything"
    — explicit subscribe model. NOT "match everything" (which
    would be the inverse default and would silently subscribe
    every user to every event on a refactor that drops their
    patterns)."""
    prefs = _prefs(event_types=())
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.should_deliver is False
    assert result.channels == frozenset()
    assert result.reason == REASON_EMPTY_SUBSCRIPTION


def test_empty_event_types_takes_precedence_over_mute():
    """Order of checks: empty_subscription is the strongest "no",
    reported even if the user is also muted. Pin so the audit
    trail reports the most-specific reason."""
    prefs = _prefs(
        event_types=(),
        muted_until=NOW + timedelta(hours=1),
    )
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.reason == REASON_EMPTY_SUBSCRIPTION


# ---------- No valid channels ----------


def test_no_valid_channels_when_all_channels_unknown():
    """Pin: a user whose only channel is "sms" (not in CHANNELS)
    gets no_valid_channels — surface the misconfiguration rather
    than silently delivering on an empty channel set."""
    prefs = _prefs(channels=frozenset({"sms", "telegram"}))
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.should_deliver is False
    assert result.reason == REASON_NO_VALID_CHANNELS


def test_no_valid_channels_with_empty_channels():
    prefs = _prefs(channels=frozenset())
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.reason == REASON_NO_VALID_CHANNELS


def test_unknown_channels_filtered_out_when_some_valid():
    """A user with {email, sms} delivers via {email} only — the
    unknown channel is silently dropped (it'd be a misconfig but
    we don't block the legitimate channels)."""
    prefs = _prefs(channels=frozenset({"email", "sms"}))
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.should_deliver is True
    assert result.channels == frozenset({"email"})


# ---------- Mute window ----------


def test_muted_when_muted_until_in_future():
    prefs = _prefs(muted_until=NOW + timedelta(hours=1))
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.should_deliver is False
    assert result.reason == REASON_MUTED


def test_not_muted_when_muted_until_in_past():
    """Mute expired — deliver normally."""
    prefs = _prefs(muted_until=NOW - timedelta(hours=1))
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.should_deliver is True
    assert result.reason == REASON_MATCHED


def test_not_muted_when_muted_until_equals_now():
    """Boundary: muted_until == now means mute just expired. Pin
    `>` not `>=` so a user un-muting at exactly noon delivers at
    noon, not at noon+epsilon."""
    prefs = _prefs(muted_until=NOW)
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.should_deliver is True


def test_not_muted_when_muted_until_is_none():
    prefs = _prefs(muted_until=None)
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.should_deliver is True


# ---------- Pattern matching ----------


def test_literal_pattern_matches():
    prefs = _prefs(event_types=("pulse.change_order.approve",))
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.should_deliver is True
    assert result.reason == REASON_MATCHED


def test_literal_pattern_does_not_match_different_event():
    prefs = _prefs(event_types=("pulse.change_order.approve",))
    result = match_event(prefs, "pulse.change_order.reject", NOW)
    assert result.should_deliver is False
    assert result.reason == REASON_NO_PATTERN_MATCH


def test_module_wildcard_matches_multi_level():
    """`pulse.*` matches `pulse.change_order.approve` (multi-level
    wildcard). Pin so a refactor to single-level matching breaks
    here — a user who subscribes to `pulse.*` expects ALL pulse
    events."""
    prefs = _prefs(event_types=("pulse.*",))
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.should_deliver is True


def test_module_wildcard_matches_single_level():
    prefs = _prefs(event_types=("webhook.*",))
    result = match_event(prefs, "webhook.test", NOW)
    assert result.should_deliver is True


def test_module_wildcard_does_not_match_other_module():
    prefs = _prefs(event_types=("pulse.*",))
    result = match_event(prefs, "punchlist.list.create", NOW)
    assert result.should_deliver is False


def test_universal_wildcard_matches_every_event():
    """`*` matches everything — used for "subscribe to all" admin
    audit feeds. Pin so a refactor that requires a dot-separated
    pattern surfaces here."""
    prefs = _prefs(event_types=("*",))
    for event in [
        "pulse.change_order.approve",
        "punchlist.list.sign_off",
        "webhook.test",
        "admin.cron.run_now",
    ]:
        result = match_event(prefs, event, NOW)
        assert result.should_deliver is True, f"`*` should match {event}"


def test_multiple_patterns_any_match_delivers():
    prefs = _prefs(event_types=("punchlist.*", "pulse.change_order.approve"))
    # Matches first pattern.
    r1 = match_event(prefs, "punchlist.list.create", NOW)
    assert r1.should_deliver is True
    # Matches second pattern.
    r2 = match_event(prefs, "pulse.change_order.approve", NOW)
    assert r2.should_deliver is True
    # Matches neither.
    r3 = match_event(prefs, "webhook.test", NOW)
    assert r3.should_deliver is False


def test_module_wildcard_matches_bare_module():
    """`pulse.*` matches `pulse` itself (no dot suffix). Pin the
    bare-module match so a refactor that requires a dot suffix
    doesn't break events emitted at the module level."""
    prefs = _prefs(event_types=("pulse.*",))
    result = match_event(prefs, "pulse", NOW)
    assert result.should_deliver is True


# ---------- Returned channels ----------


def test_matched_returns_intersected_channels():
    """`channels` in the result is the user's channels intersected
    with CHANNELS — pin so unknown channels never appear in the
    delivery list."""
    prefs = _prefs(channels=frozenset({"email", "slack", "in_app", "sms"}))
    result = match_event(prefs, "pulse.change_order.approve", NOW)
    assert result.channels == frozenset({"email", "slack", "in_app"})


def test_non_matched_returns_empty_channels():
    """When `should_deliver` is False, `channels` is empty —
    regardless of what the user had configured. Pin so a refactor
    that returns the full channel set on a non-match doesn't
    confuse the dispatcher."""
    prefs = _prefs(event_types=("pulse.change_order.approve",))
    result = match_event(prefs, "punchlist.list.create", NOW)
    assert result.should_deliver is False
    assert result.channels == frozenset()


# ---------- MatchResult shape ----------


def test_match_result_is_frozen():
    """Pin so a refactor can't mutate the result in-place."""
    result = MatchResult(True, frozenset({"email"}), REASON_MATCHED)
    try:
        result.should_deliver = False  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("MatchResult should be frozen")


def test_notification_preference_is_frozen():
    prefs = _prefs()
    try:
        prefs.muted_until = NOW  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("NotificationPreference should be frozen")
