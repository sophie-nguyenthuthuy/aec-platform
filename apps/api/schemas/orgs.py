"""Org-scoped resources (plural). Today this carries just the
self-serve org-creation path; more cross-tenant org operations land here
as they appear."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


class OrgCreate(BaseModel):
    """A new tenant. The creator becomes the owner; everyone else is
    invited via the invitation flow.

    `slug` is optional — if omitted, the api derives it from `name`. We
    keep the slug stable (immutable post-create) since it ends up in
    URLs, audit logs, and customer-facing pages."""

    name: str = Field(min_length=2, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=64)
    country_code: str = Field(default="VN", min_length=2, max_length=2)

    @field_validator("slug")
    @classmethod
    def _slug_is_kebab(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if not _SLUG_RE.fullmatch(v):
            raise ValueError("slug must be lowercase letters/digits with optional hyphens (no leading/trailing hyphen)")
        return v


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    plan: str
    country_code: str
    created_at: datetime
    role: str  # creator's role on this org — always "owner" from POST /orgs
