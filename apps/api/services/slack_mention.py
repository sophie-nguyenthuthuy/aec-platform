"""Slack mention parser (cycle QQ3).

Parse Slack-flavored mentions in user-input text. Used by:

  * The Slack alert digest body sanitizer — when echoing user
    notes to a different Slack channel, raw mentions are stripped
    so we don't ping users in the wrong context.
  * The audit note plaintext export.
  * The notification preview that strips Slack-specific syntax.

  parse_slack_mentions(text)  — (stripped_text, mentions_tuple)
  strip_slack_mentions(text)  — text only, mentions removed
  Mention                     — frozen dataclass: (kind, id, display)
  BROADCAST_KINDS             — closed set: {here, channel, everyone}

Slack mention syntax:
  * `<@U12345>`              — user mention by ID
  * `<@U12345|displayname>`  — user with display name
  * `<#C67890|channel-name>` — channel mention with name
  * `<!here>` / `<!channel>` / `<!everyone>` — broadcast

Pinned invariants:
  * Unknown angle-bracket shapes preserved verbatim (NOT
    stripped — defends against false positives from legitimate
    `<text>` content).
  * Unknown broadcast kinds (`<!unknown>`) preserved verbatim.
  * Mentions tuple in document order.
  * BROADCAST_KINDS closed set — pin so a refactor that adds
    a new broadcast kind surfaces here.

Pure stdlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MentionKind = Literal["user", "channel", "broadcast"]


# Closed set of recognized broadcast IDs. Pin so a refactor that
# adds e.g. `<!subteam^X>` surfaces here — Slack-specific subteam
# syntax is out of scope for this parser.
BROADCAST_KINDS: frozenset[str] = frozenset({"here", "channel", "everyone"})


@dataclass(frozen=True)
class Mention:
    """A parsed Slack mention.

    `kind` is one of "user" / "channel" / "broadcast".
    `id` is the raw ID (Slack's U/C-prefixed handle, or the
    broadcast keyword like "here").
    `display` is the human-friendly form: for user/channel,
    the `|`-separated display name if present (else the ID);
    for broadcast, the broadcast keyword itself.
    """

    kind: MentionKind
    id: str
    display: str


# Match: <prefix><id>(|<display>)?
# prefix ∈ {@, #, !}
# id is 1+ chars, no `|` or `>`.
# display (optional) is 0+ chars, no `>`.
_MENTION_RE = re.compile(r"<([@#!])([^|>]+)(?:\|([^>]*))?>")


def _classify(prefix: str, id_part: str) -> MentionKind | None:
    """Classify the mention prefix into a kind, or None if
    unrecognized (preserves the raw text)."""
    if prefix == "@":
        return "user"
    if prefix == "#":
        return "channel"
    if prefix == "!" and id_part in BROADCAST_KINDS:
        return "broadcast"
    return None


def parse_slack_mentions(
    text: str | None,
) -> tuple[str, tuple[Mention, ...]]:
    """Parse Slack mentions, returning stripped text + mentions.

    Returns `(stripped_text, mentions)`:
      * `stripped_text` has all recognized mentions removed.
        Unrecognized angle-bracket shapes (e.g. `<code>`,
        `<!unknown>`) are preserved verbatim.
      * `mentions` is a tuple of Mention dataclasses in
        document order.

    None / empty input → ("", ()).
    """
    if not text:
        return ("", ())

    mentions: list[Mention] = []

    def _replace(m: re.Match[str]) -> str:
        prefix = m.group(1)
        id_part = m.group(2)
        display_part = m.group(3)
        kind = _classify(prefix, id_part)
        if kind is None:
            # Preserve the original text verbatim.
            return m.group(0)
        display = (display_part if display_part else id_part) if kind in ("user", "channel") else id_part
        mentions.append(Mention(kind=kind, id=id_part, display=display))
        return ""

    stripped = _MENTION_RE.sub(_replace, text)
    return (stripped, tuple(mentions))


def strip_slack_mentions(text: str | None) -> str:
    """Return `text` with recognized Slack mentions stripped.

    Convenience wrapper over `parse_slack_mentions`.
    """
    stripped, _ = parse_slack_mentions(text)
    return stripped
