"""Audit: every `/api/v1/admin/*` route MUST have an admin-role
dep in its dependency tree.

Cross-cutting tripwire that scales beyond any single router-pin
file. Today the admin surface is mostly in `routers/admin.py`,
but the codebase grows with one new `<vertical>_admin.py` router
per platform-admin feature (slack-deliveries, webhook-deliveries-
admin, cron-admin, etc.). Each new router is a chance to forget
the role gate.

A per-router pin (`test_X_router_surface_pin.py`) catches the
forget-the-gate failure within ONE file. This audit catches it
across EVERY router that mounts a path under `/api/v1/admin/`,
regardless of which file the handler lives in.

Failure mode this guards:

  * **A new admin endpoint lands without `require_role("admin")`
    or `require_min_role(Role.ADMIN)`.** The endpoint works for
    every authenticated user — including a misclick from an org
    member, or a partner with a stale api-key. The route's own
    tests (which probably mock auth) pass; the silent privilege
    drift is caught only when a customer notices they shouldn't
    have been able to see something.

The audit runs against the LIVE FastAPI app (`main.create_app()`)
so it sees every route the deployed binary exposes — not just the
ones a per-router test happens to import. Routes from mounted
sub-applications, lazy router imports, and middleware-attached
endpoints are all in scope.

Allowlist surface for legitimate exceptions:

  * `_PUBLIC_ADMIN_PATH_FRAGMENTS` — admin paths that are
    deliberately not gated (none today). The list exists so the
    audit failure message can suggest "if this is intentional,
    add it here" without requiring the audit's author to be the
    one extending it.

If you add a public admin endpoint, add a path fragment to that
list with a one-line rationale comment. The pin won't fire on
that path, but the deliberate-exception list itself is reviewed
in PR.

This file is read-only — runs the app factory + introspects
routes. Survives reverts.
"""

from __future__ import annotations

# Admin paths that are intentionally NOT gated. Today: none. The
# allowlist exists so the audit failure message can suggest "if
# this is intentional, add it here" without requiring the audit's
# author to be the one to extend it.
_PUBLIC_ADMIN_PATH_FRAGMENTS: tuple[str, ...] = ()


# Tokens that satisfy the admin-gate check when found in the
# resolved dependency call's qualname / name / source. Allow both
# `require_role("admin")` (the simple form) AND
# `require_min_role(Role.ADMIN)` (the hierarchical form). The
# detection lives in dep introspection AND a source-grep fallback
# because dep-injection wrapping can hide function identity past
# what FastAPI's `Dependant` exposes cleanly.
_ADMIN_GATE_TOKENS: tuple[str, ...] = (
    "require_role",  # pre-rbac single-string-allowed form
    "require_min_role",  # hierarchical form
)


def _admin_gate_in_dep_tree(dep) -> bool:
    """Walk a FastAPI Dependant tree looking for any dep whose
    underlying call is an admin-role gate.

    The gate factories return CLOSURES with names like `_dep`
    rather than `require_role` itself. We catch those via:

      1. Direct match on `dep.call.__name__` (rare; covered for
         completeness).
      2. Match on `dep.call.__qualname__` (catches the closure's
         outer scope — usually contains `require_role` or
         `require_min_role` because the closure is defined inside
         the factory).
      3. Source-grep on the closure (rarely accessible; fallback).
      4. Recurse through `dep.dependencies`.
    """
    call = getattr(dep, "call", None)
    if call is not None:
        for token in _ADMIN_GATE_TOKENS:
            if token in getattr(call, "__qualname__", ""):
                return True
            if token in getattr(call, "__name__", ""):
                return True
        # Fallback: read the closure's source if accessible. arq
        # workers + dep factories typically inline these.
        try:
            import inspect as _inspect

            src = _inspect.getsource(call)
            for token in _ADMIN_GATE_TOKENS:
                if token in src:
                    return True
        except (OSError, TypeError):
            # `inspect.getsource` raises for built-ins / C-defined
            # callables. Move on to recursion.
            pass

    # Recurse — admin-gate is often nested under require_auth
    # (which is the outer dep that resolves AuthContext, then the
    # admin gate wraps it).
    return any(_admin_gate_in_dep_tree(sub_dep) for sub_dep in getattr(dep, "dependencies", []) or [])


def test_every_admin_route_has_admin_role_gate():
    """SECURITY-CRITICAL audit. For every route whose path starts
    with `/api/v1/admin/`, walk the dependency tree and assert
    SOME dependency carries the admin-role gate.

    Failure surfaces a list of ungated paths so the developer
    can either:
      1. Add `Depends(require_role("admin"))` (or
         `Depends(require_min_role(Role.ADMIN))`) to the offending
         handler.
      2. If the path is deliberately public, add it to
         `_PUBLIC_ADMIN_PATH_FRAGMENTS` with a rationale.

    Either path makes the deliberate decision visible in PR review.
    """
    from fastapi.routing import APIRoute

    from main import create_app

    app = create_app()

    ungated: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not path.startswith("/api/v1/admin/"):
            continue
        # Allowlist for deliberate public-admin endpoints.
        if any(frag in path for frag in _PUBLIC_ADMIN_PATH_FRAGMENTS):
            continue
        if not _admin_gate_in_dep_tree(route.dependant):
            methods = ",".join(sorted(route.methods or set()))
            ungated.append(f"{methods} {path}")

    assert not ungated, (
        "These /api/v1/admin/* routes have no admin-role gate in "
        "their dependency tree:\n  " + "\n  ".join(sorted(ungated)) + "\n\n"
        "If the route is supposed to be admin-gated (the default), "
        'add `Depends(require_role("admin"))` or '
        "`Depends(require_min_role(Role.ADMIN))` to the handler. "
        "If it's deliberately public, add the path fragment to "
        "`_PUBLIC_ADMIN_PATH_FRAGMENTS` in this audit file with a "
        "one-line rationale comment.\n\n"
        "Why this matters: a member-role caller hitting an "
        "ungated admin endpoint sees cross-tenant data OR can "
        "trigger a destructive operation (retention prune, global "
        "config edit). The route's own tests probably mock auth; "
        "this audit is the only thing that catches the silent "
        "privilege drift before a customer notices."
    )


def test_admin_route_audit_catches_at_least_one_route():
    """Sanity check: the audit's iteration logic actually finds
    admin routes. If a future refactor moved every admin endpoint
    out of `/api/v1/admin/*`, this audit would silently pass with
    zero routes scanned — a tripwire that doesn't fire is worse
    than no tripwire.

    A failure here means EITHER (a) every admin endpoint moved
    to a different prefix (update the audit's prefix filter) OR
    (b) the app factory failed to mount the admin routers
    (broader regression worth surfacing).
    """
    from fastapi.routing import APIRoute

    from main import create_app

    app = create_app()
    admin_count = sum(1 for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/v1/admin/"))
    assert admin_count >= 1, (
        "Audit scanned 0 admin routes. The audit's prefix filter "
        "(`/api/v1/admin/`) might no longer match any route — "
        "either the prefix was renamed (update this filter) or "
        "the admin routers aren't being mounted in main.create_app()."
    )


def test_public_admin_allowlist_is_minimal():
    """The carve-out for deliberately-public admin paths exists
    but should be EMPTY in steady state. Pin its size so a future
    addition has to be deliberate AND reviewed.

    Today: empty. If you add an entry, also add a comment in
    `_PUBLIC_ADMIN_PATH_FRAGMENTS` explaining WHY that path is
    public. The PR reviewer reads the comment alongside this pin's
    failure message and decides whether the public-admin carve-out
    is justified.
    """
    assert len(_PUBLIC_ADMIN_PATH_FRAGMENTS) <= 2, (
        f"_PUBLIC_ADMIN_PATH_FRAGMENTS now has "
        f"{len(_PUBLIC_ADMIN_PATH_FRAGMENTS)} entries: "
        f"{_PUBLIC_ADMIN_PATH_FRAGMENTS}. The allowlist exists for "
        "legitimate exceptions but should stay small; if it grows "
        "past 2, that's a signal that 'public admin' is becoming "
        "the norm and the audit's posture should be revisited."
    )
