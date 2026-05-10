"""Settings-only env-access audit.

The bug class
-------------
Direct env-var reads in router/service code bypass the project's
typed Settings boundary:

    # in routers/foo.py
    import os
    DEBUG = os.environ.get("DEBUG")  # <-- bypasses Settings

Three real costs:

1. **No validation.** `Settings` is a `pydantic_settings.BaseSettings`
   subclass that validates types, applies defaults, and raises at
   startup if a required value is missing. A direct `os.environ.get`
   skips all of that — the route returns "DEBUG=True" as the literal
   string `"true"` and string-truthy ≠ bool-True.

2. **Invisible config surface.** Settings shows up in
   `tests/test_settings_shape_pin.py` as the canonical config
   surface; reviewers can audit it. A `os.environ.get(...)` buried
   inside a 200-line router is invisible to that pin and to anyone
   trying to inventory deploy-time configuration.

3. **Test isolation pain.** Every test that touches the Settings
   object can override it via the documented fixture pattern.
   `os.environ.get(...)` reads from the live process environment —
   tests have to monkeypatch + restore manually, and a forgotten
   teardown leaks state into the next test.

The fix is one substitution: declare the var on `Settings`, then
read `settings.<NAME>` from the same import everyone else uses.

What this audit checks
----------------------
AST walk over `apps/api/{core,db,middleware,models,routers,schemas,
services,workers}/*.py` plus `apps/worker/*.py`. Flag four shapes:

  1. `<X>.environ.get(...)`  — typical lazy read with default.
  2. `<X>.environ[...]`      — bracket-style mandatory read.
  3. `<X>.getenv(...)`       — `os.getenv` shorthand.
  4. `<X>.environ.setdefault(...)` / `.pop(...)` — env-mutation.

The first attribute (`<X>`) is intentionally not pinned to `os` —
the codeguard healthcheck uses `import os as _os` to dodge a
local-name conflict. Matching `.environ` / `.getenv` by attribute
name catches both shapes; the false-positive surface is empty
(no library this codebase uses defines `.environ` or `.getenv`
attributes for unrelated purposes).

What's NOT checked
------------------
- `tests/` — tests legitimately read env to gate Postgres-required
  cases (`MIGRATIONS_TEST_DB_URL`, etc.) and patch via fixtures.
- `scripts/` — operator-facing CLIs read env directly by convention
  (no Settings instance is loaded for one-shot tools).
- Alembic migrations — same as scripts; env.py reads `DATABASE_URL_SYNC`
  directly to avoid pulling in the API's full Settings module.
- `core/settings.py` itself — that's the ONE place env reads belong.
  pydantic-settings reads via its own internal os.environ access,
  but the AST shape is `BaseSettings`-driven (no literal
  `os.environ.get` lines), so this audit doesn't have to allowlist
  it explicitly.
- `core/`, `db/` — these layers may re-export settings or read
  startup-only values through Settings; same allowlist intent
  but in practice no offenders today.

Allowlist
---------
Per-(file, line) for legitimate cases. Each entry needs a stated
reason. The two known-good cases live in `routers/codeguard.py`
where the dependency-healthcheck endpoint reads optional-dep env
vars (`ELASTICSEARCH_URL` and an LLM-provider-key var) without
baking them into the central Settings schema — those deps are
genuinely optional and the platform degrades gracefully when
absent.

Same ratchet pattern as `test_print_in_production_audit.py` and
`test_logger_lazy_formatting_audit.py`.
"""

from __future__ import annotations

import ast
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


# Today's baseline. Both entries live in `routers/codeguard.py`
# for the optional-deps healthcheck — see ALLOWLIST below.
BASELINE_DIRECT_ENV_READS = (
    2  # 2026-05: 2 legitimate optional-deps healthcheck reads in routers/codeguard.py; ratchet pinned at 2.
)


# Per-(relative_posix_path, line) allowlist. Each entry needs a
# stated reason — an empty rationale silences the gate.
ALLOWLIST: dict[tuple[str, int], str] = {
    # codeguard's `/health/ai-providers` healthcheck reads
    # OPTIONAL-dep env vars (the active LLM-provider key + an
    # optional Elasticsearch URL). Baking them into Settings
    # would make missing values a startup-time failure for a
    # deploy that doesn't use the optional dep — the explicit
    # `_os.environ.get(...)` is the right shape because it lets
    # the healthcheck return `unavailable` cleanly.
    ("apps/api/routers/codeguard.py", 131): "optional LLM-provider env-presence check; pre-Settings by design",
    (
        "apps/api/routers/codeguard.py",
        155,
    ): "optional ELASTICSEARCH_URL presence check; degrades to dense-only when absent",
}


def _scan_files() -> list[Path]:
    out: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            # Test files — env reads are legitimate in tests.
            if "tests" in p.parts:
                continue
            # Scripts — operator-facing CLIs read env directly.
            if "scripts" in p.parts:
                continue
            # Alembic migrations — env.py reads DATABASE_URL_SYNC
            # directly to avoid pulling in Settings.
            if "alembic" in p.parts:
                continue
            # Settings itself is the canonical place for env reads.
            if p.name == "settings.py":
                continue
            out.append(p)
    return sorted(out)


def _is_env_access(node: ast.AST) -> str | None:
    """Classify env-access shape. Returns kind or None.

    Matches `<X>.environ.get(...)`, `<X>.environ[...]`, `<X>.getenv(...)`,
    and the env-mutating shapes `setdefault` / `pop` on `<X>.environ`.

    `<X>` is intentionally not pinned to `os` — `import os as _os`
    is a real pattern in this codebase. The false-positive surface
    on raw attribute names `.environ` / `.getenv` is empty.
    """
    # Call shapes.
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute):
            if f.attr == "getenv":
                return "getenv"
            if (
                f.attr in ("get", "setdefault", "pop")
                and isinstance(f.value, ast.Attribute)
                and f.value.attr == "environ"
            ):
                return f"environ.{f.attr}"
    # Subscript shape: x.environ["KEY"].
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "environ":
        return "environ[]"
    return None


def _scan_file(path: Path) -> list[tuple[str, int, str, str]]:
    """Return findings: (rel_path, line, kind, source_line)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    rel = path.relative_to(_REPO_ROOT).as_posix()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    out: list[tuple[str, int, str, str]] = []
    lines = text.splitlines()
    for node in ast.walk(tree):
        kind = _is_env_access(node)
        if kind is None:
            continue
        line = node.lineno
        if (rel, line) in ALLOWLIST:
            continue
        try:
            source_line = lines[line - 1].strip()[:80]
        except IndexError:
            source_line = "<unknown>"
        out.append((rel, line, kind, source_line))
    return out


def _audit_all() -> list[tuple[str, int, str, str]]:
    out: list[tuple[str, int, str, str]] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_direct_env_reads_outside_settings():
    """Every env-var read in routers/services/workers should
    funnel through Settings. Direct `os.environ.get(...)` bypasses
    type validation, the test-fixture override pattern, and the
    config-surface pin in `test_settings_shape_pin.py`.
    """
    findings = _audit_all()
    n_unallowlisted = len(findings)
    # The baseline counts the ALLOWLIST-relieved entries too — the
    # ratchet target is "no NEW direct reads," allowlist included.
    n_total = n_unallowlisted + len(ALLOWLIST)
    if n_total > BASELINE_DIRECT_ENV_READS:
        new = n_total - BASELINE_DIRECT_ENV_READS
        rendered = [f"{rel}:{line}  [{kind}]  {src}" for rel, line, kind, src in findings[:20]]
        pytest.fail(
            f"{new} new direct env-var read(s) "
            f"(total now {n_total}, baseline {BASELINE_DIRECT_ENV_READS}):\n  "
            + "\n  ".join(rendered)
            + (f"\n  … and {n_unallowlisted - 20} more" if n_unallowlisted > 20 else "")
            + "\n\nFunnel env access through Settings:\n"
            "    # was:\n"
            "    import os\n"
            "    debug = os.environ.get('DEBUG', 'false') == 'true'\n"
            "    # use:\n"
            "    from core.settings import settings\n"
            "    debug = settings.DEBUG  # typed as bool, validated at startup\n\n"
            "Why it matters: Settings is the canonical config surface. "
            "Direct env reads:\n"
            "  - Skip pydantic type coercion (env strings stay strings).\n"
            "  - Are invisible to test_settings_shape_pin.py.\n"
            "  - Force tests to monkeypatch the live process env.\n\n"
            "If a value is genuinely a per-request optional probe (a "
            "healthcheck for an optional dep), add the (file, line) "
            "entry to ALLOWLIST with a stated reason — the same shape "
            "the codeguard.py optional-deps probe uses today."
        )
    if n_total < BASELINE_DIRECT_ENV_READS:
        pytest.fail(
            f"Direct-env-read count dropped from {BASELINE_DIRECT_ENV_READS} "
            f"to {n_total}. 🎉 Update `BASELINE_DIRECT_ENV_READS` to {n_total} "
            f"(remember to count the ALLOWLIST entries — the baseline is total, "
            f"not unallowlisted)."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative AST fixtures so a refactor
    of the detection logic surfaces here as a clean failure.
    """
    # Positive: os.environ.get with default.
    pos1 = ast.parse('value = os.environ.get("DEBUG", "false")\n')
    hits = [_is_env_access(n) for n in ast.walk(pos1)]
    assert "environ.get" in hits

    # Positive: _os alias (lazy import pattern).
    pos2 = ast.parse('value = _os.environ.get("DEBUG")\n')
    hits = [_is_env_access(n) for n in ast.walk(pos2)]
    assert "environ.get" in hits

    # Positive: os.getenv shorthand.
    pos3 = ast.parse('value = os.getenv("DEBUG")\n')
    hits = [_is_env_access(n) for n in ast.walk(pos3)]
    assert "getenv" in hits

    # Positive: os.environ["KEY"] subscript.
    pos4 = ast.parse('value = os.environ["DEBUG"]\n')
    hits = [_is_env_access(n) for n in ast.walk(pos4)]
    assert "environ[]" in hits

    # Positive: os.environ.setdefault — env-mutating shape.
    pos5 = ast.parse('os.environ.setdefault("X", "y")\n')
    hits = [_is_env_access(n) for n in ast.walk(pos5)]
    assert "environ.setdefault" in hits

    # Positive: os.environ.pop — env-mutating shape.
    pos6 = ast.parse('os.environ.pop("X", None)\n')
    hits = [_is_env_access(n) for n in ast.walk(pos6)]
    assert "environ.pop" in hits

    # Negative: settings.DEBUG — the canonical good shape.
    neg1 = ast.parse("value = settings.DEBUG\n")
    hits = [_is_env_access(n) for n in ast.walk(neg1)]
    assert all(h is None for h in hits)

    # Negative: dict.get — `.get` on something other than .environ.
    neg2 = ast.parse('value = my_dict.get("k", "v")\n')
    hits = [_is_env_access(n) for n in ast.walk(neg2)]
    assert all(h is None for h in hits)

    # Negative: an unrelated `.environ`-named attribute (theoretical
    # — no real lib does this — but documents the false-positive
    # surface clearly).
    neg3 = ast.parse("value = some.unrelated_var\n")
    hits = [_is_env_access(n) for n in ast.walk(neg3)]
    assert all(h is None for h in hits)


def test_allowlist_entries_actually_correspond_to_real_env_reads():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions on the line of the renamed call. Same shape as
    the print-audit and logger-audit stale-entry tests.

    A stale entry is one whose (file, line) doesn't actually
    contain an env-read at scan time — the line moved, the file
    was renamed, or the call was deleted entirely.
    """
    if not ALLOWLIST:
        return
    real: set[tuple[str, int]] = set()
    for path in _scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if _is_env_access(node) is not None:
                real.add((rel, node.lineno))
    stale = [k for k in ALLOWLIST if k not in real]
    assert not stale, f"Stale ALLOWLIST entries: {stale}."
