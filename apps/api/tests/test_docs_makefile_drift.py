"""Documentation ↔ Makefile drift detector.

Bug class: someone adds `make test-foo` to the Makefile and never
documents it — new contributors never find it. Or someone renames a
target and the docs still say `make test-old`. The runbook docs rot
faster than anything else in the repo because runtime tests can't
see them.

Two checks
----------
1. Every test-related Make target (anything matching `test*` or
   `hooks` or `lint`) appears as a substring in `docs/testing.md`.
   Exact-substring lets the docs format the target however reads
   best (`\\`make X\\`` in a heading, `make X` in prose, etc.) — the
   test only cares that it's mentioned somewhere.

2. Every `make <target>` reference in `docs/testing.md` resolves to
   a real target in the Makefile. Catches the renamed-but-not-
   updated direction.

Why these two checks
--------------------
Test-related is the scope of `docs/testing.md`. We don't gate on
non-test targets (`seed-demo`, `eval-codeguard`, `backfill-*`)
because those have their own runbooks elsewhere; coupling them to
the testing doc would create false drift signal.

If a target legitimately doesn't need a docs entry (e.g. an
internal helper that other targets depend on but isn't run
directly), add it to `INTERNAL_TARGETS` below with a one-line
reason — same allowlist pattern as the auth-audit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MAKEFILE = _REPO_ROOT / "Makefile"
_DOCS = _REPO_ROOT / "docs" / "testing.md"


# Targets we don't require a docs entry for — internal helpers that
# the user shouldn't invoke directly. Each entry needs a one-line
# rationale; an empty rationale turns the allowlist into noise.
INTERNAL_TARGETS: dict[str, str] = {
    "test-api-integration-up": "boot helper for `test-api-integration`; never invoked alone",
}


# Regex for a Makefile target line: `target-name:` at column 0,
# followed by optional dependencies. Filters out comments + .PHONY +
# variable assignments.
_TARGET_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9_\-]*)\s*:")

# `make <target>` references in the docs. Matches both inline
# (`make test-api`) and code-block forms (`make test-api`).
_MAKE_REF_RE = re.compile(r"\bmake\s+([a-zA-Z][a-zA-Z0-9_\-]+)")


def _list_make_targets() -> set[str]:
    """Parse the Makefile and return every declared target name.

    Skips lines that aren't target declarations (variable
    assignments via `:=`, `=`, `+=`).
    """
    targets: set[str] = set()
    for raw in _MAKEFILE.read_text(encoding="utf-8").splitlines():
        # Skip comments + recipes (recipes start with TAB).
        if not raw or raw.startswith("\t") or raw.lstrip().startswith("#"):
            continue
        # Skip variable assignments: `FOO := ...` or `FOO = ...`.
        if "=" in raw and re.match(r"^[A-Z_]+\s*[:+]?=", raw):
            continue
        m = _TARGET_RE.match(raw)
        if m:
            targets.add(m.group(1))
    return targets


def _testing_scope_targets(all_targets: set[str]) -> set[str]:
    """Filter to targets that should be documented in docs/testing.md.

    Heuristic: starts with `test`. Everything else lives in its own
    runbook — `lint` + `hooks` belong in CONTRIBUTING.md (formatter
    + commit-hook setup, not testing); `seed-*` + `eval-*` +
    `backfill-*` are operational tools documented per-feature.
    Including them here would create false-drift signal because
    they're correctly NOT in docs/testing.md.
    """
    return {t for t in all_targets if t.startswith("test")}


def test_every_testing_target_is_documented():
    """For each in-scope Make target, the target name must appear as
    a substring somewhere in `docs/testing.md`.

    Substring (rather than backtick-wrapped) check is intentional:
    the docs author has freedom to format `make test-api` inline,
    `\\`test-api\\`` in a table, or `**test-api**` in a callout —
    all should satisfy the assertion.
    """
    all_targets = _list_make_targets()
    in_scope = _testing_scope_targets(all_targets) - INTERNAL_TARGETS.keys()
    docs_text = _DOCS.read_text(encoding="utf-8")

    undocumented = sorted(t for t in in_scope if t not in docs_text)
    if undocumented:
        pytest.fail(
            f"{len(undocumented)} test-related Make target(s) missing from "
            f"{_DOCS.relative_to(_REPO_ROOT)}:\n  "
            + "\n  ".join(undocumented)
            + "\n\nAdd a section / row mentioning each by name. If a target "
            "is genuinely internal (e.g. a setup helper invoked only by "
            "another target), add it to `INTERNAL_TARGETS` with a "
            "one-line reason."
        )


def test_every_doc_make_reference_points_at_real_target():
    """Reverse direction: every `make <target>` reference in
    `docs/testing.md` must resolve to a real target.

    Catches the rename-but-not-updated rot: someone renames
    `test-api` to `test-api-unit` and the docs still say
    `make test-api`. New contributor copies the line, gets `make:
    *** No rule to make target 'test-api'`, files an issue.

    We exclude references that match a known meta-pattern like
    `make test-X-cov` shown as a TEMPLATE in a "running coverage"
    explainer. Those use angle-brackets / placeholder names that
    obviously aren't real targets — the regex below already skips
    them by requiring a hyphen-only target name (no `<` etc.).
    """
    all_targets = _list_make_targets()
    docs_text = _DOCS.read_text(encoding="utf-8")
    referenced = set(_MAKE_REF_RE.findall(docs_text))

    missing = sorted(r for r in referenced if r not in all_targets)
    if missing:
        pytest.fail(
            f"{len(missing)} `make <target>` reference(s) in "
            f"{_DOCS.relative_to(_REPO_ROOT)} point at non-existent "
            f"targets:\n  " + "\n  ".join(missing) + "\n\nEither add the target to the Makefile, or update the "
            "docs to reference the renamed target. New contributors "
            "copy these literally — broken references waste their time."
        )


def test_internal_target_allowlist_entries_actually_exist():
    """Defensive: every `INTERNAL_TARGETS` entry must reference a
    real target. Otherwise a stale entry sits in the allowlist
    forever and silently masks future drift."""
    all_targets = _list_make_targets()
    stale = [t for t in INTERNAL_TARGETS if t not in all_targets]
    assert not stale, (
        f"INTERNAL_TARGETS has stale entries (target removed from Makefile): {stale}.\n"
        "Remove them so the allowlist reflects only currently-live exemptions."
    )
