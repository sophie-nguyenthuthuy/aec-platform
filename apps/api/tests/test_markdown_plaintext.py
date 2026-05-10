"""Markdown plain-text extractor (cycle NN1).

Pinned seams:
  1. Code blocks → single space (defends against verbatim code
     leaking into Slack/email).
  2. Inline code → drops backticks, keeps content.
  3. Links → text only, URL dropped.
  4. Bold (double) before italic (single).
  5. Headers / bullets / blockquotes stripped at line start.
  6. None / empty → "".
  7. Multi-line preserved.
  8. Whitespace NOT collapsed.
"""

from __future__ import annotations

from services.markdown_plaintext import extract_plaintext

# ---------- Plain text ----------


def test_plain_text_passes_through():
    assert extract_plaintext("hello world") == "hello world"


def test_empty_returns_empty():
    assert extract_plaintext("") == ""


def test_none_returns_empty():
    assert extract_plaintext(None) == ""


# ---------- Bold / italic ----------


def test_bold_with_asterisks():
    assert extract_plaintext("**bold**") == "bold"


def test_bold_with_underscores():
    assert extract_plaintext("__bold__") == "bold"


def test_italic_with_asterisks():
    assert extract_plaintext("*italic*") == "italic"


def test_italic_with_underscores():
    assert extract_plaintext("_italic_") == "italic"


def test_bold_and_italic_in_same_line():
    assert extract_plaintext("**bold** and *italic*") == "bold and italic"


def test_bold_inside_sentence():
    assert extract_plaintext("This is **bold** text.") == "This is bold text."


# ---------- Inline code ----------


def test_inline_code_drops_backticks():
    assert extract_plaintext("`code`") == "code"


def test_inline_code_in_sentence():
    assert extract_plaintext("Use `git status` to check") == "Use git status to check"


# ---------- Code blocks ----------


def test_code_block_becomes_single_space():
    """Cardinal pin: code blocks → single space, NOT rendered
    as text. Defends against e.g. `rm -rf /` slipping verbatim
    into a Slack alert body."""
    md = "```\nrm -rf /\n```"
    assert extract_plaintext(md) == " "


def test_code_block_with_language_hint():
    md = "```bash\nls -la\n```"
    assert extract_plaintext(md) == " "


def test_code_block_in_context():
    md = "Hello ```\nls\n``` World"
    # The block is replaced with " ", giving "Hello   World"
    # (three spaces from the surrounding spaces + the replacement).
    assert extract_plaintext(md) == "Hello   World"


def test_multiline_code_block_collapses():
    md = "```\nline1\nline2\nline3\n```"
    assert extract_plaintext(md) == " "


# ---------- Links ----------


def test_link_keeps_text_drops_url():
    assert extract_plaintext("[text](https://example.com)") == "text"


def test_link_in_sentence():
    md = "See [the docs](https://example.com/docs) for details."
    assert extract_plaintext(md) == "See the docs for details."


def test_multiple_links():
    md = "[a](u1) and [b](u2)"
    assert extract_plaintext(md) == "a and b"


# ---------- Headers ----------


def test_h1_stripped():
    assert extract_plaintext("# Title") == "Title"


def test_h2_stripped():
    assert extract_plaintext("## Subtitle") == "Subtitle"


def test_h6_stripped():
    assert extract_plaintext("###### Very small") == "Very small"


def test_header_only_at_line_start():
    """Mid-line `#` is NOT a header."""
    assert extract_plaintext("foo # bar") == "foo # bar"


# ---------- Bullets ----------


def test_dash_bullet_stripped():
    assert extract_plaintext("- item") == "item"


def test_asterisk_bullet_stripped():
    assert extract_plaintext("* item") == "item"


def test_plus_bullet_stripped():
    assert extract_plaintext("+ item") == "item"


def test_multi_bullet_list():
    md = "- item 1\n- item 2\n- item 3"
    assert extract_plaintext(md) == "item 1\nitem 2\nitem 3"


def test_indented_bullet_stripped():
    assert extract_plaintext("  - nested") == "nested"


# ---------- Blockquote ----------


def test_blockquote_stripped():
    assert extract_plaintext("> quoted text") == "quoted text"


def test_multi_line_blockquote():
    md = "> line 1\n> line 2"
    assert extract_plaintext(md) == "line 1\nline 2"


# ---------- Combined ----------


def test_combined_markdown():
    md = "# Title\n\n**Body** with [link](url) and `code`."
    assert extract_plaintext(md) == "Title\n\nBody with link and code."


def test_realistic_audit_note():
    """Realistic audit note: header + body + code reference."""
    md = (
        "## Change order CO-2026-042\n\n"
        "Approved by **Nguyễn Văn A** on the basis of:\n"
        "- supplier quote within budget\n"
        "- timeline acceptable\n\n"
        "See [PR-2026-019](https://example.com/pr/2026-019)."
    )
    expected = (
        "Change order CO-2026-042\n\n"
        "Approved by Nguyễn Văn A on the basis of:\n"
        "supplier quote within budget\n"
        "timeline acceptable\n\n"
        "See PR-2026-019."
    )
    assert extract_plaintext(md) == expected


# ---------- Whitespace preservation ----------


def test_whitespace_not_collapsed():
    """Pin: extractor doesn't collapse whitespace. Caller can
    do that with `' '.join(text.split())` if needed."""
    md = "hello   world"
    assert extract_plaintext(md) == "hello   world"


def test_multi_line_preserved():
    md = "line 1\n\nline 2"
    assert extract_plaintext(md) == "line 1\n\nline 2"
