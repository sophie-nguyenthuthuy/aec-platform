"""First-run onboarding endpoints.

Today's only endpoint: `POST /api/v1/onboarding/seed-demo`. Hits the
same per-org seed routines that `scripts.seed_demo` uses, but writes
to the *caller's* org instead of the script's hardcoded `demo-co`.

This is the API behind the empty-state CTA on `/projects` — a fresh
tenant that's never created any data lands on a dashboard with zero
rows, and one click here populates a sample project with a proposal,
an approved estimate, two change orders, two RFIs, two defects, and
five site visits with photos.

Idempotent. Re-running on an already-seeded org is a no-op (every
seeder upserts on a stable natural key — title / number / name).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from core.envelope import ok
from db.session import TenantAwareSession
from middleware.auth import AuthContext
from middleware.rbac import Role, require_min_role

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


@router.post("/seed-demo", status_code=202)
async def seed_demo_into_caller_org(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """Populate the caller's org with a sample project + cross-module
    fixtures. Admin/owner only — seeding implies write access to every
    module the script touches.

    Returns the seeded project id so the frontend can navigate
    straight to its detail page after the call settles.
    """
    # Lazy import the seeders so this router doesn't pull `random` /
    # the full SQL block into module-load time of every other request.
    from scripts.seed_demo import (
        _seed_change_orders,
        _seed_defects,
        _seed_estimate,
        _seed_incidents,
        _seed_photos,
        _seed_progress,
        _seed_proposal,
        _seed_rfis,
        _seed_visits,
        _upsert_project,
    )

    org_id = auth.organization_id
    user_id = auth.user_id

    async with TenantAwareSession(org_id) as session:
        project_id = await _upsert_project(session, org_id=org_id)
        visit_ids = await _seed_visits(session, org_id=org_id, project_id=project_id, user_id=user_id)
        photo_ids = await _seed_photos(session, org_id=org_id, project_id=project_id, visit_ids=visit_ids)
        await _seed_progress(session, org_id=org_id, project_id=project_id, photo_ids=photo_ids)
        await _seed_incidents(session, org_id=org_id, project_id=project_id, photo_ids=photo_ids)
        await _seed_proposal(session, org_id=org_id, project_id=project_id, user_id=user_id)
        await _seed_estimate(session, org_id=org_id, project_id=project_id, user_id=user_id)
        await _seed_change_orders(session, org_id=org_id, project_id=project_id, user_id=user_id)
        await _seed_rfis(session, org_id=org_id, project_id=project_id, user_id=user_id)
        await _seed_defects(session, org_id=org_id, project_id=project_id, user_id=user_id)

    return ok({"project_id": str(project_id), "status": "seeded"})
