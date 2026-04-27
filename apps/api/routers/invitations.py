"""Invitation flow endpoints.

Two surfaces with very different trust:
  * `POST /api/v1/orgs/{org_id}/invitations` — admin/owner only, behind
    `require_auth`. Inserts an `invitations` row and returns the accept
    URL the admin pastes into an email until SMTP is wired up.

  * `POST /api/v1/invitations/{token}/accept` — public (no auth). The
    bearer credential is the token itself; the endpoint creates the
    Supabase user via the admin API, inserts a `users` + `org_members`
    row, and stamps `accepted_at`. Bypasses RLS via `AdminSessionFactory`
    because anonymous callers can't carry an `X-Org-ID` header.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text

from core.config import get_settings
from core.envelope import ok
from db.session import AdminSessionFactory
from middleware.auth import AuthContext, require_auth
from schemas.invitations import (
    InvitationAccept,
    InvitationAccepted,
    InvitationCreate,
    InvitationCreated,
    InvitationOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["invitations"])


# Roles allowed to issue invitations. The seed data uses `owner`; future
# admin-tier users get added here.
_ADMIN_ROLES = {"owner", "admin"}
# Roles that can be granted via an invitation. Excludes `owner` so a
# rogue admin can't promote an invitee above themselves.
_ASSIGNABLE_ROLES = {"admin", "member", "viewer"}


@router.post("/orgs/{org_id}/invitations", status_code=status.HTTP_201_CREATED)
async def create_invitation(
    org_id: UUID,
    payload: InvitationCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict:
    if auth.organization_id != org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Org mismatch")
    if auth.role not in _ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required to invite")
    if payload.role not in _ASSIGNABLE_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Invitable roles: {sorted(_ASSIGNABLE_ROLES)}",
        )

    settings = get_settings()
    token = uuid4()

    async with AdminSessionFactory() as db:
        # Reject if there's already an unaccepted invitation for this
        # email + org. Re-issuing on every click would stack rows; let
        # the admin explicitly revoke + reissue if they want a new token.
        existing = (
            await db.execute(
                text(
                    """
                    SELECT id FROM invitations
                    WHERE organization_id = :org
                      AND lower(email) = lower(:email)
                      AND accepted_at IS NULL
                      AND expires_at > NOW()
                    """
                ),
                {"org": str(org_id), "email": payload.email},
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Pending invitation already exists for this email",
            )

        row = (
            (
                await db.execute(
                    text(
                        """
                        INSERT INTO invitations (organization_id, email, role, token, invited_by)
                        VALUES (:org, :email, :role, :token, :invited_by)
                        RETURNING id, organization_id, email, role, token, expires_at
                        """
                    ),
                    {
                        "org": str(org_id),
                        "email": payload.email,
                        "role": payload.role,
                        "token": str(token),
                        "invited_by": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )
        await db.commit()

    accept_url = f"{settings.public_web_url.rstrip('/')}/invite/{row['token']}"
    return ok(
        InvitationCreated(
            id=row["id"],
            organization_id=row["organization_id"],
            email=row["email"],
            role=row["role"],
            token=row["token"],
            expires_at=row["expires_at"],
            accept_url=accept_url,
        ).model_dump(mode="json")
    )


@router.get("/orgs/{org_id}/invitations")
async def list_invitations(
    org_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict:
    if auth.organization_id != org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Org mismatch")
    if auth.role not in _ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")

    async with AdminSessionFactory() as db:
        rows = (
            (
                await db.execute(
                    text(
                        """
                        SELECT id, email, role, expires_at, accepted_at, invited_by, created_at
                        FROM invitations
                        WHERE organization_id = :org
                        ORDER BY created_at DESC
                        """
                    ),
                    {"org": str(org_id)},
                )
            )
            .mappings()
            .all()
        )

    return ok([InvitationOut(**dict(r)).model_dump(mode="json") for r in rows])


@router.delete("/orgs/{org_id}/invitations/{invitation_id}")
async def revoke_invitation(
    org_id: UUID,
    invitation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> dict:
    if auth.organization_id != org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Org mismatch")
    if auth.role not in _ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")

    async with AdminSessionFactory() as db:
        res = await db.execute(
            text(
                """
                DELETE FROM invitations
                WHERE id = :id AND organization_id = :org AND accepted_at IS NULL
                """
            ),
            {"id": str(invitation_id), "org": str(org_id)},
        )
        await db.commit()
        if res.rowcount == 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found or already accepted")
    return ok({"revoked": True})


# ---------- Public accept ----------


@router.get("/invitations/{token}")
async def get_invitation(token: UUID) -> dict:
    """Render-time lookup for the accept page — returns just enough for
    the UI ("you're being invited to <Org Name>") without leaking the
    invited_by user's id or the org's internal slug."""
    async with AdminSessionFactory() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                        SELECT i.email, i.role, i.expires_at, i.accepted_at,
                               o.name AS organization_name
                        FROM invitations i
                        JOIN organizations o ON o.id = i.organization_id
                        WHERE i.token = :token
                        """
                    ),
                    {"token": str(token)},
                )
            )
            .mappings()
            .one_or_none()
        )

    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if row["accepted_at"] is not None:
        raise HTTPException(status.HTTP_410_GONE, "Invitation already accepted")
    if row["expires_at"].tzinfo is None:
        # Defensive — DB returns tz-aware but a bad timezone setting could yield naive.
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "expires_at not tz-aware")

    return ok(
        {
            "email": row["email"],
            "role": row["role"],
            "expires_at": row["expires_at"].isoformat(),
            "organization_name": row["organization_name"],
        }
    )


@router.post("/invitations/{token}/accept")
async def accept_invitation(token: UUID, payload: InvitationAccept) -> dict:
    """Anonymous endpoint — the token IS the credential.

    Steps (atomic over the local DB; Supabase user creation is best-effort
    idempotent via `email_confirm=true` + ON CONFLICT on the local users
    upsert).

    1. Look up + lock the invitation.
    2. Reject if expired / already accepted.
    3. Create the Supabase user via the admin API (or skip if already exists).
    4. Upsert local users row with the Supabase user.id.
    5. Insert org_members row (idempotent on (user_id, organization_id)).
    6. Stamp accepted_at.
    """
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Supabase is not configured; invitations cannot be accepted",
        )

    async with AdminSessionFactory() as db:
        inv = (
            (
                await db.execute(
                    text(
                        """
                        SELECT id, organization_id, email, role, expires_at, accepted_at
                        FROM invitations
                        WHERE token = :token
                        FOR UPDATE
                        """
                    ),
                    {"token": str(token)},
                )
            )
            .mappings()
            .one_or_none()
        )

        if inv is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
        if inv["accepted_at"] is not None:
            raise HTTPException(status.HTTP_410_GONE, "Invitation already accepted")

        # Create the Supabase user. Idempotent: if the email exists, the
        # admin API returns 422 with a code we recognize and we look up
        # the existing user instead.
        user_id = await _provision_supabase_user(
            email=inv["email"],
            password=payload.password,
            full_name=payload.full_name,
        )

        # Upsert local users row mirroring the Supabase user.id.
        await db.execute(
            text(
                """
                INSERT INTO users (id, email, full_name)
                VALUES (:id, :email, :full_name)
                ON CONFLICT (id) DO UPDATE SET
                  email = EXCLUDED.email,
                  full_name = COALESCE(EXCLUDED.full_name, users.full_name)
                """
            ),
            {
                "id": str(user_id),
                "email": inv["email"],
                "full_name": payload.full_name,
            },
        )

        # Grant org membership. UPSERT on the (user_id, organization_id)
        # pair if a unique constraint exists; fall back to NOT EXISTS.
        await db.execute(
            text(
                """
                INSERT INTO org_members (id, user_id, organization_id, role)
                SELECT gen_random_uuid(), :uid, :org, :role
                WHERE NOT EXISTS (
                  SELECT 1 FROM org_members
                  WHERE user_id = :uid AND organization_id = :org
                )
                """
            ),
            {
                "uid": str(user_id),
                "org": str(inv["organization_id"]),
                "role": inv["role"],
            },
        )

        # Stamp the invitation as accepted.
        await db.execute(
            text("UPDATE invitations SET accepted_at = NOW() WHERE id = :id"),
            {"id": str(inv["id"])},
        )
        await db.commit()

    return ok(
        InvitationAccepted(
            organization_id=inv["organization_id"],
            email=inv["email"],
            role=inv["role"],
        ).model_dump(mode="json")
    )


async def _provision_supabase_user(*, email: str, password: str, full_name: str | None) -> UUID:
    """Create or look up the Supabase auth user. Returns the user's UUID,
    which we mirror into the local `users` table.

    Uses the admin API. The secret key is the `sb_secret_*` value gated
    behind the `SUPABASE_SECRET_KEY` env var; never sent to the browser.
    """
    settings = get_settings()
    base = (settings.supabase_url or "").rstrip("/")
    secret = settings.supabase_secret_key
    headers = {
        "apikey": secret,
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }

    body = {
        "email": email,
        "password": password,
        "email_confirm": True,
    }
    if full_name:
        body["user_metadata"] = {"display_name": full_name}

    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            f"{base}/auth/v1/admin/users",
            headers=headers,
            json=body,
        )

    if res.status_code in (200, 201):
        return UUID(res.json()["id"])

    # Email already registered. Look up the existing user — invitations
    # are typically used to add an existing Supabase user to a new org.
    if res.status_code == 422 and "email" in res.text.lower():
        async with httpx.AsyncClient(timeout=10.0) as client:
            lookup = await client.get(
                f"{base}/auth/v1/admin/users",
                headers=headers,
                params={"email": email},
            )
        if lookup.status_code == 200:
            users = lookup.json().get("users") or []
            if users:
                return UUID(users[0]["id"])

    logger.error("Supabase admin user-create failed: %s %s", res.status_code, res.text)
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        "Failed to provision auth user",
    )
