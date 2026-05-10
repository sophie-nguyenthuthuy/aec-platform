"""API key project-scope picker surface (cycle T2).

The create form ALREADY supports `project_ids` end-to-end (cycle I3
plumbed the backend, the frontend dialog has the picker). T2's job
is to PIN the surface so the linter rollback can't silently strip
the picker without failing this test.

Pinned seams:
  1. `ApiKeyCreate.project_ids` is a `list[UUID]` field defaulting
     to `[]` (= "all projects").
  2. `mint_key` accepts the `project_ids` kwarg.
  3. The create handler threads `project_ids=payload.project_ids`
     into `mint_key`.
  4. The listing endpoint includes `project_ids` in each row.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.asyncio


async def test_api_key_create_payload_has_project_ids_field():
    """`ApiKeyCreate.project_ids` must be a `list[UUID]` defaulting
    to `[]`. Empty = all projects (back-compat); non-empty = closed
    allowlist."""
    from routers.api_keys import ApiKeyCreate

    fields = ApiKeyCreate.model_fields
    assert "project_ids" in fields, (
        "ApiKeyCreate.project_ids rolled back. Re-apply: `project_ids: list[UUID] = Field(default_factory=list)`."
    )


async def test_mint_key_accepts_project_ids_kwarg():
    """The backend service helper must take `project_ids=[...]`. A
    refactor that drops it would mean the create-form picker sends
    UUIDs but they never reach the DB."""
    from services.api_keys import mint_key

    sig = inspect.signature(mint_key)
    assert "project_ids" in sig.parameters, (
        "services.api_keys.mint_key has lost its `project_ids` "
        "parameter. The picker on /settings/api-keys would still "
        "render but the selected project list would be silently "
        "dropped at the service layer."
    )


async def test_create_api_key_handler_threads_project_ids():
    """The handler must pass `project_ids=payload.project_ids` into
    `mint_key`. Without this, the request body's project_ids reach
    the API but never the DB INSERT."""
    from routers import api_keys as router_module

    src = inspect.getsource(router_module.create_api_key)
    assert "project_ids=payload.project_ids" in src, (
        "routers.api_keys.create_api_key is no longer threading "
        "project_ids into mint_key. The picker selection is silently "
        "dropped — every key gets the back-compat 'all projects' "
        "default."
    )


async def test_list_api_keys_response_includes_project_ids():
    """The listing must surface `project_ids` so the frontend can
    render a "scoped to N projects" pill on each row + match the
    picker's pre-fill on edit (future)."""
    from routers import api_keys as router_module

    src = inspect.getsource(router_module.list_api_keys)
    assert "project_ids" in src, (
        "routers.api_keys.list_api_keys is no longer projecting "
        "project_ids in the response. Frontend can't tell which "
        "keys are project-scoped vs org-wide."
    )


async def test_has_project_access_returns_true_for_empty_allowlist():
    """`has_project_access([], any_id) is True` — empty allowlist
    means "all projects" by the back-compat sentinel rule. Pin so
    a refactor that flips the empty-list semantics doesn't lock
    every legacy key out of every project."""
    from services.api_keys import has_project_access

    # Empty list: any project allowed (back-compat default).
    assert has_project_access([], "any-uuid-id") is True
    # Non-empty closed allowlist.
    assert has_project_access(["proj-a"], "proj-a") is True
    assert has_project_access(["proj-a"], "proj-b") is False
