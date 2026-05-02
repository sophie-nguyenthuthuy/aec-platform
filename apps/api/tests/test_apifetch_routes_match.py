"""Static check: every frontend `apiFetch(...)` path matches a real API route.

Why this exists: a previous batch shipped `/admin/scrapers` calling
`/api/v1/admin/scraper-runs/summary`, which 404'd because the endpoint
was never implemented. The summary table just rendered the empty
state on error — silent failure mode. This test catches that whole
class of bug at CI time:

  1. Build the full FastAPI app (mounts every router).
  2. Walk every `.ts`/`.tsx` file under `apps/web/{hooks,lib,app}`.
  3. Extract `apiFetch(...)` first-arg path literals (string + template).
  4. Convert each side to a "param-slot-normalised" pattern:
        FastAPI `/foo/{rule_id}/bar`  →  `/foo/{}/bar`
        Frontend `/foo/${id}/bar`     →  `/foo/{}/bar`
  5. Assert each frontend path matches at least one API pattern.

Allowlist: `_TOLERATED` for paths that are intentionally not-yet-built
(used by a not-yet-shipped feature). Keep narrow — every entry should
have a TODO and an owner. The bar to add a tolerated path is "the
hook is committed but the endpoint is in a follow-up PR."
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Frontend paths the API doesn't (yet) implement. Empty by design — if
# you're tempted to add one, ask whether the missing endpoint should
# instead block the merge that introduced the call.
_TOLERATED: set[str] = set()


def _project_root() -> Path:
    """Walk up from this file to the repo root (the dir containing
    `apps/`). Parametrised so a future test relocation doesn't
    silently break the walk."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "apps" / "web").is_dir():
            return parent
    raise RuntimeError("could not locate repo root from test file")


def _registered_route_patterns() -> set[str]:
    """Build the FastAPI app and return the set of route paths,
    normalised so `{name}` becomes `{}` for shape-matching."""
    # Lazy import — `create_app` pulls in every router, which is
    # heavy. Doing it at module-load would slow every test run, not
    # just this one.
    from main import create_app

    app = create_app()
    out: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            continue
        # Skip non-API mounts (static, healthz, etc.) — frontend
        # `apiFetch` calls only target `/api/v1/...`.
        if not path.startswith("/api/"):
            continue
        out.add(_normalise_param_slots(path, brace_pattern=r"\{[^}]+\}"))
    return out


def _normalise_param_slots(path: str, *, brace_pattern: str) -> str:
    """Replace param slots in `path` with `{}` — both sides of the
    comparison go through here so they line up.

    `brace_pattern` differs by source: FastAPI uses `{rule_id}`,
    frontend template literals use `${id}`. Each caller passes the
    appropriate regex.
    """
    return re.sub(brace_pattern, "{}", path)


# Match `apiFetch(...)` first-arg path literals. Two shapes accepted:
#   apiFetch<...>("/api/v1/foo")
#   apiFetch<...>(`/api/v1/foo/${id}`)
# The first arg can sit on the same line OR the next (a common
# Prettier wrap), so we allow optional whitespace + newlines after
# the opening paren. Re-anchored on the leading `/api` to keep us
# from matching unrelated string literals later in the call.
_APIFETCH_RE = re.compile(
    r"""apiFetch\s*(?:<[^>]*>)?\s*\(\s*[`"](?P<path>/api/[^`"]+)[`"]""",
    re.MULTILINE,
)


def _scan_frontend_apifetch_paths(repo_root: Path) -> dict[str, list[Path]]:
    """Walk the frontend tree for `apiFetch(...)` literals.

    Returns `{normalised_path: [files...]}` so a failure message can
    point at the exact source file. We don't dedupe on file because
    the same hook file may have several apiFetch calls; we only
    dedupe on the normalised path itself for the assertion.
    """
    web_root = repo_root / "apps" / "web"
    candidate_dirs = [web_root / "hooks", web_root / "lib", web_root / "app"]

    paths: dict[str, list[Path]] = {}
    for d in candidate_dirs:
        if not d.is_dir():
            continue
        for f in d.rglob("*.ts*"):
            # Skip generated + test files. `__tests__/` keeps the
            # hooks-test fakes out (they reference paths via mocked
            # fetch, not apiFetch); `.next/` would dwarf everything.
            parts = set(f.parts)
            if "__tests__" in parts or ".next" in parts or "node_modules" in parts:
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for m in _APIFETCH_RE.finditer(text):
                raw = m.group("path")
                # Strip any inline query string (`?foo=${bar}`) — a
                # few hooks build URLs with `?key=value` literal in
                # the path instead of the `query: {}` option, but
                # query strings are NEVER part of the FastAPI route
                # path, so they shouldn't gate the match.
                raw = raw.split("?", 1)[0]
                # `${...}` → `{}` for shape comparison with FastAPI's
                # `{name}` slots.
                normalised = _normalise_param_slots(raw, brace_pattern=r"\$\{[^}]+\}")
                paths.setdefault(normalised, []).append(f)
    return paths


# ---------- Test ----------


def test_every_frontend_apifetch_path_matches_a_registered_route():
    """Catches the "frontend hook calls a 404 endpoint" failure mode.

    See module docstring for design + allowlist rationale.
    """
    repo_root = _project_root()
    api_patterns = _registered_route_patterns()
    fe_paths = _scan_frontend_apifetch_paths(repo_root)

    # Sanity: the scan actually picked something up. If this collapses
    # to 0, the regex regressed silently and the test would always pass.
    assert fe_paths, "scanned 0 apiFetch calls — regex must be broken"

    missing: dict[str, list[Path]] = {}
    for fe_path, files in fe_paths.items():
        if fe_path in _TOLERATED:
            continue
        if fe_path not in api_patterns:
            missing[fe_path] = files

    if missing:
        # Build a readable failure message: which path(s) are unbacked
        # and which file(s) call them. The repo-relative path is
        # easier to act on than a full absolute path.
        lines = ["Frontend `apiFetch` paths with no matching API route:"]
        for path, files in sorted(missing.items()):
            lines.append(f"  {path}")
            for f in sorted(set(files)):
                try:
                    rel = f.relative_to(repo_root)
                except ValueError:
                    rel = f
                lines.append(f"    called from: {rel}")
        lines.append("")
        lines.append(
            "Either implement the missing endpoint, fix the path on the "
            "frontend, or (last resort) add it to `_TOLERATED` with a "
            "TODO + owner.",
        )
        pytest.fail("\n".join(lines))


def test_normalisation_helpers_round_trip():
    """Sanity: the two `{...}`-replacement regexes turn matching paths
    into the same string. Without this, the main test could pass
    vacuously by normalising both sides differently.
    """
    api_side = _normalise_param_slots(
        "/api/v1/admin/normalizer-rules/{rule_id}",
        brace_pattern=r"\{[^}]+\}",
    )
    fe_side = _normalise_param_slots(
        "/api/v1/admin/normalizer-rules/${id}",
        brace_pattern=r"\$\{[^}]+\}",
    )
    assert api_side == fe_side == "/api/v1/admin/normalizer-rules/{}"


def test_apifetch_regex_recognises_both_string_and_template_literals():
    """The regex must accept both `"/api/..."` and `` `/api/...` ``
    forms — Prettier flips between them based on whether the call has
    template params, and a regex change that drops one form would
    silently halve the audit's coverage."""
    sample = """
    const x = apiFetch<Foo>("/api/v1/static-string", { token, orgId });
    const y = await apiFetch<Bar>(`/api/v1/template/${id}`, { token, orgId });
    const z = apiFetch<Baz>(
      "/api/v1/wrapped-on-next-line",
      { token, orgId },
    );
    """
    matches = [m.group("path") for m in _APIFETCH_RE.finditer(sample)]
    assert "/api/v1/static-string" in matches
    assert "/api/v1/template/${id}" in matches
    assert "/api/v1/wrapped-on-next-line" in matches
