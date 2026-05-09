"""`# type: ignore` specificity audit.

The bug class
-------------
A bare `# type: ignore` silences EVERY mypy error on the line
forever. The original author was suppressing one specific error
(say `arg-type`); a future refactor that breaks something else
on the same line — e.g. introduces a `union-attr` violation —
silently passes typecheck because the bare ignore is also
suppressing the new bug.

The fix is one character per ignore: `# type: ignore[arg-type]`
narrows the suppression to ONLY the original error code. New
unrelated errors on the same line surface normally.

What this audit checks
----------------------
Walk every `.py` file under `apps/api/{core,db,middleware,models,
routers,schemas,services,workers}` plus `apps/worker/`. Flag any
line containing a bare `# type: ignore` (no `[code]` after).

What's NOT checked
------------------
- `# type: ignore[code]` is correct — passes.
- `# type: ignore[code1, code2]` is correct — passes.
- `# type: ignore` inside a string literal or a docstring would
  be a false positive in principle, but the scan looks for the
  marker anywhere on the line. We accept that risk; in practice
  no codebase has the literal substring `# type: ignore` inside
  a string.
- Test files (`tests/**`) are out of scope. Tests legitimately
  use bare ignores against ad-hoc mock objects.

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
BASELINE_BARE_TYPE_IGNORE = 0


# Match `# type: ignore` NOT immediately followed by `[`. The
# negative lookahead is on the next char after `ignore`. Tolerates
# trailing whitespace + end-of-line + a free-text comment.
_BARE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore(?!\[)")


def _scan_files() -> list[Path]:
    out: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            if p.name == "test_type_ignore_specificity_audit.py":
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
        if _BARE_IGNORE_RE.search(line):
            findings.append(f"{rel}:{i}  {line.strip()[:80]}")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_bare_type_ignore_comments():
    """Every `# type: ignore` should specify the error code(s) it
    suppresses: `# type: ignore[arg-type]`, not bare.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_BARE_TYPE_IGNORE:
        new = n - BASELINE_BARE_TYPE_IGNORE
        pytest.fail(
            f"{new} new bare `# type: ignore` comment(s) "
            f"(total now {n}, baseline {BASELINE_BARE_TYPE_IGNORE}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace with the specific error code:\n"
            "    # was:\n"
            "    foo  # type: ignore\n"
            "    # use:\n"
            "    foo  # type: ignore[arg-type]\n\n"
            "Run `mypy apps/api` to find the actual code; mypy prints "
            "it in brackets at the end of each error line. A bare "
            "ignore silently suppresses every future error on the "
            "line — the next refactor's regression goes invisible."
        )
    if n < BASELINE_BARE_TYPE_IGNORE:
        pytest.fail(
            f"Bare-type-ignore count dropped from "
            f"{BASELINE_BARE_TYPE_IGNORE} to {n}. 🎉 Update "
            f"`BASELINE_BARE_TYPE_IGNORE` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative fixtures."""
    # Positive: bare ignores at various spacings.
    for src in [
        "x = 1  # type: ignore",
        "x = 1  # type:ignore",
        "x = 1  # type: ignore  # extra commentary",
        "x = 1  #type: ignore",
    ]:
        assert _BARE_IGNORE_RE.search(src), f"Audit missed bare form: {src!r}"

    # Negative: specific-code forms.
    for src in [
        "x = 1  # type: ignore[arg-type]",
        "x = 1  # type: ignore[arg-type, return-value]",
        "x = 1  # type:ignore[union-attr]",
    ]:
        assert not _BARE_IGNORE_RE.search(src), (
            f"Audit false-positively flagged a specific form: {src!r}"
        )
