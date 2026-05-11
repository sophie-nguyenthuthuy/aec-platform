"""Naive-datetime audit.

The bug class
-------------
Two shapes of the same bug:

1. **`datetime.utcnow()`** — returns a naive datetime (no tzinfo).
   Python 3.12 deprecated it; Python 3.14 will remove it. The
   replacement is `datetime.now(UTC)`. We've already eaten one
   `DeprecationWarning` from `services/retention.py` — silent
   today, hard breakage on the next Python upgrade.

2. **`datetime.now()` (no tzinfo)** — returns the local machine's
   wall clock, naive. In dev with UTC laptops it's "fine"; in prod
   on a UTC container it's "fine"; the bug fires when one row is
   written by a UTC service and one by a non-UTC service, because
   timestamps no longer compare meaningfully. The fix is the same:
   `datetime.now(UTC)`.

Both produce naive datetimes that, mixed with timezone-aware ones
elsewhere in the codebase, raise `TypeError: can't compare offset-
naive and offset-aware datetimes` at runtime — usually inside a
sort or filter that worked locally and crashes on the first row in
prod with a non-trivial dataset.

What this audit checks
----------------------
For every `.py` file under `apps/api/{core,db,middleware,models,
routers,schemas,services,workers}` plus `apps/worker/`:

- Any call site of `datetime.utcnow(`, `datetime.utcfromtimestamp(`,
  `datetime.utcnow ()` (with whitespace), `dt.utcnow(`. Catches both
  the FQ form and `from datetime import datetime; datetime.utcnow()`.

- `datetime.now(` calls that pass NO arguments — the audit can't
  fully resolve "is this `now` the datetime class's classmethod or
  some other callable" statically without a full-fidelity AST walk,
  but the syntactic shape `datetime.now()` is high-precision-enough
  to flag and almost never legitimate (the `tz` arg is omitted
  almost only by accident).

What's NOT checked
------------------
- `datetime.now(UTC)`, `datetime.now(timezone.utc)`,
  `datetime.now(tz=...)` — these pass a tzinfo, audit is happy.
- `time.time()`, `time.monotonic()` — different bug class
  (epoch-seconds doesn't carry the tz bug).
- Test fixtures and the audit's own regex strings.

Same ratchet pattern as the prior audits.
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


# Today's baseline. Filled in on first run. Same shape as cron-mutex,
# tenant-predicate, etc.
BASELINE_NAIVE_DATETIMES = 0


# Per-(file, line-fragment) allowlist for legitimate cases. Each
# entry needs a stated reason. An empty rationale silences the gate.
#
# Format: (relative_posix_path, exact_line_substring) → reason
ALLOWLIST: dict[tuple[str, str], str] = {
    # No entries today — every call site should use timezone-aware
    # datetimes. Add lazily as legitimate exceptions surface (e.g.
    # interop with a third-party SDK that requires naive UTC).
}


# `datetime.utcnow(`, `datetime.utcfromtimestamp(`, and the `dt.`-
# aliased forms. We match a word-boundary before the symbol so a
# function called `my_datetime_utcnow_helper` doesn't false-match.
_UTCNOW_RE = re.compile(
    r"\b(?:datetime|dt)\s*\.\s*(?:utcnow|utcfromtimestamp)\s*\(",
)

# `datetime.now()` / `dt.now()` with NO arguments inside the parens
# (or whitespace only). Passes when the call is `datetime.now(UTC)`,
# `datetime.now(tz=...)`, etc. The negative class avoids `now()`
# methods on unrelated objects (`session.now()`, `redis.now()`) by
# requiring `datetime.` or `dt.` immediately before.
_NAIVE_NOW_RE = re.compile(
    r"\b(?:datetime|dt)\s*\.\s*now\s*\(\s*\)",
)


def _scan_files() -> list[Path]:
    """Walk every `.py` under the configured roots."""
    out: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            # Skip the audit file itself — its regex strings would
            # otherwise count.
            if p.name == "test_naive_datetime_audit.py":
                continue
            out.append(p)
    return sorted(out)


def _scan_file(path: Path) -> list[str]:
    """Return offender strings of the form `path:line  preview`."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    rel = path.relative_to(_REPO_ROOT).as_posix()
    findings: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        # Strip line comments — a `# datetime.utcnow()` discussion in
        # a comment block isn't a runtime call site. We only care
        # about live code.
        code_part = line.split("#", 1)[0]
        for regex, _label in (
            (_UTCNOW_RE, "utcnow"),
            (_NAIVE_NOW_RE, "naive_now"),
        ):
            if regex.search(code_part):
                # Allowlist match — stripped surrounding whitespace
                # so the key is line-content-stable.
                content = line.strip()
                if (rel, content) in ALLOWLIST:
                    continue
                preview = content[:80]
                findings.append(f"{rel}:{i}  {preview}")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_new_naive_datetime_call_sites():
    """Every `datetime.utcnow()` / `datetime.now()` (no-arg) call
    site should be replaced with `datetime.now(UTC)` (or equivalent
    timezone-aware form).

    Failures surface both ratchet directions:
      * COUNT > BASELINE: a new naive call landed. Replace with
        `datetime.now(UTC)`. Import `from datetime import UTC`
        (or `timezone` for older Python) at the top of the file.
      * COUNT < BASELINE: someone fixed one. 🎉 Update the
        baseline so future regressions can't silently rebuild back.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_NAIVE_DATETIMES:
        new = n - BASELINE_NAIVE_DATETIMES
        pytest.fail(
            f"{new} new naive-datetime call site(s) "
            f"(total now {n}, baseline {BASELINE_NAIVE_DATETIMES}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace each with the timezone-aware form:\n"
            "    # was:\n"
            "    datetime.utcnow()\n"
            "    # use:\n"
            "    datetime.now(UTC)\n\n"
            "Naive datetimes silently mis-compare with timezone-aware "
            "ones (`TypeError: can't compare offset-naive and offset-"
            "aware datetimes`) at the first runtime sort or filter — "
            "usually fine in dev, breaks on the first non-trivial "
            "prod row.\n\n"
            "If a call site genuinely needs the naive form (interop "
            "with a third-party SDK), add it to ALLOWLIST in this "
            "test with a one-line reason."
        )
    if n < BASELINE_NAIVE_DATETIMES:
        pytest.fail(
            f"Naive-datetime count dropped from {BASELINE_NAIVE_DATETIMES} "
            f"to {n}. 🎉 Update `BASELINE_NAIVE_DATETIMES` to {n}."
        )


def test_audit_recognises_documented_naive_shapes():
    """Defensive: positive + negative fixtures. A regression in the
    regex that broke `datetime.utcnow` matching would silently let
    every naive call site through.
    """
    # Positive: every naive form should match.
    for src in [
        "x = datetime.utcnow()",
        "x = datetime.utcfromtimestamp(1234567890)",
        "x = dt.utcnow()",
        "x = datetime . utcnow ()",  # whitespace-tolerant
        "x = datetime.now()",
        "x = dt.now()",
    ]:
        utc_hit = _UTCNOW_RE.search(src)
        naive_hit = _NAIVE_NOW_RE.search(src)
        assert utc_hit or naive_hit, f"Audit missed naive form: {src!r}"

    # Negative: timezone-aware forms must NOT match the naive
    # `datetime.now()` regex.
    for src in [
        "x = datetime.now(UTC)",
        "x = datetime.now(timezone.utc)",
        "x = datetime.now(tz=UTC)",
        "x = datetime.now(  UTC  )",
    ]:
        assert not _NAIVE_NOW_RE.search(src), f"Audit false-positively flagged a tz-aware form: {src!r}"

    # Negative: an unrelated `.now()` method on a non-datetime object
    # must NOT match.
    for src in [
        "x = session.now()",
        "x = redis.now()",
        "x = my_clock.now()",
    ]:
        assert not _NAIVE_NOW_RE.search(src), f"Audit false-positively flagged unrelated `.now()`: {src!r}"


def test_allowlist_entries_actually_correspond_to_real_lines():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions. Every (path, line-content) tuple must correspond
    to a line that the regex would otherwise flag.
    """
    if not ALLOWLIST:
        return  # nothing to check today
    real: set[tuple[str, str]] = set()
    for path in _scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for line in text.splitlines():
            code_part = line.split("#", 1)[0]
            if _UTCNOW_RE.search(code_part) or _NAIVE_NOW_RE.search(code_part):
                real.add((rel, line.strip()))
    stale = [k for k in ALLOWLIST if k not in real]
    assert not stale, (
        f"Stale ALLOWLIST entries: {stale}. Remove them so the allowlist reflects only currently-live exemptions."
    )
