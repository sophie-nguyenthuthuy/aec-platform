"""Docs link validity check.

The bug class
-------------
A `.md` file under `docs/` references `[CodeGuard pipeline](./codeguard.md)`.
Someone renames `codeguard.md` to `codeguard-overview.md`. The link
silently breaks. The next contributor who clicks the dead link wastes
time finding the new name. Multiply by ~30 docs.

What we check
-------------
Every markdown link `[label](target)` in every `docs/**/*.md` file.
For each:

  * **Relative file links** (e.g. `./codeguard.md`,
    `../apps/api/services/foo.py`): the target file must exist on
    disk. Catches renames + deletions + typos.

  * **Anchor-only links** (e.g. `#section-heading`): the target
    heading must exist in the same document.

  * **File + anchor** (e.g. `./codeguard.md#config`): both checks.

  * **Bare anchors written outside markdown** (e.g. `<a id="foo">`):
    we honour them as link targets (some docs use them for
    cross-section bookmarks).

What we don't check
-------------------
External URLs (`https://example.com`) — fetching live URLs would
flake on every CI run. Out-of-tree relative links pointing into
`apps/` or `packages/` ARE checked though, since those are repo-
local files we can verify on disk.

False-positive minimisation
---------------------------
Heading-to-anchor conversion follows the GitHub spec: lowercase,
spaces → hyphens, drop punctuation. We accept multiple plausible
slugifications because the reference rendering varies (GitHub vs
mkdocs vs raw markdown). Adding a 5th edge case rule has a worse
precision/recall tradeoff than just accepting any-of.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCS_DIR = _REPO_ROOT / "docs"


# Markdown link regex: `[label](target)`. Captures `target` only.
# The `target` group can contain spaces / parens via balanced
# parens — we keep the regex simple and non-balanced, accepting
# the rare false-negative on URLs containing literal `)` (which
# real-world docs almost never have).
_LINK_RE = re.compile(r"\[(?:[^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# Bare HTML anchors (`<a id="foo">` or `<a name="foo">`) — some docs
# use these for cross-section bookmarks. Honour them as valid link
# targets.
_HTML_ANCHOR_RE = re.compile(r'<a\s+(?:id|name)\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)

# ATX heading lines: `# Foo`, `## Foo`, etc. Setext (`Foo\n===`) are
# rare in our docs and skipped — adding them would add ambiguity for
# negligible gain.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)

# Fenced code blocks. We strip these before running the heading
# regex, otherwise lines like `"next": "14.2.35"` (JSON inside a
# code block) get false-matched as headings via their leading `"`
# (no — `_HEADING_RE` requires leading `#`, so the actual issue is
# different). Real reason: lines inside ``` fences that happen to
# start with `#` (e.g. shell prompts) would falsely match. Strip
# fences for both the heading scan AND the link scan since some
# example code contains `[label](url)` patterns that aren't real
# documentation links.
_FENCE_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


def _strip_fences(text: str) -> str:
    """Remove fenced code blocks from markdown source.

    Replaces each fence with newlines (preserves line numbering
    for failure messages — without this, the line offsets in the
    broken-link report would shift after every code block).
    """

    def _repl(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    return _FENCE_RE.sub(_repl, text)


def _slugify(heading: str) -> set[str]:
    """Convert a markdown heading to its anchor slug.

    Returns a SET of plausible slugifications because different
    renderers normalise differently:
      * GitHub: lowercase, spaces → `-`, drop most punctuation,
        keep alphanumerics + `-` + `_`.
      * GitLab / mkdocs: similar but sometimes preserves `.` or `:`.
      * Naive: just lowercase + spaces → `-`.

    A link is valid if its anchor matches ANY plausible slug. False-
    positive risk is small in practice (collisions across different
    headings within one doc are rare), and the alternative is
    flake-prone single-rule strictness.
    """
    out: set[str] = set()
    base = heading.strip().lower()
    # Variant 1: GitHub-style — drop everything that isn't
    # alphanumeric, hyphen, underscore, or space; collapse spaces to
    # hyphens.
    gh = re.sub(r"[^\w\s-]", "", base, flags=re.UNICODE)
    gh = re.sub(r"\s+", "-", gh).strip("-")
    out.add(gh)
    # Variant 2: even-more-permissive — keep dots + colons (mkdocs).
    perm = re.sub(r"[^\w\s.:_-]", "", base, flags=re.UNICODE)
    perm = re.sub(r"\s+", "-", perm).strip("-")
    out.add(perm)
    # Variant 3: naive lowercase-and-hyphen, no punctuation drop —
    # for headings whose punctuation IS part of the slug.
    naive = re.sub(r"\s+", "-", base).strip("-")
    out.add(naive)
    return out


def _collect_anchors(text: str) -> set[str]:
    """All valid anchor targets in a single markdown document."""
    stripped = _strip_fences(text)
    anchors: set[str] = set()
    for level, heading in _HEADING_RE.findall(stripped):
        del level  # unused; depth doesn't affect anchor validity
        for slug in _slugify(heading):
            if slug:  # skip empty (e.g. heading was punctuation-only)
                anchors.add(slug)
    # HTML anchors fire from the un-stripped text (they're rare in
    # code blocks and harmless if matched there).
    for explicit in _HTML_ANCHOR_RE.findall(text):
        anchors.add(explicit.lower())
    return anchors


def _list_md_files() -> list[Path]:
    return sorted(_DOCS_DIR.rglob("*.md"))


def _is_external(target: str) -> bool:
    """External URLs (skip): http(s)://, mailto:, tel:."""
    return bool(re.match(r"^(?:https?:|mailto:|tel:|ftp:|ftps:)", target, re.IGNORECASE))


def test_every_doc_link_resolves():
    """For each markdown link `[label](target)` in `docs/**/*.md`:
      * If `target` is external → skip (don't fetch live URLs in CI).
      * If `target` starts with `#` → assert the anchor exists in the
        same document.
      * Otherwise it's a path (relative to the doc) optionally
        followed by `#anchor`. Assert the file exists; if there's
        an anchor, assert that too.

    Failure message lists every broken link with `(file:line) target
    → reason` so the fix is unambiguous from the report alone.
    """
    md_files = _list_md_files()
    assert md_files, f"no .md files found under {_DOCS_DIR}; resolver is broken"

    # Pre-compute per-file anchor sets (lazy: only loaded when needed).
    anchor_cache: dict[Path, set[str]] = {}

    def anchors_in(path: Path) -> set[str]:
        if path not in anchor_cache:
            try:
                anchor_cache[path] = _collect_anchors(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                anchor_cache[path] = set()
        return anchor_cache[path]

    broken: list[str] = []
    for md_path in md_files:
        # Strip fenced code blocks so [label](url) patterns inside
        # examples (e.g. a docstring showing markdown syntax) don't
        # get treated as live doc links.
        text = _strip_fences(md_path.read_text(encoding="utf-8"))
        rel = md_path.relative_to(_REPO_ROOT)
        for match in _LINK_RE.finditer(text):
            target = match.group(1)
            if _is_external(target):
                continue
            # Compute (line, col) for the failure message — `find`
            # is fine; the regex already gave us the offset.
            line_no = text[: match.start()].count("\n") + 1

            # Split into path + anchor.
            if "#" in target:
                path_part, anchor = target.split("#", 1)
            else:
                path_part, anchor = target, None

            # Pure-anchor link → resolve in the current doc.
            if not path_part:
                if anchor and anchor.lower() not in anchors_in(md_path):
                    broken.append(f"{rel}:{line_no}  [#{anchor}] target heading not found in this doc")
                continue

            # Resolve relative to the doc's directory.
            target_path = (md_path.parent / path_part).resolve()
            if not target_path.exists():
                broken.append(f"{rel}:{line_no}  {target} → file does not exist")
                continue

            # Anchor on a different file: assert it's a markdown
            # file (we don't anchor-check non-md targets) and the
            # heading exists.
            if anchor:
                if target_path.suffix != ".md":
                    # Non-markdown file with a fragment is unusual
                    # but legal (e.g. pointing at a code-line fragment
                    # on GitHub). Accept; we can't verify these
                    # locally without a renderer.
                    continue
                if anchor.lower() not in anchors_in(target_path):
                    broken.append(
                        f"{rel}:{line_no}  {target} → file exists but heading "
                        f"`#{anchor}` not found in {target_path.relative_to(_REPO_ROOT)}"
                    )

    if broken:
        # Group by reason-class for readability when many break at once.
        pytest.fail(
            f"{len(broken)} broken doc link(s):\n  " + "\n  ".join(broken) + "\n\nFix each by either:\n"
            "  • Updating the link target to the new path/anchor.\n"
            "  • Adding the missing heading / file if it should exist.\n"
            "  • Removing the dead reference."
        )


def test_no_duplicate_headings_within_one_doc():
    """Defensive companion: if two headings in the same doc slugify
    to the same anchor, anchor-only links are ambiguous (the renderer
    appends `-1`, `-2`, ... silently).

    Pin uniqueness so a future PR that adds a duplicate `## Setup`
    section breaks loudly here, not via mysterious doc-link 404s
    weeks later.
    """
    duplicates: list[str] = []
    for md_path in _list_md_files():
        text = _strip_fences(md_path.read_text(encoding="utf-8"))
        slug_counts: dict[str, list[str]] = defaultdict(list)
        for _, heading in _HEADING_RE.findall(text):
            for slug in _slugify(heading):
                if slug:
                    slug_counts[slug].append(heading.strip())
                    break  # only count the first variant — others are duplicates of the same heading
        for slug, headings in slug_counts.items():
            if len(headings) > 1:
                duplicates.append(
                    f"{md_path.relative_to(_REPO_ROOT)}  slug `{slug}` is "
                    f"shared by {len(headings)} headings: {headings}"
                )

    assert not duplicates, (
        f"{len(duplicates)} doc(s) have duplicate heading slugs:\n  "
        + "\n  ".join(duplicates)
        + "\n\nRename one heading per pair so anchor links resolve unambiguously."
    )
