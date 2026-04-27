"""Pydantic schemas for the invitation flow.

Two surfaces:
  * Admin (`/orgs/{id}/invitations`) — auth required, returns the accept URL.
  * Public (`/invitations/{token}/accept`) — no auth, takes a password,
    creates the Supabase user + the org membership.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ---------- Admin: create invitation ----------


class InvitationCreate(BaseModel):
    email: EmailStr
    role: str = Field(
        default="member",
        description="Role on the org_members row created when the invitation is accepted.",
    )


class InvitationCreated(BaseModel):
    """Response includes the accept URL — the dev workflow has the admin
    copy it manually. Once SMTP is wired the email will carry it instead."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    email: str
    role: str
    token: UUID
    expires_at: datetime
    accept_url: str


class InvitationOut(BaseModel):
    """Listing shape — never includes the raw token (would let anyone with
    org-listing rights bypass the admin gate by impersonating an invitee)."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    invited_by: UUID | None
    created_at: datetime


# ---------- Public: accept invitation ----------


class InvitationAccept(BaseModel):
    """The invitee's set-password call. Email is not part of the body —
    we read it off the invitation row by token, so the invitee can't
    accept under a different email and silently change the user record."""

    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)


class InvitationAccepted(BaseModel):
    """Tells the web client where to send the user next. The Supabase
    client picks up the session cookie via a separate sign-in call —
    we don't return the access_token here because mixing flows
    (auth-set-by-api vs auth-set-by-supabase-js) breaks the @supabase/ssr
    cookie contract."""

    organization_id: UUID
    email: str
    role: str
