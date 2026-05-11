"""CI ↔ pre-commit drift audit.

The bug class
-------------
Pre-commit pins ruff at v0.15.12; `apps/api/requirements-dev.txt`
pins ruff==0.15.12; `.github/workflows/ci.yml` runs `ruff check` from
that requirements file. If the three drift — local pre-commit at
v0.16, CI at v0.15 — local "fixes" land that CI still rejects, OR
worse, local rejects what CI accepts. The fix-cycle wastes a round
trip; the worst-case outcome is "passes locally, red CI" or "passes
CI, red locally" with the same code and the team thrashing trying
to figure out which truth wins.

What this audit checks
----------------------
1. **ruff version equality**: `.pre-commit-config.yaml::rev: vX.Y.Z`
   for `ruff-pre-commit` matches `ruff==X.Y.Z` in
   `apps/api/requirements-dev.txt`.

2. **Hook ↔ CI step pairing**: every pre-commit hook ID either
   appears in `ci.yml` (so CI re-runs the same gate) or is on an
   allowlist with a stated reason. Reverse: every CI gate that
   pre-commit COULD run (ruff, ruff-format, prettier, JSON/YAML
   parsing) but doesn't is documented.

What's intentionally CI-only
----------------------------
- `pnpm -r typecheck` — 10-30s, blocks every commit. Run pre-push
  by `make hooks` if needed.
- `pnpm -r lint` — same.
- `pytest` — minutes; pre-commit would be unusable.
- `next build` — minutes.

Each of these is on the CI_ONLY_ALLOWLIST below with a reason.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRECOMMIT = _REPO_ROOT / ".pre-commit-config.yaml"
_CI_DIR = _REPO_ROOT / ".github" / "workflows"
_API_REQS_DEV = _REPO_ROOT / "apps" / "api" / "requirements-dev.txt"


# CI gates we deliberately skip in pre-commit. Each entry: gate name
# → reason it's CI-only. An empty reason turns the allowlist into a
# silencing mechanism; reviewers should be able to read each line
# and agree that "yes, this is genuinely too expensive to run on
# every commit."
CI_ONLY_ALLOWLIST: dict[str, str] = {
    "typecheck": "10-30s; pre-commit on every commit would be unusable",
    "pnpm -r typecheck": "10-30s; pre-commit on every commit would be unusable",
    "pnpm -r lint": "alias of typecheck for the JS workspaces",
    "pytest": "minutes; pre-commit would be unusable",
    "next build": "minutes; pre-commit would be unusable",
    "playwright": "browser install + browser tests, multi-minute",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ruff_version_in_precommit() -> str | None:
    """Parse `.pre-commit-config.yaml` for the ruff-pre-commit `rev`.

    Format:
        - repo: https://github.com/astral-sh/ruff-pre-commit
          rev: v0.15.12

    We extract the version string (with leading `v` stripped)."""
    text = _read(_PRECOMMIT)
    # Find the ruff-pre-commit block; capture the rev: line that
    # follows it within the same hook entry.
    block_re = re.compile(
        r"-\s*repo:\s*https://github\.com/astral-sh/ruff-pre-commit\s*\n"
        r"\s*rev:\s*v?([\d.]+)",
        re.MULTILINE,
    )
    m = block_re.search(text)
    if not m:
        return None
    return m.group(1)


def _ruff_version_in_requirements() -> str | None:
    """Parse `apps/api/requirements-dev.txt` for `ruff==X.Y.Z`."""
    text = _read(_API_REQS_DEV)
    m = re.search(r"^\s*ruff==([\d.]+)\s*$", text, re.MULTILINE)
    return m.group(1) if m else None


def test_ruff_version_pin_matches_between_precommit_and_requirements():
    """If these drift, the local pre-commit auto-fix lands code that
    CI still rejects (or vice versa). The fix is to bump both pins
    in lockstep — call out both files in any ruff-version-bump PR.
    """
    pre = _ruff_version_in_precommit()
    req = _ruff_version_in_requirements()
    assert pre is not None, (
        "Couldn't extract ruff `rev:` from .pre-commit-config.yaml — "
        "the regex may be out of date with the file's structure."
    )
    assert req is not None, "Couldn't extract `ruff==` pin from apps/api/requirements-dev.txt"
    assert pre == req, (
        f"ruff version drift: pre-commit pins v{pre}, requirements-dev "
        f"pins {req}.\n\n"
        f"Bump both in the same PR — the file with the older pin is the "
        f"truth nobody enforced. Update:\n"
        f"  • .pre-commit-config.yaml::rev for ruff-pre-commit\n"
        f"  • apps/api/requirements-dev.txt::ruff=={pre}\n\n"
        f"And run `pre-commit autoupdate` locally to refresh the cached "
        f"venv."
    )


def _precommit_hook_ids() -> list[str]:
    """Every `id:` line under a `hooks:` block in pre-commit config."""
    text = _read(_PRECOMMIT)
    return [m.group(1) for m in re.finditer(r"^\s*-\s*id:\s*([\w-]+)", text, re.MULTILINE)]


def _ci_step_text() -> str:
    """Concatenate every workflow YAML's text — the audit's
    "is X mentioned anywhere in CI" check is content-only.
    """
    return "\n".join(_read(p) for p in sorted(_CI_DIR.glob("*.yml")))


def test_every_precommit_hook_runs_in_ci_or_is_allowlisted():
    """For each hook ID in pre-commit, assert either:
      * The ID (or its underlying tool name) appears in some CI
        workflow file, OR
      * The hook is on a documented exemption.

    Exemptions: hooks that are purely local-only quality-of-life
    checks (e.g. `detect-private-key` is a guard against accidental
    secret commits — by the time CI sees the commit, the secret is
    already in git history). Today no such exemption exists; the
    audit should fire if a future PR adds a local-only hook without
    documenting why CI doesn't also run it.
    """
    hook_ids = _precommit_hook_ids()
    ci_text = _ci_step_text()

    # Map of "hook ID → CI search term" for hooks whose CI invocation
    # uses a different name. E.g. pre-commit hook `ruff` corresponds
    # to CI step `ruff check`. Without this aliasing the test would
    # false-positive on legitimate matches.
    HOOK_TO_CI_TERM = {
        "ruff": "ruff check",
        "ruff-format": "ruff format",
        "trailing-whitespace": "pre-commit/action",  # CI runs hooks themselves
        "end-of-file-fixer": "pre-commit/action",
        "check-yaml": "pre-commit/action",
        "check-toml": "pre-commit/action",
        "check-json": "pre-commit/action",
        "check-merge-conflict": "pre-commit/action",
        "check-added-large-files": "pre-commit/action",
        "detect-private-key": "pre-commit/action",
        # The hook runs `pytest tests/test_codeguard_surface_snapshot.py`
        # locally; CI's broader `pytest --integration -q` step picks it
        # up because `tests/` is in scope. Search for the pytest
        # invocation rather than the snapshot file name (which CI
        # doesn't reference by name).
        "codeguard-surface-snapshot": "Pytest",
        # Same shape as codeguard-surface-snapshot. The hook runs
        # `pytest tests/ -k audit`; CI's `pytest -q` step picks up
        # every `test_*_audit.py` because `tests/` is in scope.
        "ratchet-audits": "Pytest",
    }

    missing: list[str] = []
    for hid in hook_ids:
        term = HOOK_TO_CI_TERM.get(hid, hid)
        if term not in ci_text:
            missing.append(f"{hid} (searched for {term!r} in workflows)")

    assert not missing, (
        f"{len(missing)} pre-commit hook(s) don't run in CI:\n  "
        + "\n  ".join(missing)
        + "\n\nEither add a CI step that runs the hook (or its underlying "
        "tool), or update HOOK_TO_CI_TERM in this test if the CI step uses "
        "a different name. If a hook is genuinely local-only (e.g. an "
        "auto-formatter where CI runs the check-only mode under a "
        "different name), document the divergence in HOOK_TO_CI_TERM."
    )


def test_ci_only_allowlist_entries_actually_appear_in_ci():
    """Defensive: every CI_ONLY_ALLOWLIST entry must be findable
    somewhere in the workflows. If the entry no longer appears,
    delete it from the allowlist — keeping stale entries hides a
    real "we removed the gate" regression.
    """
    ci_text = _ci_step_text()
    stale = [name for name in CI_ONLY_ALLOWLIST if name not in ci_text]
    assert not stale, (
        f"{len(stale)} CI_ONLY_ALLOWLIST entries no longer appear in any "
        f"workflow:\n  " + "\n  ".join(stale) + "\nIf the gate was intentionally removed, drop the allowlist "
        "entry. If the gate was renamed, update the allowlist key."
    )


def test_pre_commit_config_is_well_formed():
    """Defensive sanity: the YAML parses and has at least one repo.
    Without this, a syntax-broken pre-commit config would silently
    skip all hooks (pre-commit's behaviour on parse error is to
    proceed with the cached old config).
    """
    import yaml

    config = yaml.safe_load(_read(_PRECOMMIT))
    assert isinstance(config, dict) and "repos" in config, "pre-commit config doesn't parse as a dict with `repos` key"
    assert len(config["repos"]) >= 2, (
        f"pre-commit config has only {len(config['repos'])} repo(s); "
        "expected at least 2 (ruff + general-hygiene at minimum). "
        "Did a recent edit accidentally truncate the file?"
    )
