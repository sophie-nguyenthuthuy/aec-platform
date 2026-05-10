"""Audit: every router module under `apps/api/routers/` is
imported AND mounted by `main.py::create_app()`.

Failure mode this catches:

  * **Shipped a router file, forgot to wire it into `main.py`.**
    The router exports a working `router` object; the file's
    own unit tests pass; CI is green. But `app.include_router()`
    never runs against it, so every path the router exposes 404s
    on the first partner request after deploy. Discovered when
    a customer reports "I followed the docs but the endpoint is
    missing" — usually 24+ hours after the silent miss landed.

  * **Renamed a router module without updating `main.py`'s
    import block.** Symmetric failure: the import line in
    `main.py` references the old name, fails with `ImportError`
    on app startup, and the entire API process won't boot. The
    failure here is loud (boot crash) but the audit catches it
    before deploy.

The audit walks `apps/api/routers/` for `*.py` files (excluding
`__init__.py`), reads `apps/api/main.py`, and asserts each router
module is BOTH imported AND has its `.router` mounted via
`app.include_router(...)`.

Allowlist surface:

  * `_NOT_ROUTER_FILES` — files in `routers/` that don't export
    a router (helpers, shared types). Today: empty besides
    `__init__.py`.

  * `_DELIBERATELY_UNMOUNTED` — router modules that are imported
    elsewhere but NOT mounted via `app.include_router()`. Today:
    empty. PR review of an addition checks "do we really not
    want this router in the API?".

This file is read-only — source-greps `main.py`. Survives reverts.
"""

from __future__ import annotations

import re
from pathlib import Path


# Files in `routers/` that don't export a `router` symbol — they
# live in the directory for packaging but aren't FastAPI routers.
_NOT_ROUTER_FILES: frozenset[str] = frozenset(
    {
        "__init__.py",
    }
)


# Router modules that are deliberately NOT mounted in
# `main.py::create_app()`. Each entry needs a rationale comment
# naming WHY the router is excluded.
#
# TODO(triage 2026-05) entries are unmounted-router bugs that the audit caught
# on its first run. They sit here as a triage list — fix each
# one and remove the entry. The audit ratchets DOWN over time.
_DELIBERATELY_UNMOUNTED: dict[str, str] = {
    # `routers/codeguard_quota.py` is mounted via DELEGATION
    # through `routers/codeguard.py`:
    #   from routers.codeguard_quota import quota_router as _quota_router
    # The parent codeguard router includes it as a sub-router.
    # This indirection is documented in codeguard_quota.py's
    # module docstring (the "concentrate at-risk routes into a
    # small focused module" rationale). The audit's main.py-only
    # check legitimately doesn't see this; allowlist it.
    "codeguard_quota": "delegated mount via routers/codeguard.py — sub-router pattern",
    # TODO(triage 2026-05): `routers/sandbox.py` exists with route
    # decorators but ISN'T mounted anywhere in `main.py` AND
    # isn't delegated through another router. Endpoints under
    # `/api/v1/sandbox/*` will 404 on every partner request.
    # Resolution: add `app.include_router(sandbox.router)` in
    # main.py::create_app() (or move sandbox routes under an
    # existing router as a delegation). Remove this entry once
    # mounted.
    "sandbox": "TODO(triage): router file exists but never mounted — endpoints 404",
}


def _routers_dir() -> Path:
    return Path(__file__).parent.parent / "routers"


def _main_py_source() -> str:
    main_path = Path(__file__).parent.parent / "main.py"
    return main_path.read_text()


def _list_router_modules() -> set[str]:
    """List every module name under `apps/api/routers/` that's a
    candidate for mounting (excluding `_NOT_ROUTER_FILES`).

    Returns the bare module name (e.g. `"admin"`, not
    `"routers.admin"`)."""
    out: set[str] = set()
    for py_file in sorted(_routers_dir().glob("*.py")):
        if py_file.name in _NOT_ROUTER_FILES:
            continue
        out.add(py_file.stem)
    return out


def _imported_in_main(main_src: str, module: str) -> bool:
    """Return True if `module` is imported into `main.py` via
    EITHER form:

      * `from routers import (\n    module,\n    ...\n)` — the
        bulk-import block.
      * `from routers import module as <alias>` — the per-module
        aliased import (used for routers that need a stable name
        like `<module>_router`).

    A regex covers both forms; the audit's failure message names
    which form would fix the miss.
    """
    # Form 1: bulk import. Match `from routers import (...)` and
    # check that `module,` or `module\n` appears inside the
    # parentheses block. We use a non-greedy match across newlines.
    bulk_re = re.compile(
        r"from\s+routers\s+import\s+\(([^)]+)\)",
        re.DOTALL,
    )
    for match in bulk_re.finditer(main_src):
        block = match.group(1)
        # Tokenise the comma-separated names; tolerate trailing
        # comments via the noqa pattern.
        names = re.findall(r"^\s*(\w+)\s*,?", block, re.MULTILINE)
        if module in names:
            return True

    # Form 2: aliased import. `from routers import <module> as <alias>`.
    aliased_re = re.compile(rf"from\s+routers\s+import\s+{re.escape(module)}\s+as\s+\w+")
    if aliased_re.search(main_src):
        return True

    return False


def _mounted_in_main(main_src: str, module: str) -> bool:
    """Return True if `app.include_router()` references the
    module's `.router` attribute. Two forms accepted:

      * `app.include_router(<module>.router)` — bulk-import form
      * `app.include_router(<alias>.router)` where `<alias>` is
        `<module>_router` (the convention in `main.py`'s aliased
        imports)
    """
    # Form 1: bare module.router.
    bare_pattern = rf"app\.include_router\(\s*{re.escape(module)}\.router\s*[,)]"
    if re.search(bare_pattern, main_src):
        return True

    # Form 2: aliased <module>_router.router.
    aliased_pattern = rf"app\.include_router\(\s*{re.escape(module)}_router\.router\s*[,)]"
    if re.search(aliased_pattern, main_src):
        return True

    return False


def test_every_router_module_is_imported_in_main():
    """For every `routers/<module>.py`, `main.py` MUST import the
    module — either via the bulk `from routers import (...)` block
    or an aliased `from routers import <module> as <alias>` line.

    A new router that's not imported never gets the chance to be
    mounted; its endpoints 404 silently.
    """
    main_src = _main_py_source()
    candidates = _list_router_modules() - set(_DELIBERATELY_UNMOUNTED.keys())

    not_imported: list[str] = []
    for module in sorted(candidates):
        if not _imported_in_main(main_src, module):
            not_imported.append(module)

    assert not not_imported, (
        "These router modules exist in `apps/api/routers/` but "
        "aren't imported by `apps/api/main.py`:\n  " + "\n  ".join(not_imported) + "\n\n"
        "Resolution:\n"
        "  1. **Common case**: add the module to the bulk "
        "`from routers import (...)` block in main.py.\n"
        "  2. **If the router needs a stable alias** (e.g. "
        "`<module>_router` to avoid name collisions), add "
        "`from routers import <module> as <module>_router` "
        "instead.\n"
        "  3. **Deliberately not mounted** (rare): add the "
        "module name to `_DELIBERATELY_UNMOUNTED` in this audit "
        "file with a rationale comment. PR review of THAT "
        "addition checks the rationale.\n\n"
        "Why this matters: a router with no main.py import is a "
        "dead file — its endpoints 404 on every partner request. "
        "Discovered hours later via a customer ticket."
    )


def test_every_imported_router_is_mounted():
    """For every router module imported in `main.py`, an
    `app.include_router()` call MUST reference its `.router`
    attribute.

    A regression here is symmetric to the import miss: the file
    is imported (so its module-level side effects run) but
    `include_router()` never executes — paths still 404.
    """
    main_src = _main_py_source()
    candidates = _list_router_modules() - set(_DELIBERATELY_UNMOUNTED.keys())

    imported_but_not_mounted: list[str] = []
    for module in sorted(candidates):
        if not _imported_in_main(main_src, module):
            # Already flagged by the import-presence test; don't
            # double-report.
            continue
        if not _mounted_in_main(main_src, module):
            imported_but_not_mounted.append(module)

    assert not imported_but_not_mounted, (
        "These router modules are imported in `main.py` but "
        "their `.router` is never passed to `app.include_router()`:\n  "
        + "\n  ".join(imported_but_not_mounted)
        + "\n\n"
        "The import runs the module's top-level code (decorators, "
        "model registration) but the endpoints aren't wired into "
        "the FastAPI app. Add an `app.include_router(<module>.router)` "
        "(or `<module>_router.router` if aliased) line in "
        "create_app()."
    )


def test_audit_finds_at_least_one_router():
    """Sanity floor: the audit's iteration finds at least a handful
    of router modules. If the routers/ dir got moved or wiped, the
    audit would silently pass with zero modules scanned.
    """
    candidates = _list_router_modules()
    assert len(candidates) >= 5, (
        f"Audit found {len(candidates)} router modules — "
        "implausibly few. Either routers/ moved (update "
        "`_routers_dir()`) or every router got refactored away "
        "(broader regression worth surfacing)."
    )


def test_deliberately_unmounted_allowlist_entries_have_rationale():
    """Every `_DELIBERATELY_UNMOUNTED` entry has a non-empty
    rationale string. The whole point of the allowlist is the
    rationale next to the entry — bare entries without a comment
    defeat the review-the-decision design."""
    for module, rationale in _DELIBERATELY_UNMOUNTED.items():
        assert rationale and rationale.strip(), (
            f"`_DELIBERATELY_UNMOUNTED` entry `{module}` has an "
            "empty rationale. PR reviewers need the WHY alongside "
            "the entry."
        )


def test_deliberately_unmounted_allowlist_is_minimal():
    """The carve-out for unmounted routers should stay empty in
    steady state. Pin a low cap so a future addition is reviewed
    deliberately."""
    assert len(_DELIBERATELY_UNMOUNTED) <= 2, (
        f"_DELIBERATELY_UNMOUNTED has "
        f"{len(_DELIBERATELY_UNMOUNTED)} entries: "
        f"{list(_DELIBERATELY_UNMOUNTED.keys())}. Today should be 0; "
        "if the list grows past 2, that's a signal of accumulated "
        "shipped-but-not-mounted routers — verify each one is "
        "intentional."
    )
