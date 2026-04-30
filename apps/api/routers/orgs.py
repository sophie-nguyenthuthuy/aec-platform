"""Self-serve org creation.

Lives outside the tenant-scoped routers because the user has no org yet
when they land here — auth is JWT-only via `require_user`. Creating an
org also makes the caller the `owner`, mirroring the seed pattern.

Pairs with the web `/onboarding/create-org` page that the layout shows
when `/me/orgs` returns empty.
"""

from __future__ import annotations

import re
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text

from core.envelope import ok
from db.session import AdminSessionFactory
from middleware.auth import UserContext, require_user
from schemas.orgs import OrgCreate, OrgOut

router = APIRouter(prefix="/api/v1/orgs", tags=["orgs"])


_SLUG_FALLBACK_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Best-effort kebab-case slug. Strips diacritics conservatively
    (Unicode normalization is out of scope here — the validator catches
    leftover non-ASCII)."""
    s = name.strip().lower()
    s = _SLUG_FALLBACK_RE.sub("-", s).strip("-")
    return s or "org"


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_org(
    payload: OrgCreate,
    user: Annotated[UserContext, Depends(require_user)],
) -> dict:
    """Create a new org and grant the caller `owner` role.

    AdminSessionFactory bypasses RLS — necessary because (a) we're
    inserting a new org row (no existing tenant context), (b) the
    `users` row may not exist yet on the very first sign-in.
    """
    requested_slug = payload.slug or _slugify(payload.name)
    org_id = uuid4()

    async with AdminSessionFactory() as db:
        # Slug uniqueness — if taken, append the org_id suffix. This is
        # rare in practice (the slug is suggested by the user) but
        # avoids a 409 on a name collision when the user hasn't
        # explicitly chosen a slug.
        existing = (
            await db.execute(
                text("SELECT 1 FROM organizations WHERE slug = :slug"),
                {"slug": requested_slug},
            )
        ).scalar_one_or_none()

        if existing is not None and payload.slug is not None:
            # The user picked this slug explicitly — refuse to silently
            # rename. They should pick another.
            raise HTTPException(status.HTTP_409_CONFLICT, f"slug '{requested_slug}' is taken")

        slug = requested_slug
        if existing is not None:
            slug = f"{requested_slug}-{str(org_id)[:8]}"

        # Ensure a local users row exists for the creator. Mirrors what
        # /me/orgs does on first login — needed because org_members FKs
        # into users.
        await db.execute(
            text(
                """
                INSERT INTO users (id, email)
                VALUES (:id, :email)
                ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
                """
            ),
            {"id": str(user.user_id), "email": user.email},
        )

        # Insert the org row. `plan` defaults to "starter", `modules`
        # and `settings` to empty per the model defaults.
        org_row = (
            (
                await db.execute(
                    text(
                        """
                        INSERT INTO organizations (id, name, slug, country_code)
                        VALUES (:id, :name, :slug, :country)
                        RETURNING id, name, slug, plan, country_code, created_at
                        """
                    ),
                    {
                        "id": str(org_id),
                        "name": payload.name,
                        "slug": slug,
                        "country": payload.country_code,
                    },
                )
            )
            .mappings()
            .one()
        )

        # Owner membership for the creator.
        await db.execute(
            text(
                """
                INSERT INTO org_members (id, user_id, organization_id, role)
                VALUES (gen_random_uuid(), :uid, :org, 'owner')
                """
            ),
            {"uid": str(user.user_id), "org": str(org_id)},
        )

        await db.commit()

    return ok(
        OrgOut(
            id=org_row["id"],
            name=org_row["name"],
            slug=org_row["slug"],
            plan=org_row["plan"],
            country_code=org_row["country_code"],
            created_at=org_row["created_at"],
            role="owner",
        ).model_dump(mode="json")
    )
