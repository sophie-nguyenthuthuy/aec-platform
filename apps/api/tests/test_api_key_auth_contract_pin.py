"""Pin the `middleware.api_key_auth` contract.

This middleware is the security boundary for partner API access. A
silent regression here has two distinct failure modes:

  * **Auth bypass** — a regression that returned an `AuthContext`
    without verifying the api-key would let unauthenticated callers
    through. Worst-case privilege escalation: an attacker submits
    `Authorization: Bearer aec_anything`, the verifier silently no-ops,
    and they hit the API with whatever role the synthesised context
    carries.

  * **Auth lockout** — a regression that 401'd legitimate api-keys
    would break every partner integration the moment it deploys. The
    failure is loud (partner sees 401s), but the rollback path
    requires waking up on-call.

Three layers of defence-in-depth this file pins:

  1. **Routing.** `require_user_or_api_key` MUST dispatch on the
     `aec_` prefix. A token starting with `aec_` goes to the api-key
     branch; anything else defers to `require_auth` for JWT
     verification. A regression that always defers to `require_auth`
     would 401 every api-key call (loud); a regression that always
     takes the api-key branch would crash on JWT inputs (loud, but
     a different failure mode that users notice as "auth broken").

  2. **AuthContext synthesis.** Api-key callers get
     `role="api_key"`, `email=""`, `api_key_id=<id>`. The
     `require_role("admin")` gate elsewhere in the codebase
     specifically checks `role` — a regression that synthesised
     `role="admin"` for api-key callers would silently grant every
     api-key full admin power.

  3. **Scope + project gates.** `require_scope` and
     `require_project_scope` MUST be no-ops for user-JWT callers
     (their access is gated by org-level RBAC), AND MUST enforce
     for api-key callers. A regression that flipped either branch
     would either lock out legitimate users or give api-keys
     unscoped access.

This file is read-only — it imports the module and tests the pure
parts (signatures, return shapes) plus the role-gate branch
behaviour via a stub AuthContext. The DB-touching paths
(`_api_key_auth`'s `verify_key` call) aren't pinned here because
they need a real session; they're covered by the existing api-key
integration tests elsewhere.

Pinned contracts:

  * Module + all four public dependencies importable.
  * `require_user_or_api_key` signature stable.
  * `require_user_or_api_key` is async + uses `aec_` prefix
    discriminator.
  * `_api_key_auth` synthesises `role="api_key"` (NOT `"admin"`,
    NOT `"member"` — anything else is privilege drift).
  * `require_scope("x")` returns a callable async dependency.
  * `require_scope` no-ops for non-api-key callers (user-JWT
    callers' role gating happens elsewhere).
  * `require_scope` raises 403 for api-key callers missing the scope.
  * `require_project_scope` returns a callable async dependency.
  * `require_project_scope` no-ops for non-api-key callers AND for
    api-key callers with empty allowlists (back-compat).
  * `require_project_scope` raises 403 with
    `project_not_in_key_allowlist` when access is denied.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

# ---------- Module presence ----------


def test_api_key_auth_module_imports():
    """All public surfaces importable. A revert that deleted any of
    them surfaces here as a hard ImportError on the next CI run —
    desired loud-fail signal vs silently broken partner auth."""
    from middleware.api_key_auth import (  # noqa: F401
        require_project_scope,
        require_scope,
        require_user_or_api_key,
    )


# ---------- require_user_or_api_key signature + shape ----------


def test_require_user_or_api_key_is_async():
    """Awaited as a FastAPI dependency. A sync regression would
    silently no-op (await on non-coro returns the function ref AND
    skips the verification entirely)."""
    from middleware.api_key_auth import require_user_or_api_key

    assert inspect.iscoroutinefunction(require_user_or_api_key), (
        "require_user_or_api_key MUST be async — FastAPI's dependency "
        "resolver awaits it; a sync regression silently skips auth."
    )


def test_require_user_or_api_key_signature_pinned():
    """`(request, credentials, x_org_id=None)`. FastAPI's resolver
    binds these by parameter name — a rename of `credentials` or
    `x_org_id` would break the dep wiring on every protected route.
    """
    from middleware.api_key_auth import require_user_or_api_key

    sig = inspect.signature(require_user_or_api_key)
    params = list(sig.parameters.keys())
    assert params == ["request", "credentials", "x_org_id"], (
        f"require_user_or_api_key signature drifted: {params}. "
        "FastAPI binds these by name; a rename breaks every "
        "protected partner-API route."
    )


def test_require_user_or_api_key_dispatches_on_aec_prefix():
    """SECURITY-CRITICAL pin. The branch that decides "is this an
    api-key or a JWT?" MUST key on the `aec_` prefix. A regression
    that always took one branch would either 401 every legitimate
    api-key call OR crash on JWT inputs — both observable, but the
    branch logic itself is what the rest of the security model
    depends on.

    We pin via source-grep rather than dynamic invocation because
    the dynamic path requires DB + Redis fixtures.
    """
    import middleware.api_key_auth as mod

    src = inspect.getsource(mod.require_user_or_api_key)

    assert "KEY_PREFIX" in src, (
        "require_user_or_api_key no longer references KEY_PREFIX. "
        "The api-key-vs-JWT discriminator MUST key on the documented "
        "`aec_` prefix; a regression here is a routing bug at the "
        "auth layer."
    )
    assert "startswith" in src, (
        "require_user_or_api_key no longer uses prefix matching. "
        "The KEY_PREFIX import isn't used as a prefix check — "
        "the dispatch logic has drifted."
    )


# ---------- AuthContext synthesis (role pin) ----------


def test_api_key_branch_synthesises_role_api_key():
    """SECURITY-CRITICAL pin. The api-key branch MUST set
    `role="api_key"` on the synthesised AuthContext. A regression
    that set `role="admin"` would silently grant every partner
    api-key full platform-admin access — `require_role("admin")`
    elsewhere checks the literal string.

    We pin via source-grep because the dynamic path needs DB
    fixtures. The grep is sufficient because:
      * The role-string assignment in `_api_key_auth` is the only
        place in the module that builds an AuthContext.
      * A regression that moved the role assignment elsewhere AND
        kept the literal would still pass this grep, which is a
        false negative — but the cost is low compared to the cost
        of a privilege-escalation regression going undetected.
    """
    import middleware.api_key_auth as mod

    src = inspect.getsource(mod._api_key_auth)
    assert 'role="api_key"' in src or "role='api_key'" in src, (
        '_api_key_auth no longer synthesises role="api_key" on the '
        'AuthContext. SECURITY: a drift to "admin"/"member"/etc. '
        "would silently grant api-key callers elevated privileges "
        "that bypass the require_role gate everywhere else."
    )


def test_api_key_branch_synthesises_empty_email():
    """The synthesised AuthContext for api-key callers has
    `email=""` — there's no human attached. Audit-log writers
    grep for `email == ""` to detect "system actor" rows; a
    regression that defaulted to a placeholder string ("api-key"
    or similar) would corrupt the audit-log filtering."""
    import middleware.api_key_auth as mod

    src = inspect.getsource(mod._api_key_auth)
    assert 'email=""' in src, (
        '_api_key_auth no longer sets email="" on the api-key '
        "AuthContext. The audit log uses empty-email as the system-"
        "actor discriminator — a placeholder string drifts that "
        "filtering logic."
    )


# ---------- require_scope ----------


def test_require_scope_returns_a_dependency_function():
    """`require_scope("x")` MUST return a callable async dep. A
    regression that returned `None` or a bare value would either
    silently no-op (allow all callers) or break FastAPI's
    dep-resolution at startup.
    """
    from middleware.api_key_auth import require_scope

    dep = require_scope("projects:read")
    assert callable(dep), "require_scope MUST return a callable dependency — FastAPI's resolver calls it per-request."
    assert inspect.iscoroutinefunction(dep), (
        "require_scope's returned dependency MUST be async — sync would silently no-op the scope check on async stacks."
    )


@pytest.mark.asyncio
async def test_require_scope_no_ops_for_user_callers():
    """User-JWT callers (role != "api_key") MUST pass through
    `require_scope` unconditionally. Their access is gated by
    org-level RBAC at the route level; api-key scopes don't apply
    to them.

    A regression that gated user callers on api-key scopes would
    lock every logged-in user out of the gated routes (loud) — but
    the inverse regression (gating api-key callers as if they were
    users) would silently waive the scope check for partner
    integrations. Pin both branches.
    """
    from fastapi import Request

    from middleware.api_key_auth import require_scope
    from middleware.auth import AuthContext

    user_ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="admin",  # NOT "api_key" — user-JWT path
        email="user@example.com",
    )

    dep = require_scope("projects:read")
    # Build a minimal Request stub; require_scope reads `request.state`
    # only when role == "api_key", so user-path can ignore it.
    fake_request = Request({"type": "http", "method": "GET", "headers": []})

    # MUST NOT raise — user callers no-op.
    out = await dep(fake_request, user_ctx)
    assert out is None


@pytest.mark.asyncio
async def test_require_scope_raises_403_when_api_key_lacks_scope():
    """SECURITY pin. An api-key caller without the requested scope
    MUST be 403'd with `missing_scope: <scope>` in the detail.
    A regression that 200'd here would silently grant unscoped
    access to every gated route.
    """
    from fastapi import HTTPException, Request, status

    from middleware.api_key_auth import require_scope
    from middleware.auth import AuthContext

    api_key_ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="api_key",
        email="",
        api_key_id=uuid4(),
    )

    dep = require_scope("projects:read")
    # Empty scopes on request.state.
    fake_request = Request({"type": "http", "method": "GET", "headers": []})
    fake_request.state.api_key_scopes = []  # explicitly empty

    with pytest.raises(HTTPException) as exc_info:
        await dep(fake_request, api_key_ctx)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "missing_scope" in str(exc_info.value.detail)
    assert "projects:read" in str(exc_info.value.detail)


# ---------- require_project_scope ----------


def test_require_project_scope_returns_dependency_function():
    """Same async-callable contract as `require_scope`."""
    from middleware.api_key_auth import require_project_scope

    dep = require_project_scope("project_id")
    assert callable(dep)
    assert inspect.iscoroutinefunction(dep)


@pytest.mark.asyncio
async def test_require_project_scope_no_ops_for_user_callers():
    """User-JWT callers pass through unconditionally — RLS handles
    their per-project access. A regression that gated users would
    break every logged-in user's drill-down (loud)."""

    from middleware.api_key_auth import require_project_scope
    from middleware.auth import AuthContext

    user_ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="admin",
        email="user@example.com",
    )

    dep = require_project_scope("project_id")
    # No path/query params needed — user path skips the check.
    fake_request = SimpleNamespace(
        path_params={},
        query_params={},
    )

    out = await dep(fake_request, user_ctx)
    assert out is None


@pytest.mark.asyncio
async def test_require_project_scope_no_ops_when_allowlist_empty():
    """BACK-COMPAT pin. Api-keys minted before migration 0039
    (per-project scopes) have an empty `api_key_project_ids` tuple
    — that's the documented "all projects" sentinel. A regression
    that 403'd on empty allowlist would break every legacy api-key
    until the partner re-mints with explicit scopes.
    """
    from middleware.api_key_auth import require_project_scope
    from middleware.auth import AuthContext

    api_key_ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="api_key",
        email="",
        api_key_id=uuid4(),
        api_key_project_ids=(),  # empty = "all projects"
    )

    dep = require_project_scope("project_id")
    # Path param value present — but the allowlist is empty so the
    # check is supposed to short-circuit.
    fake_request = SimpleNamespace(
        path_params={"project_id": str(uuid4())},
        query_params={},
    )

    out = await dep(fake_request, api_key_ctx)
    assert out is None, (
        "require_project_scope did not short-circuit on empty allowlist. "
        "Legacy api-keys (pre-migration-0039) have empty tuples by "
        "design — a 403 here breaks every partner that hasn't re-minted."
    )


@pytest.mark.asyncio
async def test_require_project_scope_403s_with_allowlist_violation():
    """SECURITY pin. An api-key with a non-empty allowlist hitting
    a project NOT in that allowlist MUST be 403'd with the literal
    `project_not_in_key_allowlist` string. A regression that 200'd
    or threw a generic 403 would either grant cross-project access
    OR confuse the partner debugging the integration."""
    from fastapi import HTTPException, status

    from middleware.api_key_auth import require_project_scope
    from middleware.auth import AuthContext

    allowed = UUID("11111111-1111-1111-1111-111111111111")
    requested = UUID("22222222-2222-2222-2222-222222222222")

    api_key_ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="api_key",
        email="",
        api_key_id=uuid4(),
        api_key_project_ids=(allowed,),
    )

    dep = require_project_scope("project_id")
    fake_request = SimpleNamespace(
        path_params={"project_id": str(requested)},
        query_params={},
    )

    with pytest.raises(HTTPException) as exc_info:
        await dep(fake_request, api_key_ctx)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "project_not_in_key_allowlist"


@pytest.mark.asyncio
async def test_require_project_scope_403s_when_param_missing():
    """Defensive: if the route doesn't actually have the named
    project_id param, fail closed (403, not 200). The router
    author needs to fix the param name; better to break loud
    than silently allow cross-project access through a typo.
    """
    from fastapi import HTTPException, status

    from middleware.api_key_auth import require_project_scope
    from middleware.auth import AuthContext

    api_key_ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="api_key",
        email="",
        api_key_id=uuid4(),
        api_key_project_ids=(uuid4(),),
    )

    dep = require_project_scope("project_id")
    fake_request = SimpleNamespace(
        path_params={},  # the route author forgot to declare the param
        query_params={},
    )

    with pytest.raises(HTTPException) as exc_info:
        await dep(fake_request, api_key_ctx)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "missing_project_id_param" in str(exc_info.value.detail)


# ---------- Custom param-name support ----------


@pytest.mark.asyncio
async def test_require_project_scope_accepts_custom_param_name():
    """Routes can pass a custom param name (e.g. "rfq_project_id").
    The dep MUST read from path_params keyed on that exact name.
    A regression that hardcoded "project_id" would silently 403
    every route that used a custom name."""
    from middleware.api_key_auth import require_project_scope
    from middleware.auth import AuthContext

    pid = UUID("11111111-1111-1111-1111-111111111111")

    api_key_ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="api_key",
        email="",
        api_key_id=uuid4(),
        api_key_project_ids=(pid,),
    )

    dep = require_project_scope("rfq_project_id")
    fake_request = SimpleNamespace(
        path_params={"rfq_project_id": str(pid)},
        query_params={},
    )

    # MUST NOT raise — custom name accepted, allowlist matches.
    await dep(fake_request, api_key_ctx)
