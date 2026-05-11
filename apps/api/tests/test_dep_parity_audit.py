"""Cross-service Python dependency parity audit.

The bug class
-------------
`apps/api/requirements.txt` pins `pydantic==2.13.3`. The arq worker
inherits the api's deps (same containers in some setups) but
`apps/worker/requirements.txt` pins `pydantic==2.9.2`. The api's
Pydantic models serialize one way; the worker's deserialize a
different way. Subtle wire-format bugs across the service boundary
that only surface in production.

What this audit checks
----------------------
For every Python package that appears in 2+ of the requirements
files across the repo:

  * `apps/api/requirements.txt`
  * `apps/api/requirements-dev.txt`
  * `apps/worker/requirements.txt`
  * `apps/ml/requirements.txt`
  * `apps/ml/serve/requirements.txt`

assert all instances pin the SAME version. Allowlist for legitimately-
divergent packages (e.g. a worker-side pin that intentionally lags
because of a known incompatibility with a worker dependency).

Implementation
--------------
Plain text parsing — `name==version` per line, ignoring comments,
blank lines, `-r` includes. Same shape as our other ratchet audits:
baseline pinned at the current divergence count, ratchets down as
each gets reconciled.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


# Files to scan. Each entry: path-from-repo-root → label for failure
# messages. Add new requirement files here as services are added.
_REQUIREMENTS_FILES = [
    "apps/api/requirements.txt",
    "apps/api/requirements-dev.txt",
    "apps/worker/requirements.txt",
    "apps/ml/requirements.txt",
    "apps/ml/serve/requirements.txt",
]


# Allowlist for legitimately-divergent packages. Format:
# (package_name) → reason. Each entry needs a stated rationale —
# an empty reason silences the gate. We don't track per-pair
# reasons because the bug class we're guarding against is the
# same regardless of which two files diverge: cross-service wire-
# format drift.
ALLOWLIST: dict[str, str] = {
    # No entries today. Add lazily as legitimate divergences surface.
}


# Today's baseline. Captured on first run; ratchet down as each
# divergence is reconciled.
BASELINE_DIVERGENT_PINS = 2


# `name==version` line. Tolerates extras (`sqlalchemy[asyncio]==X`)
# and trailing comments. Ignores blank lines, `# comment` lines,
# `-r reqs.txt` includes.
_PIN_RE = re.compile(r"^\s*([a-zA-Z0-9][a-zA-Z0-9._-]*)(\[[^\]]+\])?==([^\s#]+)\s*(?:#.*)?$")


def _parse_requirements(path: Path) -> dict[str, str]:
    """Return {package_name: pinned_version} from a requirements file.

    Names are lowercased + hyphens-vs-underscores normalised so
    `psycopg2-binary` and `psycopg2_binary` are treated as one. The
    extras suffix (`[asyncio]`) is stripped; we compare the base
    package version regardless of which extras each file requests.
    """
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _PIN_RE.match(line)
        if not m:
            continue
        name = m.group(1).lower().replace("_", "-")
        version = m.group(3)
        out[name] = version
    return out


def _collect_pins() -> dict[str, dict[str, str]]:
    """Build {package: {file_label: version}} across every reqs file."""
    pkg_pins: dict[str, dict[str, str]] = defaultdict(dict)
    for relpath in _REQUIREMENTS_FILES:
        path = _REPO_ROOT / relpath
        if not path.exists():
            continue
        for pkg, ver in _parse_requirements(path).items():
            pkg_pins[pkg][relpath] = ver
    return pkg_pins


def test_every_shared_package_pins_the_same_version_across_services():
    """For each package that appears in 2+ requirements files, assert
    every file pins the same version (or the package is on
    ALLOWLIST).

    A drift surfaces both ratchet directions — additions red-gate,
    reductions celebrate + prompt to lower the baseline.
    """
    pkg_pins = _collect_pins()
    assert pkg_pins, "no requirements files found — the auditor's path resolution is broken"

    divergent: list[str] = []
    for pkg, pins in sorted(pkg_pins.items()):
        if pkg in ALLOWLIST:
            continue
        if len(pins) < 2:
            continue  # only in one file → nothing to compare
        unique_versions = set(pins.values())
        if len(unique_versions) > 1:
            # Format the failure: package name + each file → version.
            lines = "\n      ".join(f"{f}: {v}" for f, v in sorted(pins.items()))
            divergent.append(f"{pkg}:\n      {lines}")

    n = len(divergent)
    if n > BASELINE_DIVERGENT_PINS:
        new = n - BASELINE_DIVERGENT_PINS
        pytest.fail(
            f"{new} new package(s) with divergent pins across services "
            f"(total now {n}, baseline {BASELINE_DIVERGENT_PINS}):\n  "
            + "\n  ".join(divergent[:10])
            + (f"\n  … and {n - 10} more" if n > 10 else "")
            + "\n\nReconcile the pins to a single version, OR add the "
            "package to ALLOWLIST with a stated reason. Cross-service "
            "drift on shared deps (pydantic, sqlalchemy, httpx) causes "
            "wire-format bugs at the service boundary that only surface "
            "in production."
        )
    if n < BASELINE_DIVERGENT_PINS:
        pytest.fail(
            f"Divergent-pin count dropped from {BASELINE_DIVERGENT_PINS} "
            f"to {n}. 🎉 Update `BASELINE_DIVERGENT_PINS` to {n}."
        )


def test_allowlist_entries_actually_appear_somewhere():
    """Defensive: every ALLOWLIST entry must correspond to a real
    package in some requirements file. Stale entries silently mask
    future regressions on the renamed-or-removed package."""
    pkg_pins = _collect_pins()
    stale = [pkg for pkg in ALLOWLIST if pkg not in pkg_pins]
    assert not stale, (
        f"ALLOWLIST has stale entries: {stale}. Remove them so the allowlist reflects only currently-live exemptions."
    )


def test_pin_regex_handles_documented_formats():
    """Defensive: positive + negative fixtures for the line parser.
    A regression that broke the regex (e.g. failed to handle the
    extras-bracket form) would silently miss real pins."""
    cases = {
        "fastapi==0.115.0": ("fastapi", "0.115.0"),
        "sqlalchemy[asyncio]==2.0.35": ("sqlalchemy", "2.0.35"),
        "psycopg2-binary==2.9.9": ("psycopg2-binary", "2.9.9"),
        "pyjwt==2.9.0  # core JWT lib": ("pyjwt", "2.9.0"),
        "uvicorn[standard]==0.30.6": ("uvicorn", "0.30.6"),
    }
    for line, expected in cases.items():
        m = _PIN_RE.match(line)
        assert m is not None, f"regex failed to parse {line!r}"
        name = m.group(1).lower().replace("_", "-")
        version = m.group(3)
        assert (name, version) == expected, f"parsed {line!r} as ({name!r}, {version!r}); expected {expected!r}"

    # Non-pin shapes that must NOT match.
    for line in [
        "# fastapi==0.115.0  (commented out)",
        "-r requirements.txt",
        "fastapi>=0.110.0,<0.120.0",  # range pin, not strict ==
        "git+https://github.com/foo/bar.git@abc",
        "",
    ]:
        assert _PIN_RE.match(line) is None, f"regex incorrectly matched {line!r}"
