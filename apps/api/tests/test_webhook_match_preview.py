"""Webhook subscription match preview helper (cycle W3).

Pinned seams:
  1. Empty `event_types[]` → matched_via='all'.
  2. Literal match takes precedence over wildcard (subscription
     with both gets the literal as matched_pattern).
  3. Most-specific wildcard wins when multiple match
     (`costpulse.estimate.*` over `costpulse.*`).
  4. No match → matched=False, matched_via=None.
  5. `_is_wildcard_pattern` mirrors backend schema validator —
     bare `*`, embedded `*`, no terminal `.*` all reject.
"""

from __future__ import annotations

from services.webhook_match_preview import (
    MatchResult,
    _is_wildcard_pattern,
    match_subscription,
)

# ---------- _is_wildcard_pattern ----------


def test_wildcard_pattern_accepts_module_star():
    assert _is_wildcard_pattern("costpulse.*") is True


def test_wildcard_pattern_accepts_multi_segment():
    assert _is_wildcard_pattern("costpulse.estimate.*") is True


def test_wildcard_pattern_rejects_bare_asterisk():
    """`*` alone is too permissive (partner likely meant []
    catch-all). Reject so the matcher doesn't mistakenly call it
    a wildcard."""
    assert _is_wildcard_pattern("*") is False


def test_wildcard_pattern_rejects_no_terminal_dot_star():
    """`costpulse*` and `costpulse.estimate.approve` aren't
    wildcards — must end with literal `.*`."""
    assert _is_wildcard_pattern("costpulse*") is False
    assert _is_wildcard_pattern("costpulse.estimate.approve") is False


def test_wildcard_pattern_rejects_embedded_asterisk():
    """`costpulse.*.approve` is malformed — schema validator
    rejects, helper does too."""
    assert _is_wildcard_pattern("costpulse.*.approve") is False


# ---------- match_subscription ----------


def test_empty_event_types_is_match_all():
    """Catch-all subscription: empty list = "every event fires"."""
    out = match_subscription(event_types=[], event_type="anything.goes")
    assert out == MatchResult(matched=True, matched_via="all", matched_pattern=None)


def test_literal_match_returns_via_literal():
    out = match_subscription(
        event_types=["costpulse.estimate.approve", "pulse.change_order.approve"],
        event_type="costpulse.estimate.approve",
    )
    assert out.matched is True
    assert out.matched_via == "literal"
    assert out.matched_pattern == "costpulse.estimate.approve"


def test_literal_takes_precedence_over_wildcard():
    """Subscription with BOTH `costpulse.*` AND
    `costpulse.estimate.approve` fires for both routes; the
    response surfaces the LITERAL as the matched pattern (more
    specific operationally)."""
    out = match_subscription(
        event_types=["costpulse.*", "costpulse.estimate.approve"],
        event_type="costpulse.estimate.approve",
    )
    assert out.matched_via == "literal"
    assert out.matched_pattern == "costpulse.estimate.approve"


def test_wildcard_match_returns_via_wildcard():
    out = match_subscription(
        event_types=["costpulse.*"],
        event_type="costpulse.estimate.approve",
    )
    assert out.matched is True
    assert out.matched_via == "wildcard"
    assert out.matched_pattern == "costpulse.*"


def test_most_specific_wildcard_wins():
    """When `costpulse.*` AND `costpulse.estimate.*` both match
    `costpulse.estimate.approve`, the longer prefix wins for
    partner clarity ("matched via the more specific pattern")."""
    out = match_subscription(
        event_types=["costpulse.*", "costpulse.estimate.*"],
        event_type="costpulse.estimate.approve",
    )
    assert out.matched_via == "wildcard"
    assert out.matched_pattern == "costpulse.estimate.*"


def test_wildcard_does_not_cross_segment_boundary():
    """`costpulse.estimate.*` matches `costpulse.estimate.approve`
    but NOT `costpulse.boq.import` — the prefix-with-trailing-dot
    check enforces the depth."""
    out = match_subscription(
        event_types=["costpulse.estimate.*"],
        event_type="costpulse.boq.import",
    )
    assert out.matched is False
    assert out.matched_via is None
    assert out.matched_pattern is None


def test_no_match_at_all():
    """Subscription with literals + wildcards that all miss →
    matched=False with everything else None."""
    out = match_subscription(
        event_types=["pulse.change_order.approve", "submittals.*"],
        event_type="costpulse.estimate.approve",
    )
    assert out == MatchResult(matched=False, matched_via=None, matched_pattern=None)


def test_malformed_wildcard_in_subscription_is_skipped():
    """If a subscription somehow contains a malformed wildcard
    (`*` alone, embedded `*`), the matcher skips it without
    raising — defensive against legacy data."""
    out = match_subscription(
        event_types=["*", "costpulse.*.approve", "costpulse.*"],
        event_type="costpulse.estimate.approve",
    )
    # Only the well-formed `costpulse.*` should match.
    assert out.matched is True
    assert out.matched_pattern == "costpulse.*"
