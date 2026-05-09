"""Unit tests for `scripts/validate_prometheus_rules.py`.

The validator's job is to catch alert-rule rot — a rule referencing
a renamed/missing metric, an out-of-vocabulary severity, a malformed
`for:` duration. Pin each failure mode against a synthetic YAML so
a refactor of the validator can't silently start passing rules it
should reject.

Loads the script as a module via importlib (mirrors the pattern
used by `apps/ml/tests/test_codeguard_quotas_cli.py` for
`scripts/codeguard_quotas.py`).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "validate_prometheus_rules.py"
_spec = importlib.util.spec_from_file_location("validate_prometheus_rules", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
val = importlib.util.module_from_spec(_spec)
sys.modules["validate_prometheus_rules"] = val
_spec.loader.exec_module(val)


def _write_rule_file(tmp_path: Path, content: str) -> Path:
    """Drop a synthetic rules YAML into a temp dir + return its path."""
    f = tmp_path / "test.alerts.yml"
    f.write_text(content, encoding="utf-8")
    return f


def test_passes_a_well_formed_rule(tmp_path):
    """Standard happy path. Reference a metric that's actually in the
    registry (`codeguard_quota_429_total` is registered at module
    import) so the metric-name check resolves cleanly."""
    f = _write_rule_file(
        tmp_path,
        """
groups:
  - name: test
    rules:
      - alert: TestAlert
        expr: sum(rate(codeguard_quota_429_total[5m])) > 0
        for: 5m
        labels:
          severity: warn
        annotations:
          summary: "test"
""",
    )
    registry = val._load_metric_registry()
    errors = val.validate_file(f, registry)
    assert errors == []


def test_rejects_unknown_metric_name(tmp_path):
    """The load-bearing check: a rule that references a metric not
    in the registry. This is the regression class the validator
    exists to catch — a renamed metric whose alert wasn't updated
    would silently never fire in production."""
    f = _write_rule_file(
        tmp_path,
        """
groups:
  - name: test
    rules:
      - alert: BadMetricRef
        expr: sum(rate(codeguard_quota_renamed_total[5m])) > 0
        for: 5m
        labels:
          severity: warn
        annotations:
          summary: "test"
""",
    )
    registry = val._load_metric_registry()
    errors = val.validate_file(f, registry)
    assert any("codeguard_quota_renamed_total" in e for e in errors), (
        f"Expected unknown-metric error to mention the missing name. Got: {errors!r}"
    )


def test_rejects_invalid_for_duration(tmp_path):
    """`for: 5ms` is a typo (we never alert on sub-second windows).
    `for: 5min` is wrong syntax. Both must fail."""
    f = _write_rule_file(
        tmp_path,
        """
groups:
  - name: test
    rules:
      - alert: BadDurationMs
        expr: codeguard_quota_429_total > 0
        for: 5ms
        labels:
          severity: warn
        annotations:
          summary: "test"
      - alert: BadDurationMin
        expr: codeguard_quota_429_total > 0
        for: 5min
        labels:
          severity: warn
        annotations:
          summary: "test"
""",
    )
    registry = val._load_metric_registry()
    errors = val.validate_file(f, registry)
    assert sum(1 for e in errors if "invalid `for:" in e) == 2, f"Expected exactly 2 duration errors; got: {errors!r}"


def test_rejects_unknown_severity(tmp_path):
    """Severity vocabulary is closed at {warn, page}. A typo like
    `severity: warning` (instead of `warn`) would otherwise sail
    through and break alertmanager routing silently."""
    f = _write_rule_file(
        tmp_path,
        """
groups:
  - name: test
    rules:
      - alert: BadSeverity
        expr: codeguard_quota_429_total > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "test"
""",
    )
    registry = val._load_metric_registry()
    errors = val.validate_file(f, registry)
    assert any("severity=" in e and "warning" in e for e in errors), (
        f"Expected severity-vocabulary error. Got: {errors!r}"
    )


def test_rejects_missing_required_keys(tmp_path):
    """A rule with `alert:` but no `expr:` / `for:` / `labels:` /
    `annotations:` is malformed. Pin so a partially-written rule
    can't slip through CI."""
    f = _write_rule_file(
        tmp_path,
        """
groups:
  - name: test
    rules:
      - alert: Incomplete
        for: 5m
""",
    )
    registry = val._load_metric_registry()
    errors = val.validate_file(f, registry)
    # Should flag at least `expr`, `labels`, `annotations` as missing.
    assert any("missing `expr`" in e for e in errors)
    assert any("missing `labels`" in e for e in errors)
    assert any("missing `annotations`" in e for e in errors)


def test_passes_histogram_quantile_referencing_bucket_suffix(tmp_path):
    """Histograms expose `<name>_bucket` / `<name>_sum` / `<name>_count`
    at scrape time. The registry only carries the base name; the
    validator must add the suffixed variants automatically so an
    alert using `histogram_quantile(0.99, ..._bucket)` validates
    cleanly. Pin via the real cap-check histogram + a real PromQL
    quantile query."""
    f = _write_rule_file(
        tmp_path,
        """
groups:
  - name: test
    rules:
      - alert: SlowCapCheck
        expr: |
          histogram_quantile(0.99,
            sum by (le) (rate(codeguard_quota_check_duration_seconds_bucket[5m]))
          ) > 0.1
        for: 5m
        labels:
          severity: warn
        annotations:
          summary: "test"
""",
    )
    registry = val._load_metric_registry()
    errors = val.validate_file(f, registry)
    assert errors == [], (
        f"Histogram bucket suffix should resolve via the registry's "
        f"automatic _bucket/_sum/_count expansion. Got: {errors!r}"
    )


def test_ignores_recording_rules(tmp_path):
    """Recording rules (`record:` instead of `alert:`) use a
    different shape — no `for:`, no `labels.severity`, no
    `annotations` required. The validator must skip them rather
    than flagging every recording rule as malformed."""
    f = _write_rule_file(
        tmp_path,
        """
groups:
  - name: test
    rules:
      - record: codeguard_quota_429_per_min
        expr: sum(rate(codeguard_quota_429_total[1m]))
""",
    )
    registry = val._load_metric_registry()
    errors = val.validate_file(f, registry)
    assert errors == []


def test_main_returns_zero_for_valid_file(tmp_path, capsys):
    """End-to-end: invoke `main()` against a valid file. Exit 0,
    success message on stdout. Mirrors what CI sees."""
    f = _write_rule_file(
        tmp_path,
        """
groups:
  - name: test
    rules:
      - alert: TestAlert
        expr: codeguard_quota_429_total > 0
        for: 5m
        labels:
          severity: warn
        annotations:
          summary: "test"
""",
    )
    rc = val.main([str(f)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out


def test_main_returns_one_for_invalid_file(tmp_path, capsys):
    """End-to-end: invoke `main()` against an invalid file. Exit 1,
    error message on stderr."""
    f = _write_rule_file(
        tmp_path,
        """
groups:
  - name: test
    rules:
      - alert: BadMetric
        expr: codeguard_does_not_exist > 0
        for: 5m
        labels:
          severity: warn
        annotations:
          summary: "test"
""",
    )
    rc = val.main([str(f)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "codeguard_does_not_exist" in captured.err


@pytest.mark.parametrize(
    "duration, valid",
    [
        ("5m", True),
        ("2h", True),
        ("14d", True),
        ("30s", True),
        ("1d12h", True),  # compound
        ("5ms", False),  # sub-second — rejected as a typo
        ("5min", False),
        ("forever", False),
        ("", False),
    ],
)
def test_for_duration_grammar(duration, valid):
    """Sweep the duration grammar — `\\d+[smhdwy]` plus compounds.
    Pinning each case so a refactor of the regex can't silently
    start accepting `5ms` (which is the documented "this is a typo"
    rejection case)."""
    matched = bool(val._DURATION_RE.match(duration))
    assert matched == valid, f"Duration {duration!r}: expected valid={valid}, got match={matched}"
