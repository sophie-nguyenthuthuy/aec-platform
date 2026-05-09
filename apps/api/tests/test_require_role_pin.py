"""Pin the auth dependency surface in `middleware.auth`.

Every protected router in this codebase declares its dependency as:

    auth: Annotated[AuthContext, Depends(require_role("admin"))]

…or `require_role("admin", "buyer")` for non-admin verticals. If the
function signature drifts (renamed, made not-variadic, made
positional-only), every protected route silently 500s on first hit
because the dependency-injection chain breaks at app startup time.

Worse: if `require_role` ever returns the unwrapped `AuthContext`
directly (instead of a dependency function), routes start running
WITHOUT auth — quietly. That's a privilege-escalation footgun, not
just a 500.

This file pins the read-only contract:

  * `require_role` is variadic on role names.
  * `require_role(*roles)` returns a *dependency function* (not the
    `AuthContext` itself).
  * The dependency raises 403 (NOT 401, NOT 500) on a role mismatch.
  * `AuthContext` carries `{user_id, organization_id, role, email,
    api_key_mode, api_key_id, api_key_project_ids}` — every
    multi-tenant enforcement point reads at least `organization_id`
    + `role` from this object.
  * `require_user` (the no-org-context path) returns `UserContext`
    with `{user_id, email}` — used by `/me/orgs` etc. before an
    org is pinned.

If any of these flip, the change has to be deliberate AND every
route's annotation has to migrate. Pin signals the breakage early.
"""

from __future__ import annotations

import inspect
from dataclasses import is_dataclass
from uuid import uuid4

import pytest

# ---------- AuthContext shape ----------


def test_auth_context_is_frozen_dataclass():
    """`AuthContext` is `@dataclass(frozen=True)`. Frozen because:

      * Routes pass it through async stacks; if a downstream mutation
        could change `organization_id`, RLS scoping would silently
        leak data across orgs.
      * The api-key-projects path uses it as a dict key (cache key
        for per-key throttle counters) — needs hashability, which
        frozen+tuple-fields gives us.

    A regression to a regular `class` with mutable fields = silent
    cross-tenant data exposure on the worst day.
    """
    from middleware.auth import AuthContext

    assert is_dataclass(AuthContext), "AuthContext MUST be a dataclass — frozen + hashable contract."

    # Construct one and verify mutation raises.
    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="admin",
        email="ops@example.com",
    )
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        ctx.role = "buyer"  # type: ignore[misc]


def test_auth_context_field_set():
    """Pin the field set. RLS enforcement reads `organization_id` and
    `role`; api-key throttling reads `api_key_id` + `api_key_mode`;
    per-project scoping reads `api_key_project_ids`. Renaming any
    of these silently breaks the corresponding enforcement path."""
    from middleware.auth import AuthContext

    fields = {f.name for f in AuthContext.__dataclass_fields__.values()}
    expected = {
        "user_id",
        "organization_id",
        "role",
        "email",
        "api_key_mode",
        "api_key_id",
        "api_key_project_ids",
    }
    assert fields == expected, f"AuthContext fields drifted: have {fields}, want {expected}"


def test_auth_context_api_key_project_ids_default_is_empty_tuple():
    """`api_key_project_ids` defaults to `()` to mean "all projects"
    (back-compat with keys minted before the per-project allowlist
    landed). MUST be a tuple, not a list — the frozen dataclass
    needs hashable fields, and a list would crash on the dict-key
    use case.
    """
    from middleware.auth import AuthContext

    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="admin",
        email="ops@example.com",
    )
    assert ctx.api_key_project_ids == ()
    assert isinstance(ctx.api_key_project_ids, tuple), (
        f"api_key_project_ids type is {type(ctx.api_key_project_ids).__name__}; "
        "MUST be tuple for hashability + immutability."
    )

    # The frozen dataclass must remain hashable (per-key throttle
    # cache uses it as a dict key).
    hash(ctx)


def test_auth_context_api_key_mode_default():
    """The api-key-vs-user discriminator. User-JWT callers leave it
    at `"live"` so route logic that doesn't care about api-key mode
    still works without conditionals. A regression that defaulted
    to `None` or `"test"` would silently route every request through
    the test-key code path."""
    from middleware.auth import AuthContext

    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="admin",
        email="ops@example.com",
    )
    assert ctx.api_key_mode == "live"
    assert ctx.api_key_id is None


# ---------- require_role contract ----------


def test_require_role_is_variadic_on_role_names():
    """Routes call `require_role("admin")` and `require_role("admin",
    "buyer")` etc. The signature MUST accept variadic strings. A
    regression to `require_role(role: str)` would silently break
    every multi-role gate (and break them in a way pyright/mypy
    catches — but only if they're run, which the revert pattern
    can quietly disable).
    """
    from middleware.auth import require_role

    sig = inspect.signature(require_role)
    params = list(sig.parameters.values())
    assert len(params) == 1, f"require_role signature drifted: {[p.name for p in params]}"
    assert params[0].kind is inspect.Parameter.VAR_POSITIONAL, (
        f"require_role's role-list parameter is `{params[0].kind.name}`, want VAR_POSITIONAL (`*allowed`)."
    )


def test_require_role_returns_a_dependency_function():
    """CRITICAL security pin. `require_role(*roles)` MUST return a
    dependency *function* that FastAPI then calls per-request. If
    a regression made it return `AuthContext` directly (or `None`),
    every protected route would either:

      * Run without auth (the value is truthy, FastAPI skips the
        dep-resolution entirely on second hit) — privilege escalation.
      * Or 500 immediately — at which point we'd notice. The first
        case is the dangerous one.

    Pin: the return value MUST be callable AND async."""
    from middleware.auth import require_role

    dep = require_role("admin")
    assert callable(dep), "require_role MUST return a callable dependency."
    assert inspect.iscoroutinefunction(dep), (
        "require_role's returned dependency MUST be async — sync would silently no-op the auth check on async stacks."
    )


def test_require_role_dep_signature_takes_authcontext_via_depends():
    """The returned dep takes an `AuthContext` via `Depends(require_auth)`.
    If the parameter name drifts (e.g. `auth` instead of `ctx`),
    FastAPI's dependency cache continues to work BUT the role check
    silently no-ops if the param isn't an AuthContext.
    """
    import typing

    from middleware.auth import AuthContext, require_role

    dep = require_role("admin")
    sig = inspect.signature(dep)
    params = list(sig.parameters.values())
    assert len(params) == 1, f"require_role's dep takes {len(params)} params; want exactly 1 (AuthContext)."
    # `middleware/auth.py` has `from __future__ import annotations` so
    # the param annotation is a string at runtime — resolve via
    # `get_type_hints` to compare against the actual class.
    hints = typing.get_type_hints(dep)
    annotated_type = hints.get(params[0].name)
    assert annotated_type is AuthContext, (
        f"require_role's dep param `{params[0].name}` resolves to "
        f"{annotated_type!r}; want AuthContext so FastAPI's dep-resolver "
        "runs `require_auth` to populate it."
    )


@pytest.mark.asyncio
async def test_require_role_raises_403_on_role_mismatch():
    """Mismatch returns HTTP 403 — NOT 401 (which would imply "log in
    again" in the frontend toast logic) and NOT 500 (which would
    surface as "platform error, try later" copy). Pin the status
    code so the frontend's role-mismatch toast keeps its meaning.
    """
    from fastapi import HTTPException, status

    from middleware.auth import AuthContext, require_role

    dep = require_role("admin")
    member_ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="member",  # NOT admin — should be denied
        email="member@example.com",
    )

    with pytest.raises(HTTPException) as exc_info:
        await dep(member_ctx)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_require_role_lets_matching_role_through():
    """Happy path. The dep returns the AuthContext unchanged so the
    route's `auth: Annotated[AuthContext, ...]` parameter receives
    it. A regression that returned a wrapped/coerced object would
    break every router that reads `auth.organization_id` directly.
    """
    from middleware.auth import AuthContext, require_role

    dep = require_role("admin")
    admin_ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="admin",
        email="admin@example.com",
    )

    out = await dep(admin_ctx)
    assert out is admin_ctx, (
        "require_role's dep MUST return the AuthContext unchanged — "
        "routes read .organization_id / .user_id directly off it."
    )


@pytest.mark.asyncio
async def test_require_role_admits_any_listed_role():
    """`require_role("admin", "buyer")` is the multi-role pattern
    used by routes that allow either a buyer (project owner) or
    an admin (cross-tenant escalation). MUST admit either."""
    from middleware.auth import AuthContext, require_role

    dep = require_role("admin", "buyer")

    for role in ("admin", "buyer"):
        ctx = AuthContext(
            user_id=uuid4(),
            organization_id=uuid4(),
            role=role,
            email=f"{role}@example.com",
        )
        out = await dep(ctx)
        assert out is ctx


# ---------- UserContext / require_user (no-org path) ----------


def test_user_context_field_set():
    """`UserContext` is the JWT-validated-but-no-org-pinned context.
    Used by `/me/orgs` (the org switcher) — needs to work BEFORE
    an org is pinned. Tighter shape than AuthContext so we can't
    accidentally read `.organization_id` off it.
    """
    from middleware.auth import UserContext

    assert is_dataclass(UserContext)
    fields = {f.name for f in UserContext.__dataclass_fields__.values()}
    assert fields == {"user_id", "email"}, (
        f"UserContext fields drifted: have {fields}, want "
        "{user_id, email} — keep it tighter than AuthContext "
        "so accidentally reading .organization_id raises."
    )


def test_user_context_does_not_carry_org_id():
    """Defensive: a regression that added `organization_id` here
    would let a `/me/*` route accidentally read it (defaulting to
    None, then probably crashing on str() conversion later). Better
    to fail at attribute-access time than silently default."""
    from middleware.auth import UserContext

    fields = {f.name for f in UserContext.__dataclass_fields__.values()}
    assert "organization_id" not in fields, (
        "UserContext gained `organization_id`. That would let pre-org "
        "endpoints accidentally read it; use AuthContext for org-scoped "
        "routes instead."
    )


def test_require_user_signature_pinned():
    """`require_user` is the dep used by `/me/*`. Must remain async,
    must remain a single-credential parameter (no X-Org-ID required —
    that's the whole point)."""
    from middleware.auth import require_user

    assert inspect.iscoroutinefunction(require_user), "require_user MUST be async — used as a FastAPI dep."
    sig = inspect.signature(require_user)
    # Just one param (the bearer credentials); no X-Org-ID header
    # because this dep MUST work before an org is pinned.
    params = list(sig.parameters.keys())
    assert params == ["credentials"], (
        f"require_user signature drifted: {params}. Adding an "
        "X-Org-ID header dep here would break the org-switcher path."
    )
