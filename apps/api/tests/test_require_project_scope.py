"""Behavioural tests for `middleware.api_key_auth.require_project_scope`.

The dependency exists in production code and is pinned by
`test_integrator_surface_snapshot.py`. This file goes one layer
deeper: it actually MOUNTS routes wired to the dependency and asserts
the four canonical outcomes:

  1. User-JWT caller → bypass (no-op; users have org-level RBAC).
  2. Api-key with empty `api_key_project_ids` → bypass (all-projects
     sentinel, the back-compat default for pre-0039 keys).
  3. Api-key with `project_id` in the allowlist → pass through.
  4. Api-key with `project_id` NOT in the allowlist → 403.

Plus three edge cases that have caused regressions in similar gates:

  5. The dependency reads `project_id` from the query string when
     the route has it there (not just path params).
  6. The dependency accepts a renamed param name via
     `require_project_scope("pid")`.
  7. A route gated on `require_project_scope()` but without the
     declared param fails closed (403, not silent allow) — keeps a
     misuse from accidentally widening access.

This is the "drop-in confidently" battery. When you're about to add
`Depends(require_project_scope())` to a real route, this file is what
you'd duplicate-and-edit to verify the gate matches your route's
shape.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient

from middleware.api_key_auth import require_project_scope, require_user_or_api_key
from middleware.auth import AuthContext

ORG_ID = UUID("00000000-0000-0000-0000-000000000aaa")
USER_ID = UUID("00000000-0000-0000-0000-000000000bbb")
KEY_ID = UUID("00000000-0000-0000-0000-000000000ccc")
SCOPED_PROJECT = UUID("00000000-0000-0000-0000-000000000111")
OTHER_PROJECT = UUID("00000000-0000-0000-0000-000000000222")


def _build_app(auth_ctx: AuthContext, *, param_name: str = "project_id", path: str | None = None) -> FastAPI:
    """Mount a tiny app with a single project-scoped GET. Default path
    `/projects/{project_id}/things` is the convention every per-project
    route in the codebase follows."""
    app = FastAPI()
    real_path = path or f"/projects/{{{param_name}}}/things"

    @app.get(real_path)
    async def _handler(
        _auth: AuthContext = Depends(require_user_or_api_key),
        _gate: None = Depends(require_project_scope(param_name)),
    ):
        return {"ok": True}

    app.dependency_overrides[require_user_or_api_key] = lambda: auth_ctx
    return app


# ---------- Case 1: user-JWT caller bypasses --------------------------


def test_user_jwt_caller_passes_regardless_of_path_project_id():
    """Users have org-level RBAC; the dependency is a no-op for them.
    A scoped api-key would 403 on `OTHER_PROJECT`, but a user must
    succeed because their access posture comes from RLS + role, not
    the api-key allowlist."""
    user_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="caller@example.com",
        # Even setting a non-empty allowlist on a user ctx must NOT
        # gate them — the field's only meaningful for api-key callers.
        api_key_project_ids=(SCOPED_PROJECT,),
    )
    app = _build_app(user_ctx)
    client = TestClient(app)
    res = client.get(f"/projects/{OTHER_PROJECT}/things")
    assert res.status_code == 200, res.text


# ---------- Case 2: api-key, empty allowlist = all projects ----------


def test_api_key_with_empty_allowlist_accesses_any_project():
    """Empty `api_key_project_ids` is the back-compat sentinel: the
    key was minted before per-project scoping or was deliberately not
    scoped. It MUST behave as "all projects" — gating it would break
    every existing partner integration."""
    api_ctx = AuthContext(
        user_id=KEY_ID,
        organization_id=ORG_ID,
        role="api_key",
        email="",
        api_key_id=KEY_ID,
        api_key_project_ids=(),  # ← empty = all
    )
    app = _build_app(api_ctx)
    client = TestClient(app)
    res = client.get(f"/projects/{OTHER_PROJECT}/things")
    assert res.status_code == 200, res.text


# ---------- Case 3: api-key, project_id IN allowlist ----------


def test_api_key_with_matching_project_id_passes():
    api_ctx = AuthContext(
        user_id=KEY_ID,
        organization_id=ORG_ID,
        role="api_key",
        email="",
        api_key_id=KEY_ID,
        api_key_project_ids=(SCOPED_PROJECT, OTHER_PROJECT),
    )
    app = _build_app(api_ctx)
    client = TestClient(app)
    res = client.get(f"/projects/{SCOPED_PROJECT}/things")
    assert res.status_code == 200, res.text


# ---------- Case 4: api-key, project_id NOT in allowlist → 403 ----------


def test_api_key_with_non_matching_project_id_is_forbidden():
    """The headline case — a partner's scoped key tries to access a
    project outside its allowlist. Gate must 403 with the
    `project_not_in_key_allowlist` marker so the partner's debug log
    shows "this key isn't scoped to that project" rather than a
    generic forbidden."""
    api_ctx = AuthContext(
        user_id=KEY_ID,
        organization_id=ORG_ID,
        role="api_key",
        email="",
        api_key_id=KEY_ID,
        api_key_project_ids=(SCOPED_PROJECT,),  # only this one
    )
    app = _build_app(api_ctx)
    client = TestClient(app)
    res = client.get(f"/projects/{OTHER_PROJECT}/things")
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "project_not_in_key_allowlist" in res.text


# ---------- Edge case 5: query-string project_id ----------


def test_dependency_reads_project_id_from_query_string():
    """Some endpoints take project_id as a query param (e.g. a search
    that filters across projects). The dependency must read either
    location so a route author isn't forced to add a path param just
    to use the gate."""
    api_ctx = AuthContext(
        user_id=KEY_ID,
        organization_id=ORG_ID,
        role="api_key",
        email="",
        api_key_id=KEY_ID,
        api_key_project_ids=(SCOPED_PROJECT,),
    )
    app = FastAPI()

    @app.get("/things")
    async def _handler(
        project_id: UUID,
        _auth: AuthContext = Depends(require_user_or_api_key),
        _gate: None = Depends(require_project_scope()),
    ):
        return {"project_id": str(project_id)}

    app.dependency_overrides[require_user_or_api_key] = lambda: api_ctx
    client = TestClient(app)

    # Allowed project — pass.
    res = client.get(f"/things?project_id={SCOPED_PROJECT}")
    assert res.status_code == 200

    # Disallowed project — 403.
    res = client.get(f"/things?project_id={OTHER_PROJECT}")
    assert res.status_code == 403


# ---------- Edge case 6: renamed param ----------


def test_dependency_accepts_renamed_param_name():
    """`require_project_scope('pid')` should gate on a path/query
    param literally named `pid`. Lets routes adopt the gate without
    renaming their existing param."""
    api_ctx = AuthContext(
        user_id=KEY_ID,
        organization_id=ORG_ID,
        role="api_key",
        email="",
        api_key_id=KEY_ID,
        api_key_project_ids=(SCOPED_PROJECT,),
    )
    app = _build_app(api_ctx, param_name="pid")
    client = TestClient(app)
    res = client.get(f"/projects/{OTHER_PROJECT}/things")
    assert res.status_code == 403


# ---------- Edge case 7: misuse fails closed ----------


def test_route_without_declared_param_fails_closed_403():
    """A route author wires `Depends(require_project_scope())` but
    forgets to declare a `project_id` path/query param. The gate
    can't read a value to check — fail closed (403), don't silently
    let the request through. Better to flag the misconfiguration
    than to accidentally widen access."""
    api_ctx = AuthContext(
        user_id=KEY_ID,
        organization_id=ORG_ID,
        role="api_key",
        email="",
        api_key_id=KEY_ID,
        api_key_project_ids=(SCOPED_PROJECT,),
    )
    app = FastAPI()

    @app.get("/things")
    async def _handler(
        _auth: AuthContext = Depends(require_user_or_api_key),
        _gate: None = Depends(require_project_scope()),
    ):
        return {"ok": True}

    app.dependency_overrides[require_user_or_api_key] = lambda: api_ctx
    client = TestClient(app)
    res = client.get("/things")
    assert res.status_code == 403
    assert "missing_project_id_param" in res.text
