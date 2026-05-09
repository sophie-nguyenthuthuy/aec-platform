"""Secret/env-var access audit.

The bug class
-------------
`core/config.py` is the authoritative settings layer. Every env
var the API reads should come through it: types are validated,
prod-only invariants are enforced (`validate_prod_settings`),
and the field shows up in `.env.example` for new contributors.

The bug fires when someone bypasses it:

    redis_url = os.environ["REDIS_URL"]   # <-- bypass

In dev with a populated `.env` the call returns the right value.
In prod with a misconfig:
  * No validation that the var is set (`KeyError` at request time
    instead of boot-time refusal).
  * No type coercion (string instead of `RedisDsn`).
  * Not visible in `.env.example`, so the next deploy forgets it.
  * Not visible in the prod-defaults check, so a dev value can
    leak through.

The fix is structural: read the value from `Settings`. The audit
walks every Python file under `apps/api/` and flags `os.environ`
/ `os.getenv` references outside the allowlist.

What this audit checks
----------------------
For every `.py` file under `apps/api/{core,db,middleware,models,
routers,schemas,services,workers}` plus `apps/worker/`:

- Direct subscript: `os.environ["KEY"]`, `os.environ['KEY']`,
  `os.environ.get("KEY")`.
- Free-function form: `os.getenv("KEY")`, `os.getenv("KEY", default)`.

Allowlist
---------
- `core/config.py` — the authoritative settings layer; obviously
  reads env vars by definition.
- Per-(file, line) entries for legitimate one-offs (e.g. a script
  that runs outside the FastAPI process and has no Settings
  instance to read from).

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


# Today's baseline. Filled in on first run; ratchet down as call
# sites migrate to `Settings`.
BASELINE_DIRECT_ENV_ACCESS = 0


# Files where direct env-var access is legitimate. Each entry
# needs a stated reason. An empty rationale silences the gate.
#
# Format: relative_posix_path → reason
_FILE_ALLOWLIST: dict[str, str] = {
    # The authoritative settings layer: this IS the abstraction
    # everyone else reads through. Cannot itself read from
    # Settings without infinite recursion.
    "apps/api/core/config.py": "the Settings layer itself",
}


# Per-(file, line-content) allowlist for one-off legitimate cases
# inside otherwise-disciplined files. Empty by design — anything
# here is a smell that should be migrated. Add lazily with reason.
_LINE_ALLOWLIST: dict[tuple[str, str], str] = {
    # No entries today.
}


# `os.environ["KEY"]`, `os.environ['KEY']`, `os.environ.get(...)`,
# `os.getenv(...)`. The word-boundary anchor stops `your_os.environ`
# from false-matching.
_ENV_ACCESS_RE = re.compile(
    r"\bos\s*\.\s*(?:environ\s*(?:\[|\.\s*get\s*\()|getenv\s*\()",
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
            if p.name == "test_secret_access_audit.py":
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
    if rel in _FILE_ALLOWLIST:
        return []
    findings: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        # Strip line comments — a `# os.environ.get("FOO")` example
        # in a docstring isn't a runtime call site.
        code_part = line.split("#", 1)[0]
        if not _ENV_ACCESS_RE.search(code_part):
            continue
        content = line.strip()
        if (rel, content) in _LINE_ALLOWLIST:
            continue
        findings.append(f"{rel}:{i}  {content[:80]}")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_direct_env_access_outside_settings():
    """Every env var should be read via `core.config.Settings`,
    not via `os.environ` / `os.getenv` directly.

    Failures surface both ratchet directions:
      * COUNT > BASELINE: a new bypass landed. Migrate the call
        site to `get_settings().<field>`. Add the field to
        `Settings` (with a default) if it doesn't exist yet.
      * COUNT < BASELINE: someone fixed one. 🎉 Update the
        baseline so future regressions can't silently rebuild back.

    The bug class: bypassing Settings means losing type validation,
    losing the prod-defaults check, losing `.env.example` visibility,
    and surfacing config errors as `KeyError` at request time
    instead of boot-time refusal.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_DIRECT_ENV_ACCESS:
        new = n - BASELINE_DIRECT_ENV_ACCESS
        pytest.fail(
            f"{new} new direct env-var access call site(s) "
            f"(total now {n}, baseline {BASELINE_DIRECT_ENV_ACCESS}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nMigrate to `Settings`:\n"
            "    # was:\n"
            "    redis_url = os.environ['REDIS_URL']\n"
            "    # use:\n"
            "    from core.config import get_settings\n"
            "    redis_url = get_settings().redis_url\n\n"
            "If `redis_url` isn't a Settings field yet, add it to "
            "`core/config.py::Settings` with a sensible default and "
            "an entry in `.env.example`. The `test_env_example_"
            "exhaustiveness.py` audit will surface the missing entry "
            "if you forget it.\n\n"
            "If a call site genuinely needs to bypass Settings (e.g. "
            "a one-shot script that runs outside the FastAPI process), "
            "add it to `_FILE_ALLOWLIST` or `_LINE_ALLOWLIST` in this "
            "test with a one-line reason."
        )
    if n < BASELINE_DIRECT_ENV_ACCESS:
        pytest.fail(
            f"Direct-env-access count dropped from "
            f"{BASELINE_DIRECT_ENV_ACCESS} to {n}. 🎉 Update "
            f"`BASELINE_DIRECT_ENV_ACCESS` to {n}."
        )


def test_audit_recognises_documented_access_shapes():
    """Defensive: positive + negative fixtures. A regression in
    the regex that broke `os.environ` matching would silently let
    every bypass through.
    """
    # Positive: every direct access form should match.
    for src in [
        'redis_url = os.environ["REDIS_URL"]',
        "redis_url = os.environ['REDIS_URL']",
        'redis_url = os.environ.get("REDIS_URL")',
        'redis_url = os.environ.get("REDIS_URL", "redis://localhost")',
        'redis_url = os.getenv("REDIS_URL")',
        'redis_url = os.getenv("REDIS_URL", default)',
        "redis_url = os . environ [ 'REDIS_URL' ]",  # whitespace-tolerant
    ]:
        assert _ENV_ACCESS_RE.search(src), f"Audit missed direct-access form: {src!r}"

    # Negative: indirect / wrapped forms must NOT match.
    for src in [
        "redis_url = settings.redis_url",
        "redis_url = get_settings().redis_url",
        "redis_url = self.environ_helper(key)",  # not os.environ
        "# os.environ.get('REDIS_URL')",  # comment-only
    ]:
        # `code_part` strips comments; we test the regex behaviour
        # AND the comment-stripping by going through the line filter.
        code_part = src.split("#", 1)[0]
        assert not _ENV_ACCESS_RE.search(code_part), f"Audit false-positively flagged a non-os.environ form: {src!r}"


def test_file_allowlist_entries_actually_correspond_to_real_files():
    """Defensive: stale `_FILE_ALLOWLIST` entries silently mask
    future regressions. Every entry must correspond to a real
    file under one of the scan roots.
    """
    real_files: set[str] = set()
    for path in _scan_files():
        real_files.add(path.relative_to(_REPO_ROOT).as_posix())
    # Also include allowlisted files that the scanner skips
    # (we still want to confirm they exist on disk).
    for rel in _FILE_ALLOWLIST:
        real_files.add(rel) if (_REPO_ROOT / rel).exists() else None

    stale = [k for k in _FILE_ALLOWLIST if not (_REPO_ROOT / k).exists()]
    assert not stale, (
        f"Stale _FILE_ALLOWLIST entries: {stale}. Remove them so the allowlist reflects only currently-live exemptions."
    )
