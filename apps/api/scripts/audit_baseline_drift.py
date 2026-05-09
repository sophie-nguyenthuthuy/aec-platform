"""Compare audit baselines between two git refs and emit a markdown report.

Use case
--------
PR review: a reviewer wants to see at a glance which ratchet
baselines moved on this branch vs `main`. Each `tests/test_*_audit.py`
declares one or more `BASELINE_*` constants; this script parses
those out of both refs and tabulates the deltas.

Usage
-----
    python -m scripts.audit_baseline_drift                  # main → HEAD
    python -m scripts.audit_baseline_drift --base origin/main
    python -m scripts.audit_baseline_drift --head 6013faa
    python -m scripts.audit_baseline_drift --output drift.md

Output shape
------------
A markdown table with one row per `(audit, constant)` pair where
the value differs between the two refs:

    | Audit | Constant | main | HEAD | Δ |
    | --- | --- | --- | --- | --- |
    | pydantic_strictness | BASELINE_NON_STRICT_COUNT | 300 | 320 | **+20** |
    | tenant_predicate | BASELINE_TENANT_LEAK | 107 | 113 | **+6** |
    | …

Plus a summary line: "N audits drifted, +X total / -Y total."

The script does NOT execute the audits — it parses the literal RHS
of the `BASELINE_*` assignments via AST. Hermetic, no FastAPI/
SQLAlchemy load. Runs in <1s for a typical 50-audit suite.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _list_audit_files_at_ref(ref: str) -> list[str]:
    """Return relative paths of every `tests/test_*_audit.py` at
    the given git ref."""
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "apps/api/tests/"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=True,
    ).stdout
    return [
        line
        for line in out.splitlines()
        if re.match(r"apps/api/tests/test_.+_audit\.py$", line)
    ]


def _read_file_at_ref(ref: str, rel_path: str) -> str | None:
    """`git show <ref>:<path>`. Returns None if the file doesn't
    exist at that ref."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel_path}"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_baselines(source: str) -> dict[str, int | str]:
    """Return `{constant_name: value}` for every module-level
    `BASELINE_*` assignment.

    Values are returned as `int` when the RHS is an int literal,
    else as the unparsed string (best-effort — keeps the script
    robust against future non-integer baselines).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: dict[str, int | str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not name.startswith("BASELINE_"):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            out[name] = value.value
        else:
            try:
                out[name] = ast.unparse(value)
            except Exception:  # noqa: BLE001
                out[name] = "<unparseable>"
    return out


def _audit_short_name(rel_path: str) -> str:
    """`apps/api/tests/test_cron_mutex_audit.py` → `cron_mutex`."""
    name = Path(rel_path).stem
    return name.removeprefix("test_").removesuffix("_audit")


def _collect(ref: str) -> dict[str, dict[str, int | str]]:
    """`{audit_short_name: {constant: value}}` for every audit at
    the ref."""
    out: dict[str, dict[str, int | str]] = {}
    for rel in _list_audit_files_at_ref(ref):
        source = _read_file_at_ref(ref, rel)
        if source is None:
            continue
        baselines = _parse_baselines(source)
        if baselines:
            out[_audit_short_name(rel)] = baselines
    return out


def _format_delta(base_val: int | str | None, head_val: int | str | None) -> str:
    """Format a markdown cell for the delta column."""
    if base_val is None:
        return "**+new**"
    if head_val is None:
        return "**removed**"
    if isinstance(base_val, int) and isinstance(head_val, int):
        delta = head_val - base_val
        if delta == 0:
            return "0"
        return f"**{'+' if delta > 0 else ''}{delta}**"
    if base_val == head_val:
        return "0"
    return "≠"


def _render(
    base_data: dict[str, dict[str, int | str]],
    head_data: dict[str, dict[str, int | str]],
    base_ref: str,
    head_ref: str,
) -> str:
    """Render the markdown report. Includes only rows that differ."""
    rows: list[tuple[str, str, str, str, str]] = []
    int_drift_total = 0  # signed sum of integer deltas

    audits = sorted(set(base_data) | set(head_data))
    for audit in audits:
        base_b = base_data.get(audit, {})
        head_b = head_data.get(audit, {})
        constants = sorted(set(base_b) | set(head_b))
        for const in constants:
            base_v = base_b.get(const)
            head_v = head_b.get(const)
            if base_v == head_v:
                continue
            rows.append(
                (
                    audit,
                    const,
                    "—" if base_v is None else str(base_v),
                    "—" if head_v is None else str(head_v),
                    _format_delta(base_v, head_v),
                )
            )
            if isinstance(base_v, int) and isinstance(head_v, int):
                int_drift_total += head_v - base_v

    parts: list[str] = []
    parts.append("# Audit baseline drift\n")
    parts.append(
        f"Comparing **`{base_ref}`** → **`{head_ref}`**. Generated by "
        "`make audit-drift` (script: `apps/api/scripts/audit_baseline_drift.py`).\n"
    )
    if not rows:
        parts.append("✅ No audit baselines drifted between the two refs.\n")
        return "\n".join(parts)

    new_audits = sorted(set(head_data) - set(base_data))
    removed_audits = sorted(set(base_data) - set(head_data))
    parts.append(
        f"**{len(rows)} baseline(s) drifted** across "
        f"{len({r[0] for r in rows})} audit(s). "
        f"Net integer Δ: {'+' if int_drift_total >= 0 else ''}"
        f"{int_drift_total}.\n"
    )
    if new_audits:
        parts.append(
            f"**{len(new_audits)} new audit(s) on HEAD**: "
            + ", ".join(f"`{a}`" for a in new_audits)
            + "\n"
        )
    if removed_audits:
        parts.append(
            f"**{len(removed_audits)} audit(s) removed on HEAD**: "
            + ", ".join(f"`{a}`" for a in removed_audits)
            + "\n"
        )

    parts.append("| Audit | Constant | Base | HEAD | Δ |")
    parts.append("| --- | --- | --- | --- | --- |")
    for audit, const, base_v, head_v, delta in rows:
        parts.append(f"| `{audit}` | `{const}` | {base_v} | {head_v} | {delta} |")
    parts.append("")
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="main", help="git ref for the baseline (default: main)")
    parser.add_argument("--head", default="HEAD", help="git ref for the head (default: HEAD)")
    parser.add_argument(
        "--output",
        default=None,
        help="write report to this path (default: stdout)",
    )
    args = parser.parse_args()

    base_data = _collect(args.base)
    head_data = _collect(args.head)
    report = _render(base_data, head_data, args.base, args.head)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
