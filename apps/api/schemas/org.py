"""Schemas for org-membership management."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from middleware.rbac import Role


class OrgMember(BaseModel):
    """One member row joined to the user it represents."""

    model_config = ConfigDict(from_attributes=True)
    membership_id: UUID
    user_id: UUID
    email: str
    full_name: str | None = None
    avatar_url: str | None = None
    role: Role
    joined_at: datetime


class InviteMemberRequest(BaseModel):
    email: EmailStr = Field(description="Existing or new user's email.")
    role: Role = Field(
        default=Role.MEMBER,
        description="Initial role. Owners can promote later via PATCH.",
    )


class UpdateMemberRoleRequest(BaseModel):
    role: Role
