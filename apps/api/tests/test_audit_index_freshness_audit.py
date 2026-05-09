"""Audit-index freshness audit.

Meta-audit: pins that `docs/audit-suite.md` is up-to-date with every
`tests/test_*_audit.py`. Without this gate, the index slowly drifts
out of sync with reality — an audit that landed last quarter doesn't
appear in the index, and the page becomes the "I'll trust it later"
kind of doc that nobody trusts.

What this audit checks
----------------------
Re-run the generator (`scripts.generate_audit_index`) in-memory. The
returned text MUST match the contents of `docs/audit-suite.md` byte-
for-byte. A mismatch means somebody added/removed an audit, or
bumped a baseline, without re-running `make audit-index`.

Failure mode is friendly: the diff between expected and actual is
printed in the assertion, and the fix is one shell command.

Why this is its own ratchet, not a hook
---------------------------------------
A pre-commit hook could regenerate the doc on every commit, but
that hides regressions in the generator itself (the doc would
silently re-render with broken output). Failing in pytest forces a
human to look at the diff before landing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _API_ROOT.parent.parent
_DOC_PATH = _REPO_ROOT / "docs" / "audit-suite.md"


def test_audit_index_doc_matches_generator_output():
    """`docs/audit-suite.md` must exactly equal what
    `scripts.generate_audit_index._render(...)` would produce today.

    Failure means the index drifted: someone added an audit, removed
    one, or bumped a baseline without regenerating. Fix:
        cd apps/api && python -m scripts.generate_audit_index
    """
    # Late-import the generator so the rest of the audit suite
    # doesn't pay its parse cost during collection.
    from scripts.generate_audit_index import _audit_files, _render

    expected = _render(_audit_files())

    if not _DOC_PATH.exists():
        pytest.fail(
            f"{_DOC_PATH.relative_to(_REPO_ROOT)} doesn't exist yet. "
            "Generate it with `make audit-index` (or "
            "`cd apps/api && python -m scripts.generate_audit_index`)."
        )

    actual = _DOC_PATH.read_text(encoding="utf-8")
    if actual != expected:
        # Surface a small head-of-diff context. The full diff lives
        # in the file vs. the regenerator output; we just want to
        # tell the operator how to fix it.
        actual_lines = actual.splitlines()
        expected_lines = expected.splitlines()
        head = min(len(actual_lines), len(expected_lines), 80)
        first_diff = next(
            (i for i in range(head) if actual_lines[i] != expected_lines[i]),
            None,
        )
        if first_diff is None and len(actual_lines) != len(expected_lines):
            first_diff = head
        snippet: str
        if first_diff is None:
            snippet = "(no inline diff to show — check tail of file)"
        else:
            snippet = (
                f"  line {first_diff + 1}:\n"
                f"    expected: {expected_lines[first_diff] if first_diff < len(expected_lines) else '<end>'!r}\n"
                f"    actual:   {actual_lines[first_diff] if first_diff < len(actual_lines) else '<end>'!r}"
            )
        pytest.fail(
            f"{_DOC_PATH.relative_to(_REPO_ROOT)} is stale.\n\n"
            f"{snippet}\n\n"
            "Regenerate with:\n"
            "    make audit-index\n"
            "    # or, equivalently:\n"
            "    cd apps/api && python -m scripts.generate_audit_index\n\n"
            "Then commit the regenerated file alongside whatever "
            "audit change you made."
        )
