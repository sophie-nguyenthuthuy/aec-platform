"""Organisation membership management.

Permissions matrix:

  * GET    /api/v1/org/members            — any authenticated member
                                            (everyone needs to see who's
                                            in their org)
  * POST   /api/v1/org/members            — admin / owner
  * PATCH  /api/v1/org/members/{user_id}  — admin / owner
  * DELETE /api/v1/org/members/{user_id}  — admin / owner

Two safety rules baked into the handlers:
  1. You cannot remove or demote the *last* owner — would orphan the
     organisation. Test coverage explicitly asserts this.
  2. You cannot demote yourself if you're the only owner (covered by
     rule 1 — same check).

Invitation flow is intentionally minimal: we provision a `users` row
+ an `org_members` row immediately. There's no email-token round-trip
yet; the assumption is that an admin invites by an email that already
has (or will create) a Supabase auth account, and the next time that
user logs in, `/api/v1/me/orgs` shows the new membership.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role
from schemas.org import InviteMemberRequest, OrgMember, UpdateMemberRoleRequest

router = APIRouter(prefix="/api/v1/org", tags=["org"])


# ---------- List ----------


@router.get("/members")
async def list_members(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return every member of the caller's org. Visible to all roles —
    even viewers need to see who's in the team."""
    rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT m.id   AS membership_id,
                           u.id   AS user_id,
                           u.email,
                           u.full_name,
                           u.avatar_url,
                           m.role,
                           m.created_at AS joined_at
                    FROM org_members m
                    JOIN users u ON u.id = m.user_id
                    WHERE m.organization_id = :org
                    ORDER BY m.created_at
                    """
                ),
                {"org": str(auth.organization_id)},
            )
        )
        .mappings()
        .all()
    )
    return ok([OrgMember.model_validate(dict(r)).model_dump(mode="json") for r in rows])


# ---------- Invite ----------


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def invite_member(
    payload: InviteMemberRequest,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Invite a user (by email) to the org with a given role.

    Idempotent: if the email already corresponds to a member, returns
    the existing row (status 201 still — the desired end state is
    "this email is in the org with this role" either way).
    """
    # Provision a `users` row if the email is new — Supabase manages
    # the actual auth account; the local row is just an FK target.
    user_row = (
        await db.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": payload.email},
        )
    ).scalar_one_or_none()

    if user_row is None:
        user_id = uuid4()
        await db.execute(
            text("INSERT INTO users (id, email) VALUES (:id, :email)"),
            {"id": str(user_id), "email": payload.email},
        )
    else:
        user_id = user_row

    # Idempotent membership upsert — `(organization_id, user_id)` is the
    # natural key. We don't have a unique index on that pair (the table
    # was originally org-only), so do a SELECT-then-INSERT under the
    # caller's transaction.
    existing = (
        (
            await db.execute(
                text("SELECT id, role FROM org_members WHERE organization_id = :org AND user_id = :uid"),
                {"org": str(auth.organization_id), "uid": str(user_id)},
            )
        )
        .mappings()
        .first()
    )

    if existing is not None:
        membership_id = existing["id"]
    else:
        membership_id = uuid4()
        await db.execute(
            text(
                """
                INSERT INTO org_members (id, organization_id, user_id, role)
                VALUES (:id, :org, :uid, :role)
                """
            ),
            {
                "id": str(membership_id),
                "org": str(auth.organization_id),
                "uid": str(user_id),
                "role": payload.role.value,
            },
        )
    await db.commit()

    member_row = (
        (
            await db.execute(
                text(
                    """
                SELECT m.id AS membership_id, u.id AS user_id, u.email,
                       u.full_name, u.avatar_url, m.role,
                       m.created_at AS joined_at
                FROM org_members m
                JOIN users u ON u.id = m.user_id
                WHERE m.id = :mid
                """
                ),
                {"mid": str(membership_id)},
            )
        )
        .mappings()
        .one()
    )
    return ok(OrgMember.model_validate(dict(member_row)).model_dump(mode="json"))


# ---------- Update role ----------


@router.patch("/members/{user_id}")
async def update_member_role(
    user_id: UUID,
    payload: UpdateMemberRoleRequest,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Change a member's role. Cannot demote the last owner."""
    if payload.role != Role.OWNER:
        await _ensure_not_last_owner(db, auth.organization_id, user_id)

    result = await db.execute(
        text(
            """
            UPDATE org_members
            SET role = :role
            WHERE organization_id = :org AND user_id = :uid
            RETURNING id
            """
        ),
        {
            "role": payload.role.value,
            "org": str(auth.organization_id),
            "uid": str(user_id),
        },
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    await db.commit()

    member_row = (
        (
            await db.execute(
                text(
                    """
                SELECT m.id AS membership_id, u.id AS user_id, u.email,
                       u.full_name, u.avatar_url, m.role,
                       m.created_at AS joined_at
                FROM org_members m
                JOIN users u ON u.id = m.user_id
                WHERE m.organization_id = :org AND m.user_id = :uid
                """
                ),
                {"org": str(auth.organization_id), "uid": str(user_id)},
            )
        )
        .mappings()
        .one()
    )
    return ok(OrgMember.model_validate(dict(member_row)).model_dump(mode="json"))


# ---------- Remove ----------


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a member from the org. Cannot remove the last owner."""
    await _ensure_not_last_owner(db, auth.organization_id, user_id)

    await db.execute(
        text("DELETE FROM org_members WHERE organization_id = :org AND user_id = :uid"),
        {"org": str(auth.organization_id), "uid": str(user_id)},
    )
    await db.commit()
    return None


# ---------- Helpers ----------


async def _ensure_not_last_owner(
    db: AsyncSession,
    organization_id: UUID,
    target_user_id: UUID,
) -> None:
    """Guard: we never want to leave an org with zero owners.

    The check has to run BEFORE the mutation — once we've demoted /
    deleted the last owner, the org is effectively orphaned, and rolling
    back depends on the caller's transaction posture (some routers
    auto-commit). Defensive ordering here.
    """
    target_role = (
        await db.execute(
            text("SELECT role FROM org_members WHERE organization_id = :org AND user_id = :uid"),
            {"org": str(organization_id), "uid": str(target_user_id)},
        )
    ).scalar_one_or_none()
    if target_role != Role.OWNER.value:
        return  # not an owner → nothing to guard

    owner_count = (
        await db.execute(
            text("SELECT count(*) FROM org_members WHERE organization_id = :org AND role = 'owner'"),
            {"org": str(organization_id)},
        )
    ).scalar_one()
    if owner_count <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot remove or demote the last owner — promote someone else first.",
        )
