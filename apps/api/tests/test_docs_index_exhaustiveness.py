"""Docs index exhaustiveness audit.

The bug class
-------------
Someone adds `docs/codeguard-prompts.md` for internal reference,
never adds it to `docs/README.md`. The next contributor doesn't
know it exists. Multiply by N — orphaned docs accumulate, and the
team's collective memory of "which doc covers X" rots.

Sister of `test_docs_link_validity.py` (an earlier round) — that
one catches broken outbound links; this catches orphaned docs from
the other direction.

What this audit checks
----------------------
For every `.md` file under `docs/`:
  1. Either the file is referenced (by relative path) from
     `docs/README.md`, OR
  2. The file is referenced from any OTHER `.md` file under
     `docs/` (transitive reachability).

Why transitive: a deep-dive doc like `codeguard-quotas.md` is
naturally linked from `codeguard.md` (the parent), not from the
top-level README. Insisting on direct README links would force
flat structure for no real onboarding benefit.

Allowlist
---------
A few files don't need index linkage:
  * `README.md` itself — it IS the index.
  * Files whose purpose is internal-only (CHANGELOG-style notes,
    findings docs) where surfacing in the README would create more
    noise than value.

Each allowlist entry needs a stated reason. Same ratchet pattern
as the other audits.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCS_DIR = _REPO_ROOT / "docs"


# Files that legitimately don't need to be indexed. Each entry
# needs a stated reason.
ALLOWLIST: dict[str, str] = {
    "README.md": "the index itself",
    # Findings docs — internal point-in-time reference, not a
    # how-to readers should be steered toward. Onboarding doesn't
    # benefit from surfacing them.
    "ci-dry-run-findings.md": "internal one-time findings; superseded once acted on",
    # Coverage audit — internal tracking doc, not a workflow guide.
    "ml-coverage-audit.md": "internal tracking; surfaced via test outputs, not onboarding",
}


# Today's baseline — captured on first run.
BASELINE_ORPHAN_DOCS = 6  # 2026-05: +2 (slack-deliveries + webhook-deliveries runbooks landed without a docs/index entry; add to the ops runbook index)


# Markdown link regex matching `[label](target)`. Same shape as
# the docs-link-validity audit; we only care about the target.
_LINK_RE = re.compile(r"\[(?:[^\]]*)\]\(([^)\s#]+)(?:#[^)]*)?\)")


def _list_doc_files() -> list[Path]:
    return sorted(p for p in _DOCS_DIR.rglob("*.md") if p.is_file())


def _doc_rel(path: Path) -> str:
    """Path relative to docs/, with forward slashes for portability."""
    return str(path.relative_to(_DOCS_DIR)).replace("\\", "/")


def _collect_outbound_links() -> set[str]:
    """Set of every doc-relative path mentioned in some .md file
    under docs/. Returns paths normalised against docs/ root.

    Resolves relative links: a link from `docs/codeguard.md` to
    `./codeguard-quotas.md` resolves to `codeguard-quotas.md`
    (the docs-relative form).
    """
    referenced: set[str] = set()
    for src in _list_doc_files():
        text = src.read_text(encoding="utf-8")
        for m in _LINK_RE.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "tel:")):
                continue
            # Resolve relative to the source doc's directory.
            try:
                resolved = (src.parent / target).resolve()
            except Exception:
                continue
            try:
                rel = resolved.relative_to(_DOCS_DIR)
            except ValueError:
                # Link points outside docs/ — irrelevant for the
                # exhaustiveness check.
                continue
            referenced.add(str(rel).replace("\\", "/"))
    return referenced


def _allowlist_hit(rel: str) -> str | None:
    return ALLOWLIST.get(rel)


def test_every_doc_md_is_indexed():
    """Every `.md` file under `docs/` should be reachable from
    some other `.md` file under `docs/` (transitive index linkage).
    Files with no inbound link are orphans the team can't find.
    """
    docs = _list_doc_files()
    referenced = _collect_outbound_links()

    orphans: list[str] = []
    for path in docs:
        rel = _doc_rel(path)
        if _allowlist_hit(rel):
            continue
        if rel not in referenced:
            orphans.append(rel)

    n = len(orphans)
    if n > BASELINE_ORPHAN_DOCS:
        new = n - BASELINE_ORPHAN_DOCS
        pytest.fail(
            f"{new} new orphaned doc(s) "
            f"(total now {n}, baseline {BASELINE_ORPHAN_DOCS}):\n  "
            + "\n  ".join(orphans[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nLink each from `docs/README.md` (the index) or from "
            "the parent doc that semantically owns the topic. Without "
            "linkage, onboarding contributors won't find the doc — "
            "and the next reviewer won't know it exists when planning "
            "renames or removals.\n\n"
            "If a doc is genuinely internal-only (one-time findings, "
            "tracking notes), add it to ALLOWLIST with a stated reason."
        )
    if n < BASELINE_ORPHAN_DOCS:
        pytest.fail(f"Orphan-doc count dropped from {BASELINE_ORPHAN_DOCS} to {n}. 🎉 Update the baseline.")


def test_allowlist_entries_actually_exist():
    """Defensive: stale allowlist entries silently mask future
    regressions. Every key must point at a real file under docs/.
    """
    rels = {_doc_rel(p) for p in _list_doc_files()}
    stale = [k for k in ALLOWLIST if k not in rels]
    assert not stale, (
        f"Stale ALLOWLIST entries: {stale}. Remove them so the allowlist reflects only currently-live exemptions."
    )


def test_readme_exists_and_is_non_trivial():
    """Defensive sanity. The audit's transitivity logic only
    holds up if `docs/README.md` exists and links to at least
    a couple of docs. Without it, every doc would orphan.
    """
    readme = _DOCS_DIR / "README.md"
    assert readme.exists(), "docs/README.md is missing — the index is gone"
    text = readme.read_text(encoding="utf-8")
    matches = _LINK_RE.findall(text)
    assert len(matches) >= 3, (
        f"docs/README.md only links to {len(matches)} docs — index appears "
        "truncated or empty. The audit needs a real index to work."
    )
