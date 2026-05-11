"""Per-file / per-function complexity budget audit.

The bug class
-------------
Code grows. Files that started at 200 lines drift to 800, then
1500, then nobody wants to touch them because changing anything
is a 30-minute cognitive load. The fix isn't to ban large files
— some surfaces (a router that maps 40 endpoints) are
legitimately large — it's to *pin the max so it can't grow
silently*.

Same shape for functions. A 50-line handler is fine. A 200-line
handler with 6 nested branches is the call site where bugs
hide.

What this audit checks
----------------------
Two ratchet counters:

  1. **Largest file size** (lines of code). Pinned at today's
     largest. New files can't push the ceiling higher without
     the audit failing.

  2. **Largest function size** (lines from `def`/`async def` to
     the last statement). Pinned at today's largest. Same rule.

Both ratchet *down* — when the team refactors the largest file
or extracts a helper out of the largest function, the audit
fails until the constant is updated to the new max.

What it doesn't check
---------------------
* Cyclomatic complexity — adding `mccabe` would catch nested-
  branch bugs more precisely, but the LOC proxy gets 80% of the
  signal at zero cost. If a follow-up audit wants to add it, the
  hook is in `_function_lengths`.
* Test files (`tests/`) — fixtures and table-driven tests are
  legitimately long.
* Generated dirs (`alembic/versions/`, `__pycache__/`).
* Migration / one-shot scripts (`scripts/`).

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent


# Today's baselines. The largest file is `routers/handover.py`
# at 1480 lines; the largest function is
# `services/assistant.py::build_project_context` at 456 lines.
#
# Both should ratchet down. When the next refactor lands, update
# these to the new max — the audit will tell you (it asserts both
# directions).
BASELINE_MAX_FILE_LOC = 1480
BASELINE_MAX_FUNCTION_LOC = 456


# Per-file allowlist. Each entry needs a stated reason. Files in
# the allowlist are exempt from the file-LOC budget. Functions
# named here (via `module.py::function_name`) are exempt from the
# function-LOC budget.
FILE_ALLOWLIST: dict[str, str] = {
    # No entries today.
}
FUNCTION_ALLOWLIST: dict[str, str] = {
    # No entries today.
}


def _python_files() -> list[Path]:
    """All `.py` files under apps/api/, excluding tests, scripts,
    alembic, generated dirs."""
    skip_dirs = {"tests", "scripts", "alembic", "__pycache__"}
    out: list[Path] = []
    for p in _API_ROOT.rglob("*.py"):
        if any(part in skip_dirs for part in p.relative_to(_API_ROOT).parts):
            continue
        out.append(p)
    return sorted(out)


def _file_loc(path: Path) -> int:
    """Total physical lines in the file. Includes comments and
    blank lines — it's a "scrolling cost" budget, not a
    "statement count" budget."""
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


def _function_lengths(path: Path) -> list[tuple[str, int, int]]:
    """Return (function_name, start_line, length_lines) for every
    top-level + nested function in the file. Length is computed
    from `def`/`async def` to the last child statement.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = node.lineno
        end = max(
            (getattr(c, "end_lineno", start) for c in ast.walk(node)),
            default=start,
        )
        out.append((node.name, start, end - start + 1))
    return out


def _audit_file_sizes() -> list[tuple[str, int]]:
    """Return [(relpath, loc), ...] sorted desc by loc, excluding
    allowlisted files."""
    out: list[tuple[str, int]] = []
    for p in _python_files():
        rel = str(p.relative_to(_API_ROOT))
        if rel in FILE_ALLOWLIST:
            continue
        out.append((rel, _file_loc(p)))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def _audit_function_sizes() -> list[tuple[str, int, int]]:
    """Return [(qualified_name, start_line, length), ...] sorted
    desc by length, excluding allowlisted functions."""
    out: list[tuple[str, int, int]] = []
    for p in _python_files():
        rel = str(p.relative_to(_API_ROOT))
        for name, start, length in _function_lengths(p):
            qualified = f"{rel}::{name}"
            if qualified in FUNCTION_ALLOWLIST:
                continue
            out.append((qualified, start, length))
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def test_no_file_exceeds_size_budget():
    """The largest source file under apps/api/ must not exceed
    the pinned ceiling. New files can be larger only by raising
    the baseline — which forces a conversation about whether the
    file should be split.

    Same ratchet pattern. Failure surfaces both directions.
    """
    sizes = _audit_file_sizes()
    if not sizes:
        pytest.skip("no python files found — auditor's path resolution is broken")
    biggest_file, biggest_loc = sizes[0]
    if biggest_loc > BASELINE_MAX_FILE_LOC:
        # Show the top 5 largest so the operator can pick which to split.
        top = "\n  ".join(f"{loc:5d}  {f}" for f, loc in sizes[:5])
        pytest.fail(
            f"`{biggest_file}` is now {biggest_loc} lines "
            f"(baseline {BASELINE_MAX_FILE_LOC}).\n\n"
            f"Top 5 largest files:\n  {top}\n\n"
            "Fixes (in order of preference):\n"
            "  1. Split the file along a natural seam (per-resource\n"
            "     handlers, per-feature services).\n"
            "  2. Extract a sub-package — e.g. `routers/handover/` with\n"
            "     `packages.py`, `events.py`, `mappings.py`.\n"
            "  3. If the file is genuinely cohesive (a giant Pydantic\n"
            "     schema module, an enum table), add it to FILE_ALLOWLIST\n"
            "     with a stated reason.\n"
            "  4. As a last resort, raise BASELINE_MAX_FILE_LOC — but\n"
            "     this means the team has agreed the new ceiling is\n"
            "     acceptable, not that 'we'll split it later.'"
        )
    if biggest_loc < BASELINE_MAX_FILE_LOC:
        pytest.fail(
            f"Largest file dropped from {BASELINE_MAX_FILE_LOC} to "
            f"{biggest_loc} (`{biggest_file}`). 🎉 "
            f"Update `BASELINE_MAX_FILE_LOC` to {biggest_loc}."
        )


def test_no_function_exceeds_size_budget():
    """The longest function under apps/api/ must not exceed the
    pinned ceiling. Same ratchet logic — long functions are the
    call sites where bugs hide; the audit forces a conversation
    every time someone wants to grow the ceiling.
    """
    sizes = _audit_function_sizes()
    if not sizes:
        pytest.skip("no functions found — auditor's path resolution is broken")
    biggest_fn, biggest_line, biggest_len = sizes[0]
    if biggest_len > BASELINE_MAX_FUNCTION_LOC:
        top = "\n  ".join(f"{length:4d}  {name}  (line {line})" for name, line, length in sizes[:5])
        pytest.fail(
            f"`{biggest_fn}` (line {biggest_line}) is now {biggest_len} "
            f"lines (baseline {BASELINE_MAX_FUNCTION_LOC}).\n\n"
            f"Top 5 longest functions:\n  {top}\n\n"
            "Fixes (in order of preference):\n"
            "  1. Extract sub-functions for the obvious phases (parse\n"
            "     input, do work, build response).\n"
            "  2. Lift nested-loop bodies into named helpers — the name\n"
            "     becomes documentation.\n"
            "  3. If the function is genuinely irreducible (a giant\n"
            "     dispatch table, a hand-written parser), add it to\n"
            "     FUNCTION_ALLOWLIST with a stated reason."
        )
    if biggest_len < BASELINE_MAX_FUNCTION_LOC:
        pytest.fail(
            f"Largest function dropped from {BASELINE_MAX_FUNCTION_LOC} "
            f"to {biggest_len} (`{biggest_fn}`). 🎉 "
            f"Update `BASELINE_MAX_FUNCTION_LOC` to {biggest_len}."
        )


def test_allowlist_entries_correspond_to_real_targets():
    """Defensive: stale allowlist entries silently mask future
    regressions. Every key must point at a real file / function.
    """
    real_files = {str(p.relative_to(_API_ROOT)) for p in _python_files()}
    stale_files = [k for k in FILE_ALLOWLIST if k not in real_files]
    assert not stale_files, (
        f"Stale FILE_ALLOWLIST entries (file no longer exists): "
        f"{stale_files}. Remove them so the allowlist reflects only "
        "currently-live exemptions."
    )

    real_fns: set[str] = set()
    for p in _python_files():
        rel = str(p.relative_to(_API_ROOT))
        for name, _start, _length in _function_lengths(p):
            real_fns.add(f"{rel}::{name}")
    stale_fns = [k for k in FUNCTION_ALLOWLIST if k not in real_fns]
    assert not stale_fns, (
        f"Stale FUNCTION_ALLOWLIST entries (function no longer exists): "
        f"{stale_fns}. Remove them so the allowlist reflects only "
        "currently-live exemptions."
    )
