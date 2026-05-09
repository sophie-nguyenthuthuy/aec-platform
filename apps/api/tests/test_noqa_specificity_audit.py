"""`# noqa` specificity audit.

The bug class
-------------
A bare `# noqa` silences EVERY ruff/flake8 lint error on the
line forever. The original author was suppressing one specific
rule (say `E501` for a long URL); a future refactor that breaks
something else on the same line — e.g. introduces a `B008`
mutable-default — silently passes lint because the bare noqa
is also suppressing the new violation.

Sister of `test_type_ignore_specificity_audit.py` for ruff:
- `# type: ignore` → mypy
- `# noqa` → ruff/flake8

The fix is one suffix per noqa: `# noqa: E501` narrows the
suppression to ONLY the original rule. New unrelated lint
violations on the same line surface normally.

What this audit checks
----------------------
Walk every `.py` file under `apps/api/{core,db,middleware,models,
routers,schemas,services,workers}` plus `apps/worker/`. Flag any
line containing a bare `# noqa` (no `:` after).

What's NOT checked
------------------
- `# noqa: E501` is correct — passes.
- `# noqa: E501, B008` is correct — passes.
- Test files (`tests/**`) are out of scope. Tests sometimes use
  bare noqa against ad-hoc fixtures.
- `tests/` directories scanned via `apps/worker` rglob get
  excluded explicitly.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_ROOT = _REPO_ROOT / "apps" / "api"
_SCAN_ROOTS: list[Path] = [
    _API_ROOT / "core",
    _API_ROOT / "db",
    _API_ROOT / "middleware",
    _API_ROOT / "models",
    _API_ROOT / "routers",
    _API_ROOT / "schemas",
    _API_ROOT / "services",
    _API_ROOT / "workers",
    _REPO_ROOT / "apps" / "worker",
]


# Today's baseline. Filled in on first run.
BASELINE_BARE_NOQA = 0


# Match `# noqa` NOT immediately followed by `:`. Tolerates
# trailing whitespace + end-of-line + a free-text comment.
# The (?!\s*:) negative lookahead allows whitespace-then-colon
# (which would be `# noqa : E501` — rare but valid ruff syntax).
_BARE_NOQA_RE = re.compile(r"#\s*noqa(?!\s*:)\b")


def _scan_files() -> list[Path]:
    out: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            if "tests" in p.parts:
                continue
            if p.name == "test_noqa_specificity_audit.py":
                continue
            out.append(p)
    return sorted(out)


def _scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    rel = path.relative_to(_REPO_ROOT).as_posix()
    findings: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if _BARE_NOQA_RE.search(line):
            findings.append(f"{rel}:{i}  {line.strip()[:80]}")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_bare_noqa_comments():
    """Every `# noqa` should specify the rule code(s) it
    suppresses: `# noqa: E501`, not bare.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_BARE_NOQA:
        new = n - BASELINE_BARE_NOQA
        pytest.fail(
            f"{new} new bare `# noqa` comment(s) "
            f"(total now {n}, baseline {BASELINE_BARE_NOQA}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace with the specific rule code:\n"
            "    # was:\n"
            "    long_url = '…'  # noqa\n"
            "    # use:\n"
            "    long_url = '…'  # noqa: E501\n\n"
            "Run `ruff check apps/api` to find the actual rule "
            "code; ruff prints it in the error line. A bare noqa "
            "silently suppresses every future violation on the "
            "line — the next refactor's regression goes invisible."
        )
    if n < BASELINE_BARE_NOQA:
        pytest.fail(f"Bare-noqa count dropped from {BASELINE_BARE_NOQA} to {n}. 🎉 Update `BASELINE_BARE_NOQA` to {n}.")


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative fixtures."""
    # Positive: bare noqa.
    for src in [
        "x = 1  # noqa",
        "x = 1  #noqa",
        "x = 1  # noqa  # extra commentary",
    ]:
        assert _BARE_NOQA_RE.search(src), f"Audit missed bare form: {src!r}"

    # Negative: specific-code forms.
    for src in [
        "x = 1  # noqa: E501",
        "x = 1  # noqa: E501, B008",
        "x = 1  #noqa:F401",
        "x = 1  # noqa : E501",  # whitespace before colon
    ]:
        assert not _BARE_NOQA_RE.search(src), f"Audit false-positively flagged a specific form: {src!r}"

    # Negative: word `noqa` inside text where there's no `#` prefix
    # — shouldn't match.
    for src in [
        "x = 'noqa'",
        "noqa_helper = lambda: None",
    ]:
        assert not _BARE_NOQA_RE.search(src), f"Audit false-positively matched a non-comment: {src!r}"
