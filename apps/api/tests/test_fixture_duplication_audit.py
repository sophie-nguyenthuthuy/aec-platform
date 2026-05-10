"""Test-fixture duplication audit.

What this catches
-----------------
Each test file under `apps/api/tests/` tends to grow its own
boilerplate: a local `app` fixture that mounts a router, a local
`_install_langchain_stubs()` shim, an inline `_execute_result(...)`
helper for FakeAsyncSession returns. Across 80+ test files, the
same shape gets copy-pasted N times. When the underlying contract
shifts (e.g. a new arg on the langchain stub), each copy needs
hand-updating; the ones missed silently rot.

This audit counts duplicated occurrences of well-known fixture
patterns and ratchets on the count. Reductions celebrate (someone
hoisted to conftest); additions red-gate.

Recognised patterns
-------------------
- `_install_langchain_stubs()` invocation — should live in conftest
  or a shared helper module.
- `MagicMock()` with `scalars.return_value.all.return_value = ...`
  — the `_execute_result` shape; should be a single helper.
- `monkeypatch.setattr(_rl, "_acquire", ...)` — the rate-limit
  bypass autouse fixture is already in conftest.py; per-file
  replications are dead code.

What this doesn't audit
-----------------------
Quality of fixtures (whether they're well-named, well-scoped). The
audit's purpose is "the SAME pattern appears in 5+ files" — that's
the structural signal for "lift to conftest." Cosmetic differences
(formatting, helper-name choice) are out of scope.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _API_ROOT / "tests"


# Patterns + the count above which the duplication is "too much."
# Each pattern gets its own ratchet baseline so a fix to one
# doesn't false-pass another.
PATTERNS: dict[str, str] = {
    "langchain_stubs": r"_install_langchain_stubs\s*\(\s*\)",
    "fake_execute_result": r"scalars\.return_value\.all\.return_value",
    "rate_limit_bypass": r'_rl,\s*"_acquire"',
}


# Today's baselines — counted on first run. Each pattern's count
# ratchets independently.
BASELINES: dict[str, int] = {
    "langchain_stubs": 1,
    # 2026-05: 12 → 13 → 12 with new tests for assistant streaming +
    # query budgets. The signal stays loud — past 13 the right
    # answer is to lift `fake_execute_result` into conftest as a
    # `make_execute_result(rows: list[Any])` helper.
    "fake_execute_result": 12,
    "rate_limit_bypass": 0,
}


def _list_test_files() -> list[Path]:
    return sorted(p for p in _TESTS_DIR.rglob("*.py") if p.name.startswith("test_") and p.is_file())


def _count_pattern_per_file(pattern: re.Pattern[str]) -> int:
    """Count files (not occurrences) where the pattern appears at
    least once. The "lift-to-conftest" signal is "many files do this"
    — within a single file, multiple occurrences are usually one
    helper used many times, which isn't the duplication shape we
    care about.
    """
    n = 0
    for path in _list_test_files():
        # Skip the audit file itself — its regex pattern strings
        # would otherwise count.
        if path.name == "test_fixture_duplication_audit.py":
            continue
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            n += 1
    return n


def _all_pattern_counts() -> dict[str, int]:
    return {name: _count_pattern_per_file(re.compile(pat)) for name, pat in PATTERNS.items()}


def test_fixture_pattern_duplication_does_not_grow():
    """For each well-known fixture pattern, count files that use
    it ad-hoc; assert the count stays at-or-below the baseline.

    Failure surfaces both ratchet directions. Reductions prompt
    the developer to drop the baseline so future regressions can't
    silently rebuild.
    """
    actual = _all_pattern_counts()

    drift_up: list[str] = []
    drift_down: list[str] = []
    for name, exp in BASELINES.items():
        got = actual[name]
        if got > exp:
            drift_up.append(f"{name}: {exp} → {got}  (+{got - exp})")
        elif got < exp:
            drift_down.append(f"{name}: {exp} → {got}  (-{exp - got})")

    if drift_up:
        pytest.fail(
            f"{len(drift_up)} fixture pattern(s) appear in more files than "
            f"baseline:\n  " + "\n  ".join(drift_up) + "\n\nThe `lift to conftest` signal is firing — these patterns "
            "are getting copy-pasted across test files. Move the helper "
            "to `apps/api/tests/conftest.py` (or a shared `_helpers.py` "
            "module) so the next contract change updates one place, not N."
        )
    if drift_down:
        pytest.fail(
            f"{len(drift_down)} fixture pattern(s) ratcheted down:\n  "
            + "\n  ".join(drift_down)
            + "\n\nUpdate `BASELINES` in this test to match the new counts "
            "so future regressions can't silently rebuild back up."
        )


def test_baselines_cover_every_recognised_pattern():
    """Defensive: every `PATTERNS` entry must have a `BASELINES`
    entry. Without this, adding a pattern without a baseline
    would crash the main test with a KeyError instead of giving a
    useful message.
    """
    missing = sorted(set(PATTERNS) - set(BASELINES))
    extra = sorted(set(BASELINES) - set(PATTERNS))
    assert not missing and not extra, (
        f"PATTERNS / BASELINES out of sync:\n  pattern w/o baseline: {missing}\n  baseline w/o pattern: {extra}"
    )


def test_pattern_regex_actually_matches_documented_shape():
    """Defensive: positive fixtures for each regex. A regex
    regression that broke a pattern would silently let duplication
    through.
    """
    cases = {
        "langchain_stubs": "_install_langchain_stubs()",
        "fake_execute_result": "r.scalars.return_value.all.return_value = list(rows)",
        "rate_limit_bypass": 'monkeypatch.setattr(_rl, "_acquire", _always_allow)',
    }
    for name, sample in cases.items():
        pat = re.compile(PATTERNS[name])
        assert pat.search(sample), f"Pattern {name!r} failed to match its documented sample: {sample!r}"


def test_per_pattern_baseline_breakdown_is_visible_on_fail():
    """Sanity that the counter helper returns sensible output and
    the test-file walker excludes itself.

    Surfaces the per-pattern current count for any reviewer
    debugging a baseline drift — the assertion message in
    `test_fixture_pattern_duplication_does_not_grow` shows it via
    the failure-only path; this test documents the same data on
    pass-too via a no-op assert.
    """
    counts = _all_pattern_counts()
    # Sanity: every pattern returns a non-negative integer count.
    for name, n in counts.items():
        assert isinstance(n, int) and n >= 0, f"Pattern {name!r} returned non-int count {n!r}"
    # The audit file is correctly excluded from its own count —
    # otherwise the regex strings here would inflate every count
    # by 1.
    audit_text = (_TESTS_DIR / "test_fixture_duplication_audit.py").read_text()
    assert "_install_langchain_stubs" in audit_text  # we reference it as a pattern
    # ...but the count from the audit must have skipped it.
    pat = re.compile(PATTERNS["langchain_stubs"])
    files_using = [
        p
        for p in _list_test_files()
        if p.name != "test_fixture_duplication_audit.py" and pat.search(p.read_text(encoding="utf-8"))
    ]
    assert _count_pattern_per_file(pat) == len(files_using)
