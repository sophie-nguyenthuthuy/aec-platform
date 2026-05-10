"""Markdown plain-text extractor (cycle NN1).

Strip basic Markdown syntax for plain-text rendering. Used by:

  * The audit row note column — truncated plain text in the
    list view; full markdown in the detail view.
  * The Slack alert digest body — Slack has its own markdown
    flavor, so we strip the user's markdown to avoid double-
    rendering or `> rm -rf /` slipping into Slack as a quoted
    code block.
  * The email digest preview snippet.

  extract_plaintext(markdown)  — plain-text version

Intentionally NOT a full markdown parser:
  * Bold/italic markers stripped (`**bold**` → `bold`).
  * Inline code stripped of backticks (`` `code` `` → `code`).
  * Code BLOCKS (` ```...``` `) → single space (NOT rendered as
    text — defends against `> rm -rf /` slipping verbatim).
  * Links (`[text](url)`) → just `text` (URL dropped).
  * Headers (`# Title`) → just `Title`.
  * Bullet markers (`- `, `* `, `+ `) → stripped.
  * Blockquote markers (`> `) → stripped.

Pinned invariants:
  * Code blocks become single space regardless of content length.
  * Empty input → empty output.
  * Multi-line preserved as newlines.
  * Whitespace NOT collapsed (caller decides if they want that).
  * Nested formatting (e.g. `**bold *italic* bold**`) NOT
    handled — preserved verbatim. Out of scope.

Pure stdlib.
"""

from __future__ import annotations

import re

# Code blocks first: ```...``` (multi-line). Replace whole match
# with a single space — defends against code content rendering
# as plain prose.
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")


# Inline code: `code` → code (drop the backticks).
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")


# Links: [text](url) → text (URL dropped).
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


# Bold (double markers): **text** or __text__ → text.
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")


# Italic (single markers): *text* or _text_ → text.
_ITALIC_RE = re.compile(r"\*([^*]+)\*|_([^_]+)_")


# Headers at line start: # / ## / ... → strip marker + spaces.
_HEADER_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


# Bullet markers at line start: optional whitespace + (-, *, +) + space.
_BULLET_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)


# Blockquote markers at line start.
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s+", re.MULTILINE)


def _bold_replace(m: re.Match[str]) -> str:
    """Bold regex has two alternatives — return whichever matched."""
    return m.group(1) or m.group(2) or ""


def _italic_replace(m: re.Match[str]) -> str:
    return m.group(1) or m.group(2) or ""


def extract_plaintext(markdown: str | None) -> str:
    """Strip Markdown syntax from `markdown` and return plain text.

    None / empty → "".

    Order of operations matters (pin via tests):
      1. Code blocks → single space (FIRST, so backticks inside
         blocks don't get processed as inline code).
      2. Inline code → drop backticks.
      3. Links → text only.
      4. Bold (double) BEFORE italic (single).
      5. Italic.
      6. Headers, bullets, blockquotes (line-anchored markers).
    """
    if markdown is None:
        return ""
    text = markdown

    text = _CODE_BLOCK_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _BOLD_RE.sub(_bold_replace, text)
    text = _ITALIC_RE.sub(_italic_replace, text)
    text = _HEADER_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    text = _BLOCKQUOTE_RE.sub("", text)

    return text
