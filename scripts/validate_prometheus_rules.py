#!/usr/bin/env python3
"""Validate Prometheus alert-rule files.

Run as a CI gate to catch the kind of regression that wouldn't
surface until production Prometheus rejected a config reload:

  * YAML doesn't parse cleanly.
  * A rule is missing a load-bearing key (`alert`, `expr`, `for`,
    `labels`, `annotations`).
  * `for:` doesn't match Prometheus's duration syntax (`\\d+[smhd]`
    or compound like `1d12h`).
  * `severity` isn't one of `{warn, page}` (we want a closed
    vocabulary for routing — adding a third tier should be a
    deliberate decision, not a typo).
  * The `expr` references a metric name that doesn't exist in
    `apps/api/core/metrics.py`'s registry. Catches the regression
    where someone renames a metric in the registration site but
    forgets the alert rule still queries the old name — the alert
    would silently never fire in production.

What this DOESN'T do:

  * Full PromQL parse. `promql-parser` would be the right tool but
    pulling in a third-party Python crate for a CI gate is overkill;
    `promtool check rules` is the canonical authority — if a future
    deploy gets it bundled, the right move is to call that instead
    and deprecate this script. Until then, the metric-name check
    catches the most common regression class.
  * Cross-rule checks (e.g. "two rules can't have the same alert
    name"). Prometheus tolerates duplicate alert names within
    different groups; we don't enforce uniqueness here.

Usage:

    python scripts/validate_prometheus_rules.py infra/prometheus/*.yml

Exit codes:
    0  — every rule passes
    1  — at least one rule failed validation (errors printed to stderr)
    2  — couldn't open one of the files / unexpected I/O failure

Wired into CI as a step in the `python-api` job (see `.github/
workflows/ci.yml`); also runnable locally for fast feedback.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# `for:` durations are a small grammar: one or more `<number><unit>`
# pairs concatenated, where unit ∈ {s, m, h, d, w, y}. Prometheus also
# accepts ms, but we never use sub-second windows for alerting (the
# scrape interval makes them meaningless), so reject ms here as a
# guard rail — a rule with `for: 5ms` is a typo.
_DURATION_RE = re.compile(r"^(\d+[smhdwy])+$")

# Severity vocabulary. Adding a third tier is a deliberate decision
# that should also touch the routing in alertmanager config —
# rejecting unknown values here forces that conversation.
_ALLOWED_SEVERITIES: frozenset[str] = frozenset({"warn", "page"})

# Heuristic for "this looks like one of our metric names": the
# `aec_*` and `codeguard_*` prefixes are the only ones we own. Any
# `<prefix>_<name>` token in `expr` matching this should appear in
# the registry exported by `core/metrics.py`. PromQL functions and
# operators are filtered out separately (they don't have these
# prefixes).
_OUR_METRIC_PREFIXES: tuple[str, ...] = ("aec_", "codeguard_")


def _load_metric_registry() -> set[str]:
    """Import `core.metrics` and pull every registered metric's name.

    Histograms generate three suffixes at scrape time
    (`_bucket`/`_sum`/`_count`); add those too so an alert that
    references e.g. `histogram_quantile(0.99,
    ..._bucket)` resolves cleanly.
    """
    # Make `apps/api` importable. The script lives at repo root; CI
    # invokes it with cwd = repo root.
    repo_root = Path(__file__).resolve().parent.parent
    api_root = repo_root / "apps" / "api"
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    try:
        import core.metrics as _metrics
    except ImportError as exc:
        # If the metrics module won't import, the validator can't
        # do its job — but better to surface that as a hard CI
        # failure than to silently skip the metric-name check.
        sys.stderr.write(
            f"validate_prometheus_rules: couldn't import core.metrics ({exc}). "
            "Cannot validate metric names against the registry.\n"
        )
        sys.exit(2)

    names: set[str] = set()
    for m in _metrics._REGISTRY:
        names.add(m.name)
        # Histograms expose <name>_bucket, <name>_sum, <name>_count
        # at scrape time. The registry only carries the base name;
        # add the suffixed variants so alerts referencing them
        # validate cleanly.
        if getattr(m, "metric_type", "") == "histogram":
            names.add(f"{m.name}_bucket")
            names.add(f"{m.name}_sum")
            names.add(f"{m.name}_count")
    return names


def _extract_metric_refs(expr: str) -> set[str]:
    """Pull tokens that look like our metric names from a PromQL
    expression. Ignores PromQL functions / operators / label values
    by filtering on the `aec_` / `codeguard_` prefix."""
    # `\w+` in Python matches `[A-Za-z0-9_]+` — covers metric names.
    # Excludes punctuation that's structural in PromQL (`(`, `[`,
    # `{`, etc.) so a label-key match like `outcome="hit"` won't be
    # picked up as a metric.
    tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", expr))
    return {t for t in tokens if t.startswith(_OUR_METRIC_PREFIXES)}


def validate_file(path: Path, registry: set[str]) -> list[str]:
    """Return a list of error messages for `path`. Empty list = pass."""
    try:
        import yaml
    except ImportError:
        return [f"{path}: PyYAML not installed; can't validate"]

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: read failed ({exc})"]

    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return [f"{path}: YAML parse failed: {exc}"]

    if not isinstance(doc, dict) or "groups" not in doc:
        return [f"{path}: missing top-level `groups` key"]
    groups = doc.get("groups") or []
    if not isinstance(groups, list):
        return [f"{path}: `groups` must be a list, got {type(groups).__name__}"]

    errors: list[str] = []
    for gi, group in enumerate(groups):
        gname = group.get("name", f"<group {gi}>")
        rules = group.get("rules") or []
        for ri, rule in enumerate(rules):
            label = f"{path}:{gname}:rule[{ri}]"
            # Only validate alert rules; recording rules use a
            # different shape (`record:` instead of `alert:`).
            if "record" in rule:
                continue
            if "alert" not in rule:
                errors.append(f"{label}: missing `alert` key")
                continue
            aname = rule["alert"]
            label = f"{path}:{aname}"

            # Required fields for an alert rule.
            for required in ("expr", "for", "labels", "annotations"):
                if required not in rule:
                    errors.append(f"{label}: missing `{required}`")
            if errors and any(label in e for e in errors):
                # Don't compound errors for a malformed rule.
                continue

            # `for:` duration grammar.
            for_value = str(rule.get("for", ""))
            if not _DURATION_RE.match(for_value):
                errors.append(
                    f"{label}: invalid `for: {for_value}` — must match "
                    r"`\d+[smhdwy]` (e.g. `5m`, `2h`, `14d`)"
                )

            # Severity vocabulary.
            severity = (rule.get("labels") or {}).get("severity")
            if severity not in _ALLOWED_SEVERITIES:
                errors.append(
                    f"{label}: severity={severity!r} not in {sorted(_ALLOWED_SEVERITIES)!r}. "
                    "Adding a new tier is a deliberate decision — also update "
                    "alertmanager routing."
                )

            # Metric-name resolution: every `aec_*` / `codeguard_*`
            # token in `expr` must exist in the registry. This is the
            # check that catches the rename-metric-but-not-alert
            # regression — exactly the failure mode that would otherwise
            # only surface in production when the alert silently never fires.
            expr = str(rule.get("expr", ""))
            refs = _extract_metric_refs(expr)
            unknown = refs - registry
            if unknown:
                errors.append(
                    f"{label}: expr references unknown metric(s) "
                    f"{sorted(unknown)!r}. Either the metric was renamed "
                    "(update this rule) or the metric isn't registered "
                    "in apps/api/core/metrics.py (register it)."
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        sys.stderr.write("Usage: validate_prometheus_rules.py <path> [<path> ...]\n")
        return 2

    registry = _load_metric_registry()
    all_errors: list[str] = []
    for path_str in args:
        path = Path(path_str)
        if not path.exists():
            sys.stderr.write(f"validate_prometheus_rules: {path}: not found\n")
            return 2
        all_errors.extend(validate_file(path, registry))

    if all_errors:
        for e in all_errors:
            sys.stderr.write(f"  {e}\n")
        sys.stderr.write(f"\n{len(all_errors)} error(s) — see above.\n")
        return 1
    sys.stdout.write(f"validate_prometheus_rules: {len(args)} file(s) OK\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
