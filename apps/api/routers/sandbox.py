"""Sandbox endpoints — synthetic-data layer for `mode='test'` API keys.

These are the routes a partner with a test-mode key hits. Same path
shape as the live equivalents (projects/defects/rfis/suppliers) under
the `/api/v1/sandbox/*` prefix so the partner's integration code can
swap a single base URL between dev and prod.

Auth: requires `require_user_or_api_key`. Live keys (and human users)
also reach these — they get the same fixtures, which is fine because
"sandbox" is documentation; production traffic should use the live
routes. We don't gate on `is_test_mode(auth)` here because:

  * A live partner who wants to spike against fixtures can
    intentionally call /sandbox without minting a test key.
  * Test-mode keys can ALSO hit live routes — those will return real
    org data (the test partner is in a real org). The sandbox is
    additive, not exclusive.

Mutations are not exposed here in v1 — the rationale is in
`services.sandbox`. Add them when a partner asks.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from core.envelope import ok
from middleware.api_key_auth import require_user_or_api_key
from middleware.auth import AuthContext
from services.sandbox import (
    sample_defects,
    sample_projects,
    sample_rfis,
    sample_suppliers,
)

router = APIRouter(prefix="/api/v1/sandbox", tags=["sandbox"])


@router.get("/projects")
async def list_sandbox_projects(
    auth: Annotated[AuthContext, Depends(require_user_or_api_key)],
) -> dict[str, Any]:
    """Three sample projects spanning planning / construction /
    completed. IDs are pinned literals so partner integration tests
    can hardcode them."""
    return ok(sample_projects())


@router.get("/defects")
async def list_sandbox_defects(
    auth: Annotated[AuthContext, Depends(require_user_or_api_key)],
) -> dict[str, Any]:
    """Two sample defects on the construction-stage project."""
    return ok(sample_defects())


@router.get("/rfis")
async def list_sandbox_rfis(
    auth: Annotated[AuthContext, Depends(require_user_or_api_key)],
) -> dict[str, Any]:
    return ok(sample_rfis())


@router.get("/suppliers")
async def list_sandbox_suppliers(
    auth: Annotated[AuthContext, Depends(require_user_or_api_key)],
) -> dict[str, Any]:
    return ok(sample_suppliers())
