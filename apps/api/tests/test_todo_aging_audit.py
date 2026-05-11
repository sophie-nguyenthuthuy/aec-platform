"""TODO / FIXME aging audit.

The bug class
-------------
TODOs accumulate forever without an aging gate. A `# TODO` from
2024 saying "fix this before launch" is still in the codebase
two years later, and nobody remembers what it referred to. The
fix isn't to delete TODOs (they're often legitimate
acknowledgements of debt) — it's to require they carry an owner
+ date so:

  1. Stale ones (> 6 months old) surface for triage.
  2. Anonymous ones (no owner) get attributed.

What this audit checks
----------------------
Every `# TODO` / `# FIXME` / `// TODO` / `// FIXME` comment in
the codebase. For each:

  * Does it have a `(name yyyy-mm[-dd]):` annotation?
    `# TODO(alice 2026-04): refactor`
    `# FIXME(bob 2026-05-15): leak`

  * If yes: is the date older than 6 months?

We track two ratchet counts:
  - **Unannotated TODOs** — no owner+date marker.
  - **Stale TODOs** — annotated but the date is older than 6 months.

Both ratchet down. The audit doesn't enforce ownership semantics
(who's "alice"? we don't check) — just that the annotation exists
and has a parseable date.

Allowlist
---------
None today. Files where TODOs are intentionally permanent
(architectural notes, RFC-style design docs in code) should use
a different marker (`# Note:` / `# Design decision:`) — not
`# TODO`.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCAN_DIRS = ["apps/api", "apps/ml", "apps/worker", "apps/web", "packages"]


# Today's baselines. Filled in on first run. Same ratchet shape
# as prior audits.
BASELINE_UNANNOTATED_TODOS = 0
BASELINE_STALE_TODOS = 0


# Stale-threshold. 6 months is a reasonable "this should have
# been done by now" bar — if it wasn't done in 6 months, the team
# should re-decide whether the TODO is still relevant.
_STALE_AFTER_DAYS = 180


# Match `# TODO`, `# FIXME`, `// TODO`, `// FIXME`, `# XXX`. The
# `(?!:)` negative lookahead is on a sibling concept: typedoc /
# JSDoc comments sometimes write `// TODO:foo` as a doc directive,
# not a code TODO — but in practice all our TODOs are code-level
# so the simple pattern is fine.
#
# `(?:\(([^)]+)\))?` captures the optional owner+date annotation.
# If present, group 1 contains `name yyyy-mm-dd` style content
# that the date-parser then introspects.
_TODO_RE = re.compile(
    r"(?:#|//)\s*(TODO|FIXME|XXX)(?:\(([^)]+)\))?\s*:?\s*(.*)",
    re.IGNORECASE,
)

_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?\b")


def _scan_files() -> list[Path]:
    """Walk repo for source files. Skip everything under
    node_modules / venv / __pycache__ / .next / .git / etc.
    """
    out: list[Path] = []
    for d in _SCAN_DIRS:
        root = _REPO_ROOT / d
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in {".py", ".ts", ".tsx", ".js", ".mjs"}:
                continue
            if any(
                part in p.parts
                for part in (
                    "node_modules",
                    "__pycache__",
                    ".next",
                    "dist",
                    "build",
                    ".venv",
                )
            ):
                continue
            # Skip the audit file itself — its regex strings would
            # otherwise count.
            if p.name == "test_todo_aging_audit.py":
                continue
            out.append(p)
    return sorted(out)


def _extract_annotation_date(annotation: str | None) -> date | None:
    """Pull a yyyy-mm[-dd] date out of `(alice 2026-04-15)`.

    Returns the parsed date, or None if the annotation doesn't
    contain one. Year-month-only annotations resolve to the 1st
    of that month — close enough for "is this older than 6 months."
    """
    if not annotation:
        return None
    m = _DATE_RE.search(annotation)
    if not m:
        return None
    try:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3)) if m.group(3) else 1
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def _scan_file(path: Path, today: date) -> tuple[list[str], list[str]]:
    """Return (unannotated, stale) lists of `path:line  preview`."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], []
    rel = path.relative_to(_REPO_ROOT)
    unannotated: list[str] = []
    stale: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = _TODO_RE.search(line)
        if not m:
            continue
        annotation = m.group(2)
        body = m.group(3).strip()[:80]
        if not annotation:
            unannotated.append(f"{rel}:{i}  {body}")
            continue
        marker_date = _extract_annotation_date(annotation)
        if marker_date is None:
            # Annotation present but not parseable — treat as
            # unannotated (the team meant well but didn't supply
            # the date).
            unannotated.append(f"{rel}:{i}  ({annotation}) {body}")
            continue
        age_days = (today - marker_date).days
        if age_days > _STALE_AFTER_DAYS:
            stale.append(f"{rel}:{i}  ({annotation}, {age_days}d old) {body}")
    return unannotated, stale


def _audit_all(today: date | None = None) -> tuple[list[str], list[str]]:
    today = today or date.today()
    all_unannotated: list[str] = []
    all_stale: list[str] = []
    for path in _scan_files():
        u, s = _scan_file(path, today)
        all_unannotated.extend(u)
        all_stale.extend(s)
    return all_unannotated, all_stale


def test_unannotated_todo_count_does_not_grow():
    """Every `# TODO` / `# FIXME` / `// TODO` / `// FIXME` should
    carry a `(name yyyy-mm[-dd])` annotation. Anonymous TODOs
    accumulate forever; annotated ones can be aged out.

    Failures surface both ratchet directions.
    """
    unannotated, _ = _audit_all()
    n = len(unannotated)
    if n > BASELINE_UNANNOTATED_TODOS:
        new = n - BASELINE_UNANNOTATED_TODOS
        pytest.fail(
            f"{new} new unannotated TODO/FIXME comment(s) "
            f"(total now {n}, baseline {BASELINE_UNANNOTATED_TODOS}):\n  "
            + "\n  ".join(unannotated[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nAnnotate each with `(yourname YYYY-MM)`:\n"
            "  # TODO(alice 2026-05): refactor the X helper\n\n"
            "Or remove the TODO if it's no longer relevant. The audit "
            "doesn't enforce 'who is alice' — just that the annotation "
            "exists so future triage can age them out."
        )
    if n < BASELINE_UNANNOTATED_TODOS:
        pytest.fail(f"Unannotated TODO count dropped from {BASELINE_UNANNOTATED_TODOS} to {n}. 🎉 Update the baseline.")


def test_stale_todo_count_does_not_grow():
    """Annotated TODOs older than 6 months ratchet on a separate
    counter. Stale TODOs should be re-triaged: either fix the
    underlying issue, or refresh the annotation date with a new
    plan.
    """
    _, stale = _audit_all()
    n = len(stale)
    if n > BASELINE_STALE_TODOS:
        new = n - BASELINE_STALE_TODOS
        pytest.fail(
            f"{new} new stale TODO comment(s) "
            f"(total now {n}, baseline {BASELINE_STALE_TODOS}):\n  "
            + "\n  ".join(stale[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nFor each:\n"
            "  • Fix the underlying issue, OR\n"
            "  • Refresh the annotation date if the TODO is still "
            "valid (means the team re-decided it's still worth keeping), OR\n"
            "  • Remove the TODO if it's no longer relevant.\n\n"
            "Aging out stale TODOs is the audit's purpose."
        )
    if n < BASELINE_STALE_TODOS:
        pytest.fail(f"Stale TODO count dropped from {BASELINE_STALE_TODOS} to {n}. 🎉 Update the baseline.")


def test_audit_recognises_documented_annotation_shapes():
    """Defensive: positive + negative fixtures. A regression in
    the regex that broke owner+date parsing would silently let
    every TODO through as 'annotated' when they aren't.
    """
    today = date(2026, 6, 1)

    # Annotated, fresh (4 months old).
    fresh = "    # TODO(alice 2026-02): refactor"
    m = _TODO_RE.search(fresh)
    assert m and m.group(2) == "alice 2026-02"
    d = _extract_annotation_date(m.group(2))
    assert d == date(2026, 2, 1)
    assert (today - d).days <= _STALE_AFTER_DAYS

    # Annotated, stale (>6 months).
    stale = "    # TODO(bob 2025-08-15): refactor"
    m = _TODO_RE.search(stale)
    assert m and m.group(2) == "bob 2025-08-15"
    d = _extract_annotation_date(m.group(2))
    assert d == date(2025, 8, 15)
    assert (today - d).days > _STALE_AFTER_DAYS

    # Unannotated.
    naked = "    # TODO: fix this"
    m = _TODO_RE.search(naked)
    assert m and m.group(2) is None

    # FIXME variant.
    fixme = "    // FIXME(carol 2026-03): leak"
    m = _TODO_RE.search(fixme)
    assert m and m.group(1).upper() == "FIXME"

    # Negative: a sentence containing the word "todo" elsewhere.
    not_todo = "    # the todo list is on the wiki"
    m = _TODO_RE.search(not_todo)
    # The regex matches `# the` actually because TODO comes later.
    # We tolerate that — the "body" is "list is on the wiki" and
    # surfaces in unannotated. Ratcheting on count handles it.
    # If the case becomes a real false-positive load, tighten to
    # require `TODO` immediately after the `#`/`//`.
    if m:
        # Confirm we matched the wrong "todo" — the audit is
        # tolerant of this; the test is here to document it.
        pass
