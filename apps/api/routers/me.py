"""Identity endpoints — work without an X-Org-ID pin.

These exist because the dashboard layout needs to know which orgs the
authenticated user belongs to *before* it can pick a default org and start
sending the X-Org-ID header that every other tenant-scoped endpoint
requires. The org switcher feeds off the same data.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text

from core.envelope import ok
from core.rate_limit import rate_limit
from db.session import AdminSessionFactory
from middleware.auth import UserContext, require_user

router = APIRouter(prefix="/api/v1/me", tags=["me"])


# Per-user limiter — every dashboard render hits /me/orgs once at SSR.
# 60/min is comfortably above legitimate usage (page reload + minute of
# org switches), well below abuse. Keying on user_id rather than IP
# means a corporate NAT doesn't share the bucket across employees.
def _user_key(user: UserContext = Depends(require_user)) -> str:
    return str(user.user_id)


_me_orgs_limiter = rate_limit(prefix="me-orgs", limit=60, window_sec=60, key_dep=Depends(_user_key))


@router.get("/orgs", dependencies=[Depends(_me_orgs_limiter)])
async def list_my_orgs(
    user: Annotated[UserContext, Depends(require_user)],
) -> dict:
    """Every org this user is a member of, with their role.

    Also auto-provisions a `users` row for first-time Supabase logins —
    Supabase manages auth but our `org_members.user_id` FKs into the local
    `users` table, so we need a row there before any org membership lookup
    can succeed. Membership grants live in the local DB (seeded or
    invitation-driven); without a grant, this endpoint returns an empty
    list and the UI shows an "ask an admin to invite you" empty state.
    """
    # AdminSessionFactory bypasses RLS — necessary because (a) we need to
    # write to `users` regardless of the future tenant scope, and (b) the
    # `org_members` query runs without an `app.current_org_id` GUC pin.
    async with AdminSessionFactory() as db:
        await db.execute(
            text(
                """
                INSERT INTO users (id, email)
                VALUES (:uid, :email)
                ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
                """
            ),
            {"uid": str(user.user_id), "email": user.email},
        )
        await db.commit()

        rows = (
            (
                await db.execute(
                    text(
                        """
                    SELECT o.id::text AS id, o.name, m.role
                    FROM org_members m
                    JOIN organizations o ON o.id = m.organization_id
                    WHERE m.user_id = :uid
                    ORDER BY o.name
                    """
                    ),
                    {"uid": str(user.user_id)},
                )
            )
            .mappings()
            .all()
        )

    return ok([dict(r) for r in rows])
