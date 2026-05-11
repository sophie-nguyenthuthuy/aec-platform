"""Smoke tests for `main.create_app()` itself.

Why this exists: every other test mounts a single router or stubs
the full app. Nothing today asserts that the production FastAPI
factory builds successfully + that the resulting app has the
shape we expect. That gap has bitten us:

  * `routers.activity_stream` was missing from `main.py`'s
    `include_router` calls for several batches; the corresponding
    `useActivityStream.ts` hook 404'd silently in production.
    `test_apifetch_routes_match.py` eventually caught it via path-
    matching, but a smoke test on `app.routes` would have caught it
    at the same gate as well — and would also catch routes
    registered without auth.

  * Import-time side effects (model registration, settings
    validation, observability setup) only manifest in
    `create_app()`. A typo in `from routers import ...` that
    raises ImportError fails every endpoint test, but the failure
    mode looks like "every test errors out" rather than "this
    one root-cause hits the import line."

This file pins three properties of the built app:

  1. `create_app()` returns a `FastAPI` instance without raising.
  2. Route count is plausible (at least 100 routes) — surfaces a
     mass-deregistration regression.
  3. Every `/api/v1/*` endpoint declares an auth-style dependency
     (`require_auth`, `require_role`, `require_min_role`,
     `require_scope`) — so a route added without gating fails
     CI rather than landing as a silent privilege bug.

Public-by-design routes (`public_rfq.*`, the test-fire endpoints
intentionally exposed without auth) are allowlisted explicitly.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

# Routes that intentionally have NO auth dependency. Every entry
# should carry a one-line rationale in the comment so a reviewer
# adding a new route knows why it's here vs. needing an auth gate.
#
# Match-shape: a path is allowlisted when ANY entry in this set
# is a substring of the route path. Substring (not prefix) so
# `/api/v1/public/rfq/respond` and `/api/v1/public/rfq/context`
# both match a single `/public/` rule.
_AUTH_FREE_ROUTE_FRAGMENTS: frozenset[str] = frozenset(
    {
        # Token-in-URL is the auth — the supplier has no AEC
        # account; the unguessable token in the email IS the
        # credential. See `routers/public_rfq.py`.
        "/api/v1/public/rfq/",
        # Onboarding signup bootstraps the org + first user; no
        # logged-in caller exists yet by definition.
        "/api/v1/onboarding/signup",
        # Invitation accept / preview — the recipient has no org
        # membership until the call succeeds; the unguessable token
        # in the path IS the credential. Same shape as public RFQ.
        "/api/v1/invitations/{token}",
        # Public webhook event catalog — partners evaluate the
        # platform's webhook surface BEFORE getting an API key.
        # Pure documentation, no tenant-scoped data. Pinned by the
        # integrator-surface snapshot too.
        "/api/v1/webhooks/event-types",
        # SSE activity stream — `GET /api/v1/activity/stream?ticket=…`.
        # EventSource can't carry custom headers, so authentication is
        # done via the one-shot ticket query param (minted from the
        # Bearer-authed `POST /activity/stream/ticket` endpoint, which
        # IS still gated). Same shape as `/api/v1/public/rfq/` —
        # token-in-URL is the auth.
        "/api/v1/activity/stream",
        # Webhook signature-verification playground —
        # `POST /api/v1/webhooks/verify-signature`. Public on purpose:
        # partners debug their integration BEFORE getting an API key,
        # and the endpoint is read-only HMAC-over-user-supplied-bytes
        # (no DB access, no tenant data). The secret used in the
        # computation is supplied by the caller, so there's nothing
        # to leak. See routers/webhooks.py for the full rationale.
        "/api/v1/webhooks/verify-signature",
    }
)


def _build_app() -> FastAPI:
    """Build the app once, isolated from the surrounding test session
    so an import-time regression surfaces here as a clean failure
    rather than a chain of unrelated test errors.
    """
    from main import create_app

    return create_app()


def test_create_app_does_not_raise():
    """Smoke: `create_app()` builds without raising. A typo in any
    `from routers import ...` line, a misspelt `include_router`,
    a model-registration failure — all manifest as an exception
    here with a clean traceback pointing at the line.
    """
    app = _build_app()
    assert isinstance(app, FastAPI)


def test_app_has_plausible_route_count():
    """Lower bound on `app.routes` — guards against a mass
    deregistration regression. The current count (as of 2026-05-04)
    is ~430; the floor is set well below to absorb deliberate
    consolidations without false failures.

    A new value at this floor (e.g. dropping below 100) would mean
    something on the order of 30 routers worth of endpoints went
    missing — almost certainly a `from routers import (...)` block
    accidentally truncated.
    """
    app = _build_app()
    assert len(app.routes) > 100, (
        f"app has only {len(app.routes)} routes — expected >100. "
        "Likely a router include_router was accidentally dropped or "
        "an import block was truncated."
    )


def test_every_api_v1_route_has_auth_dependency():
    """Every `/api/v1/*` endpoint MUST declare an auth dependency
    (or be on the explicit allowlist). A route registered without
    one is a silent privilege bug — a caller without a token gets
    the response anyway.

    The auth chain is detected by recursively walking
    `route.dependant.dependencies` and looking for a known
    auth-helper name. If the name set drifts (e.g. a new
    `require_X` helper lands), the test will need a one-line
    update — but the surfaced false-positive is an explicit signal
    a new auth shape is in play.
    """
    app = _build_app()

    # Set of auth-dependency function names we accept as evidence
    # the route is gated. `require_auth` is the basic
    # "logged-in user" check; the others are role-based or scoped
    # variants that themselves call `require_auth` under the hood.
    _AUTH_DEP_NAMES: frozenset[str] = frozenset(
        {
            # Full org-membership auth — the canonical "logged-in
            # caller, scoped to an org" gate.
            "require_auth",
            # Role / scope gates (each calls require_auth internally).
            "require_role",
            "require_min_role",
            "require_scope",
            # JWT-only (no org binding) — used by `/me/orgs`,
            # `/orgs` POST, etc. where the caller has authenticated
            # but hasn't picked / created an org yet.
            "require_user",
        }
    )

    def _has_auth_dep(dependant) -> bool:
        """Walk `dependant.dependencies` recursively. FastAPI
        flattens sub-deps lazily — we look at every layer to catch
        cases like `Depends(require_role("admin"))` where the
        outer dep wraps the inner `require_auth`.
        """
        for dep in dependant.dependencies:
            name = getattr(dep.call, "__name__", "")
            if name in _AUTH_DEP_NAMES:
                return True
            # `require_role("admin")` returns an inner closure
            # whose name is the closure's, not the outer factory's
            # — check both the .call name AND a `__qualname__` /
            # `__wrapped__` chain. In practice the closure carries
            # `require_role` in its qualname when produced via the
            # factory pattern in `middleware.auth`.
            qualname = getattr(dep.call, "__qualname__", "")
            if any(n in qualname for n in _AUTH_DEP_NAMES):
                return True
            # Recurse — FastAPI's Dependant tree can nest.
            if _has_auth_dep(dep):
                return True
        return False

    unprotected: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not path.startswith("/api/v1/"):
            continue
        if any(frag in path for frag in _AUTH_FREE_ROUTE_FRAGMENTS):
            continue
        if not _has_auth_dep(route.dependant):
            unprotected.append(f"{','.join(sorted(route.methods))} {path}")

    assert not unprotected, (
        "These /api/v1/* routes have no auth dependency:\n  "
        + "\n  ".join(unprotected)
        + "\nIf the route is intentionally public, add the relevant "
        "path fragment to `_AUTH_FREE_ROUTE_FRAGMENTS` with a one-line "
        "rationale. Otherwise add `Depends(require_auth)` (or a stricter "
        "variant) to the route signature."
    )


def test_every_api_v1_route_uses_documented_path_prefix():
    """Pin: every `APIRoute` in the app sits under one of the
    documented prefix families. A typo (`/api/v2/admin/...` instead
    of `/api/v1/...`) would silently move endpoints off the
    versioned line — frontend hooks `apiFetch("/api/v1/...")`
    would 404, browser network panels show no clear error.

    Allowed prefixes:
      * `/api/v1/...`              — the canonical versioned API
      * `/api/v1/public/...`       — token-in-URL public routes
      * `/health`, `/health/ready` — k8s probes (no /api prefix)
      * `/metrics`                 — Prometheus scrape (no /api prefix)
      * `/openapi.json`, `/docs`,
        `/redoc`                   — FastAPI's built-in surfaces
    """
    app = _build_app()
    allowed_prefixes = (
        "/api/v1/",
        "/health",
        # K8s probe spelling. `routers/ops.py` mounts these without
        # the `/api/v1` prefix because cluster probe configs default
        # to flat paths; both `/health` and `/healthz` co-exist for
        # convention compatibility.
        "/healthz",
        "/readyz",
        "/metrics",
        "/openapi.json",
        "/docs",
        "/redoc",
    )

    misshapen: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not any(path.startswith(p) for p in allowed_prefixes):
            misshapen.append(f"{','.join(sorted(route.methods))} {path}")

    assert not misshapen, (
        "These routes are outside the documented prefix set:\n  "
        + "\n  ".join(misshapen)
        + "\nIf this is intentional, add the prefix to "
        "`allowed_prefixes` above with a comment explaining why "
        "(e.g. a new probe family, a webhook receiver endpoint, etc.)."
    )
