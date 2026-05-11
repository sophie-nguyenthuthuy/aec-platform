"""Slack mention parser (cycle QQ3).

Pinned seams:
  1. BROADCAST_KINDS = {here, channel, everyone}.
  2. <@USER> → user kind.
  3. <#CHANNEL|name> → channel with display.
  4. <!here> → broadcast.
  5. Unknown angle-bracket shapes preserved verbatim.
  6. Mentions in document order.
  7. None / empty → ("", ()).
"""

from __future__ import annotations

from services.slack_mention import (
    BROADCAST_KINDS,
    Mention,
    parse_slack_mentions,
    strip_slack_mentions,
)

# ---------- BROADCAST_KINDS ----------


def test_broadcast_kinds_canonical():
    assert frozenset({"here", "channel", "everyone"}) == BROADCAST_KINDS


def test_broadcast_kinds_is_frozen():
    assert isinstance(BROADCAST_KINDS, frozenset)


# ---------- User mentions ----------


def test_simple_user_mention():
    text, mentions = parse_slack_mentions("Hello <@U12345>!")
    assert text == "Hello !"
    assert mentions == (Mention(kind="user", id="U12345", display="U12345"),)


def test_user_mention_with_display_name():
    text, mentions = parse_slack_mentions("Hi <@U1|alice>")
    assert text == "Hi "
    assert mentions == (Mention(kind="user", id="U1", display="alice"),)


def test_multiple_user_mentions():
    text, mentions = parse_slack_mentions("<@U1> and <@U2>")
    assert text == " and "
    assert mentions == (
        Mention(kind="user", id="U1", display="U1"),
        Mention(kind="user", id="U2", display="U2"),
    )


# ---------- Channel mentions ----------


def test_channel_mention_with_name():
    text, mentions = parse_slack_mentions("In <#C1|general>")
    assert text == "In "
    assert mentions == (Mention(kind="channel", id="C1", display="general"),)


def test_channel_mention_without_display():
    """A bare `<#C1>` (no `|name`) — display falls back to ID."""
    text, mentions = parse_slack_mentions("In <#C1>")
    assert mentions == (Mention(kind="channel", id="C1", display="C1"),)


# ---------- Broadcast ----------


def test_broadcast_here():
    text, mentions = parse_slack_mentions("<!here> attention")
    assert text == " attention"
    assert mentions == (Mention(kind="broadcast", id="here", display="here"),)


def test_broadcast_channel():
    text, mentions = parse_slack_mentions("<!channel>")
    assert text == ""
    assert mentions == (Mention(kind="broadcast", id="channel", display="channel"),)


def test_broadcast_everyone():
    text, mentions = parse_slack_mentions("<!everyone>")
    assert mentions == (Mention(kind="broadcast", id="everyone", display="everyone"),)


# ---------- Unknown shapes preserved ----------


def test_unknown_broadcast_preserved():
    """Cardinal pin: `<!unknown>` is NOT in BROADCAST_KINDS,
    so preserve verbatim. Defends against false positives —
    e.g. an actual subteam mention shouldn't be silently
    stripped without us knowing what we're stripping."""
    text, mentions = parse_slack_mentions("<!unknown>")
    assert text == "<!unknown>"
    assert mentions == ()


def test_legitimate_angle_brackets_preserved():
    """`<code>` is not a Slack mention (no @ # ! prefix) —
    preserved verbatim. Defends against stripping legitimate
    user content."""
    text, mentions = parse_slack_mentions("this is <code>")
    assert text == "this is <code>"
    assert mentions == ()


def test_html_like_tags_preserved():
    text, mentions = parse_slack_mentions("<div>html</div>")
    assert text == "<div>html</div>"


def test_subteam_syntax_preserved():
    """`<!subteam^X>` is Slack subteam mention syntax — out of
    scope, preserve verbatim."""
    text, mentions = parse_slack_mentions("<!subteam^S1234|team>")
    assert text == "<!subteam^S1234|team>"
    assert mentions == ()


# ---------- Mixed content ----------


def test_mention_then_text():
    text, mentions = parse_slack_mentions("<@U1|alice> approved this")
    assert text == " approved this"
    assert mentions[0].display == "alice"


def test_multiple_kinds_in_order():
    """Pin: mentions tuple in document order (NOT grouped by kind)."""
    text, mentions = parse_slack_mentions("<@U1> in <#C1|general> attn <!here>")
    assert mentions == (
        Mention(kind="user", id="U1", display="U1"),
        Mention(kind="channel", id="C1", display="general"),
        Mention(kind="broadcast", id="here", display="here"),
    )


# ---------- Plain text ----------


def test_plain_text_no_mentions():
    text, mentions = parse_slack_mentions("Plain text no mentions")
    assert text == "Plain text no mentions"
    assert mentions == ()


# ---------- Defensive ----------


def test_none_returns_empty():
    text, mentions = parse_slack_mentions(None)
    assert text == ""
    assert mentions == ()


def test_empty_returns_empty():
    text, mentions = parse_slack_mentions("")
    assert text == ""
    assert mentions == ()


# ---------- strip_slack_mentions ----------


def test_strip_removes_recognized_mentions():
    assert strip_slack_mentions("<@U1>hello") == "hello"
    assert strip_slack_mentions("<@U1> world") == " world"


def test_strip_preserves_unknown():
    assert strip_slack_mentions("<!unknown>kept") == "<!unknown>kept"
    assert strip_slack_mentions("<code>kept") == "<code>kept"


def test_strip_none_returns_empty():
    assert strip_slack_mentions(None) == ""


def test_strip_empty_returns_empty():
    assert strip_slack_mentions("") == ""


# ---------- Mention frozen ----------


def test_mention_is_frozen():
    m = Mention(kind="user", id="U1", display="alice")
    try:
        m.id = "U2"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Mention should be frozen")
