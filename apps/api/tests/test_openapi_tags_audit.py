"""Per-route OpenAPI tags audit.

The bug class
-------------
A route registered without `tags=[...]` shows up in /docs ungrouped,
floating at the top of the page between the module-organized ones.
Multiply by 200+ routes and /docs becomes uselessly disorganized
for new contributors trying to navigate it.

The fix has two shapes that both satisfy the contract:

  1. Per-route tag:
        @router.post("/x", tags=["pulse"])
        def f(): ...

  2. Router-level tag (preferred):
        router = APIRouter(prefix="/api/v1/pulse", tags=["pulse"])

What this audit checks
----------------------
Walk every route on `main.app`; assert each has a non-empty `tags`
list. Same shape as the auth audit and the route-docs audit.
Ratchet baseline.

What it doesn't check
---------------------
Tag content. A route tagged `["misc"]` satisfies the gate even
though that's a poor tag choice. Tag QUALITY is a code-review
concern; the audit's purpose is "is the field populated at all."
"""

from __future__ import annotations

import pytest

# Today's baseline. Filled in on first run; ratchet down as
# routers gain tags.
BASELINE_UNTAGGED_ROUTES = 0


# Routes that legitimately don't need tagging (framework-mounted,
# internal-only).
ALLOWLIST: dict[tuple[str, str], str] = {
    # Health/metrics/readiness — framework-level, intentionally
    # outside the module taxonomy of /docs.
    ("/health", "GET"): "liveness probe; framework-level, not module-scoped",
    ("/health/ready", "GET"): "readiness probe; framework-level",
    ("/metrics", "GET"): "Prometheus exposition; framework-level",
}


_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def _allowlist_hit(path: str, method: str) -> str | None:
    return ALLOWLIST.get((path, method))


def test_every_route_has_at_least_one_tag():
    """Walk `main.app`; for each route, assert `route.tags` is
    non-empty. /docs uses tags to group endpoints by module — a
    missing tag means the route shows up ungrouped at the top.

    Failures surface both ratchet directions.
    """
    from main import create_app

    app = create_app()

    untagged: list[tuple[str, str]] = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if path.startswith("/docs") or path in {"/openapi.json", "/redoc"}:
            continue
        for method in methods & _HTTP_METHODS:
            if _allowlist_hit(path, method):
                continue
            tags = getattr(route, "tags", None) or []
            if not tags:
                untagged.append((method, path))

    n = len(untagged)
    if n > BASELINE_UNTAGGED_ROUTES:
        new = n - BASELINE_UNTAGGED_ROUTES
        formatted = "\n  ".join(f"{m:<7} {p}" for m, p in sorted(untagged)[:20])
        pytest.fail(
            f"{new} new untagged route(s) "
            f"(total now {n}, baseline {BASELINE_UNTAGGED_ROUTES}):\n  "
            + formatted
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + '\n\nAdd `tags=["<module>"]` to either:\n'
            '  • the per-route decorator: `@router.post("/x", tags=["pulse"])`\n'
            '  • the router declaration: `APIRouter(prefix="...", tags=["pulse"])` '
            "(preferred — applies to every route on the router).\n\n"
            "Without tags, /docs renders the route ungrouped at the top "
            "of the page, between the module-organized ones."
        )
    if n < BASELINE_UNTAGGED_ROUTES:
        pytest.fail(
            f"Untagged-route count dropped from {BASELINE_UNTAGGED_ROUTES} "
            f"to {n}. 🎉 Update `BASELINE_UNTAGGED_ROUTES` to {n}."
        )


def test_allowlist_entries_actually_match_routes():
    """Defensive: every ALLOWLIST entry must correspond to a real
    route. Stale entries silently mask future regressions when the
    route was renamed."""
    from main import create_app

    app = create_app()
    real_pairs = {(getattr(r, "path", ""), m) for r in app.routes for m in (getattr(r, "methods", None) or set())}
    stale = [f"{m} {p}" for (p, m) in ALLOWLIST if (p, m) not in real_pairs]
    assert not stale, (
        "ALLOWLIST has stale entries:\n  "
        + "\n  ".join(stale)
        + "\nRemove them so the allowlist reflects only currently-live exemptions."
    )
