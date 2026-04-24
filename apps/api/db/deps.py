from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth


async def get_db(ctx: AuthContext = Depends(require_auth)) -> AsyncIterator[AsyncSession]:
    async with TenantAwareSession(ctx.organization_id) as session:
        yield session
