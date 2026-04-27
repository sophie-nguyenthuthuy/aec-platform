"""RBAC primitives: hierarchical role enum + dependency factories.

The platform uses four organisation-scoped roles:

  * `owner`   — billing, plan, dangerous deletes (e.g. delete org). One
                per org by convention; not enforced as a unique
                constraint because handover-of-ownership scenarios
                temporarily need two.
  * `admin`   — full read/write across modules; can manage members
                (invite, change role, revoke) but can't delete the org.
  * `member`  — full read; can write within modules they participate in
                (create RFIs, log defects, approve estimates).
  * `viewer`  — read-only. Useful for clients, auditors, contractor
                liaisons. Cannot create / update / delete anything.

Hierarchy: `viewer < member < admin < owner`. `Role.at_least(other)`
encodes the rank check; routers either name explicit roles
(`require_role(Role.ADMIN, Role.OWNER)`) or use the cleaner
`require_min_role(Role.ADMIN)` form when "this and everything above"
is the intent.

Why not stash the rank order on the enum itself? Python's `Enum`
treats class attributes specially — `_RANK` would be a member.
Module-level constant + a class method gets us the same ergonomics
without that footgun.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status

from middleware.auth import AuthContext, require_auth


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"

    @classmethod
    def parse(cls, raw: str) -> Role | None:
        """Tolerant lookup — returns None for unrecognised strings rather
        than raising. Lets the role check fall through to a 403 with a
        clean error message instead of crashing on stale DB data."""
        try:
            return cls(raw)
        except ValueError:
            return None

    def at_least(self, floor: Role) -> bool:
        """`self` rank is >= `floor` rank in the hierarchy."""
        return _RANK[self] >= _RANK[floor]


_RANK: dict[Role, int] = {
    Role.VIEWER: 1,
    Role.MEMBER: 2,
    Role.ADMIN: 3,
    Role.OWNER: 4,
}


def require_role(*allowed: Role | str):
    """Allow only callers whose role is in `allowed`. Accepts Role enums
    or raw strings (for back-compat with the existing call sites)."""
    allowed_values = {a.value if isinstance(a, Role) else a for a in allowed}

    async def _dep(ctx: Annotated[AuthContext, Depends(require_auth)]) -> AuthContext:
        if ctx.role not in allowed_values:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Insufficient role: this endpoint requires one of {sorted(allowed_values)}",
            )
        return ctx

    return _dep


def require_min_role(floor: Role):
    """Allow callers at or above `floor` in the hierarchy. Cleaner than
    listing every role above the threshold."""

    async def _dep(ctx: Annotated[AuthContext, Depends(require_auth)]) -> AuthContext:
        actual = Role.parse(ctx.role)
        if actual is None or not actual.at_least(floor):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Insufficient role: this endpoint requires at least '{floor.value}'",
            )
        return ctx

    return _dep
