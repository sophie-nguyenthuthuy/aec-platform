"""Webhook subscription match preview (cycle W3).

Pure-helper module. Given a subscription's `event_types[]` array and
a candidate `event_type`, decides whether the subscription would
fire for that event AND why.

Mirrors the dispatcher's matching rule from `services.webhooks.enqueue_event`:

  * empty `event_types[]`        → match all (matched_via='all')
  * literal `event_type` in list → exact match (matched_via='literal')
  * `<prefix>.*` wildcard match  → matched_via='wildcard',
                                   matched_pattern returns the
                                   wildcard literal that matched

Why a separate helper from `services.webhooks._wildcard_candidates`:
that one builds candidate wildcards FROM an event_type FOR the
dispatcher's PG `&&` lookup. This one does the reverse — checks
whether a subscription's static list MATCHES a given event — and
returns structured result for partner-facing UI ("matched via
wildcard `costpulse.*`").

Power: drives `POST /api/v1/webhooks/{id}/match-preview` so
partners can verify "would my subscription receive event X?"
without firing a real test event.

Pure Python, no DB, no async — invoke directly from anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchResult:
    """Structured result for the partner-facing match preview.

    `matched`: bool — would the dispatcher fire this subscription?
    `matched_via`: one of:
      * `"all"`     — subscription has empty event_types[] (catch-all)
      * `"literal"` — exact event_type appears in event_types[]
      * `"wildcard"` — a `<prefix>.*` pattern in event_types[] matches
      * `None`      — no match (matched=False)
    `matched_pattern`: the specific entry in event_types[] that
      matched. Only populated when matched_via in {"literal", "wildcard"}.
      For wildcard matches this is the wildcard string ("costpulse.*"),
      which the partner can then look up in the docs.
    """

    matched: bool
    matched_via: str | None
    matched_pattern: str | None


def match_subscription(*, event_types: list[str], event_type: str) -> MatchResult:
    """Decide whether a subscription's `event_types[]` matches the
    supplied `event_type`.

    Order of evaluation mirrors the dispatcher SQL:
      1. Empty list → match-all.
      2. Exact literal match.
      3. Wildcard match (any `<prefix>.*` whose prefix is a parent
         segment of the event_type).

    A subscription with BOTH a literal AND a wildcard that match
    reports the LITERAL match — the literal is more specific and
    the partner-facing message benefits from showing the exact
    entry that "wins."
    """
    # 1. Empty list = catch-all (the dispatcher's
    # `cardinality(event_types) = 0` branch).
    if not event_types:
        return MatchResult(matched=True, matched_via="all", matched_pattern=None)

    # 2. Exact literal — preferred over wildcard when both match.
    if event_type in event_types:
        return MatchResult(matched=True, matched_via="literal", matched_pattern=event_type)

    # 3. Wildcard scan. Walk every entry; the first matching
    # wildcard wins. Multiple wildcards CAN match — for
    # `costpulse.estimate.approve`, both `costpulse.estimate.*`
    # and `costpulse.*` would match. We return the most-specific
    # one (longest prefix) for partner clarity.
    matching_wildcards: list[str] = []
    for entry in event_types:
        if not _is_wildcard_pattern(entry):
            continue
        prefix = entry[:-2]  # drop `.*`
        if event_type.startswith(prefix + "."):
            matching_wildcards.append(entry)

    if matching_wildcards:
        # Most-specific = longest prefix = wins. `costpulse.estimate.*`
        # over `costpulse.*` for `costpulse.estimate.approve`.
        best = max(matching_wildcards, key=len)
        return MatchResult(matched=True, matched_via="wildcard", matched_pattern=best)

    # No match.
    return MatchResult(matched=False, matched_via=None, matched_pattern=None)


def _is_wildcard_pattern(entry: str) -> bool:
    """True iff `entry` is a `<prefix>.*` wildcard form. Mirrors the
    schema validator in `schemas.webhooks.WebhookSubscriptionCreate`:
    must end with `.*`, must have a non-empty prefix, no embedded
    `*`."""
    if not entry.endswith(".*"):
        return False
    prefix = entry[:-2]
    if not prefix:
        return False
    return "*" not in prefix
