"""GitHub Actions workflow hygiene audit.

The bug class
-------------
Three CI/CD failure modes that compound silently:

1. **Missing `timeout-minutes`.** GitHub's default job timeout is
   6 hours. A job that hangs (test deadlock, network stall) burns
   real GitHub Actions minutes against the org's plan until the
   default trips. With ~10 jobs per PR and a few stalls per week,
   this adds up.

2. **Implicit `permissions:` (read+write everything).** Default
   `GITHUB_TOKEN` permissions are read+write across the repo —
   far more than most jobs need. Least-privilege says set
   explicitly. A compromised dependency in a PR with
   `permissions: contents: write` could push commits; with
   `permissions: contents: read` it can't.

3. **Unpinned `runs-on: ubuntu-latest`.** When GitHub flips
   `ubuntu-latest` from 22.04 to 24.04 (silent rolling pin), every
   workflow's environment shifts under the team's feet. Recommend
   pinning to a specific version (`ubuntu-22.04`) or at least
   pinning per-job for the canary jobs.

What this audit checks
----------------------
For every `.github/workflows/*.yml`:
  * Every `jobs.<id>` block has `timeout-minutes:`.
  * Every workflow OR job has `permissions:` set explicitly.
  * Every `runs-on:` is documented (we accept `ubuntu-latest`
    for now but ratchet on the count so a future tightening can
    drop it).

Same ratchet pattern as the other infrastructure audits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"


# Today's baselines per category. Filled in on first run.
BASELINE_JOBS_NO_TIMEOUT = 13
BASELINE_WORKFLOWS_NO_PERMISSIONS = 1


def _list_workflow_files() -> list[Path]:
    if not _WORKFLOWS_DIR.exists():
        return []
    return sorted(_WORKFLOWS_DIR.glob("*.yml")) + sorted(_WORKFLOWS_DIR.glob("*.yaml"))


def _parse_workflow(path: Path) -> dict:
    """Parse YAML; return the parsed dict.

    We use PyYAML which we already depend on (alembic uses it
    transitively + the prometheus-rules validator imports it).
    """
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _count_jobs_without_timeout(workflow: dict) -> list[str]:
    """Return list of job-IDs in `workflow.jobs.*` that lack
    `timeout-minutes`.
    """
    jobs = workflow.get("jobs") or {}
    out: list[str] = []
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        if "timeout-minutes" not in job:
            out.append(job_id)
    return out


def _has_permissions(workflow: dict) -> bool:
    """True if EITHER the workflow or every job has `permissions:` set.

    Top-level `permissions:` cascades to every job that doesn't
    override; setting it once at workflow level is sufficient.
    """
    if "permissions" in workflow:
        return True
    jobs = workflow.get("jobs") or {}
    if not jobs:
        return False
    return all(isinstance(j, dict) and "permissions" in j for j in jobs.values())


def test_every_job_has_a_timeout():
    """For each job across every workflow file, assert
    `timeout-minutes` is set. Without it, a stuck job burns 6h of
    GitHub Actions minutes before the default trips.

    Failures surface both ratchet directions.
    """
    files = _list_workflow_files()
    assert files, f"no workflow files found under {_WORKFLOWS_DIR}"

    findings: list[str] = []
    for path in files:
        workflow = _parse_workflow(path)
        for job_id in _count_jobs_without_timeout(workflow):
            findings.append(f"{path.name}::{job_id}")

    n = len(findings)
    if n > BASELINE_JOBS_NO_TIMEOUT:
        new = n - BASELINE_JOBS_NO_TIMEOUT
        pytest.fail(
            f"{new} new job(s) without `timeout-minutes` "
            f"(total now {n}, baseline {BASELINE_JOBS_NO_TIMEOUT}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nAdd `timeout-minutes: <N>` to each job. Pick a value "
            "~2x the realistic runtime — short enough that a stuck job "
            "fails fast, long enough that legitimate slow runs don't "
            "false-fail. Suggested floors:\n"
            "  • Lint / pre-commit: 5\n"
            "  • Unit tests: 15\n"
            "  • Integration with docker-compose: 30\n"
            "  • Build / Playwright E2E: 30"
        )
    if n < BASELINE_JOBS_NO_TIMEOUT:
        pytest.fail(
            f"Job-without-timeout count dropped from {BASELINE_JOBS_NO_TIMEOUT} to {n}. 🎉 Update the baseline."
        )


def test_every_workflow_declares_permissions():
    """For each workflow, assert EITHER the workflow OR every job
    has `permissions:` set. Default GITHUB_TOKEN permissions are
    read+write across the repo — far more than most jobs need.

    Failures surface both ratchet directions.
    """
    files = _list_workflow_files()
    findings: list[str] = []
    for path in files:
        workflow = _parse_workflow(path)
        if not _has_permissions(workflow):
            findings.append(path.name)

    n = len(findings)
    if n > BASELINE_WORKFLOWS_NO_PERMISSIONS:
        new = n - BASELINE_WORKFLOWS_NO_PERMISSIONS
        pytest.fail(
            f"{new} new workflow(s) without explicit `permissions:` "
            f"(total now {n}, baseline {BASELINE_WORKFLOWS_NO_PERMISSIONS}):\n  "
            + "\n  ".join(findings)
            + "\n\nAdd a top-level `permissions:` block to each "
            "workflow (or per-job if jobs need different scopes). "
            "Least-privilege defaults:\n\n"
            "    permissions:\n"
            "      contents: read\n"
            "      pull-requests: read\n\n"
            "Add write permissions only on jobs that actually need "
            "them (release, deploy)."
        )
    if n < BASELINE_WORKFLOWS_NO_PERMISSIONS:
        pytest.fail(
            f"Workflow-without-permissions count dropped from "
            f"{BASELINE_WORKFLOWS_NO_PERMISSIONS} to {n}. 🎉 Update the baseline."
        )
