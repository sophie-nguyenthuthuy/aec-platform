from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    future=True,
)

SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class TenantAwareSession:
    """Async session wrapper that injects `app.current_org_id` so RLS policies apply.

    Use via `async with TenantAwareSession(org_id) as session:` inside a request handler,
    or rely on the `get_db` dependency which reads org_id from the auth context.
    """

    def __init__(self, organization_id: UUID):
        self.organization_id = organization_id
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        self._session = SessionFactory()
        await self._session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(self.organization_id)},
        )
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        assert self._session is not None
        try:
            if exc is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()


@asynccontextmanager
async def tenant_session(organization_id: UUID) -> AsyncIterator[AsyncSession]:
    async with TenantAwareSession(organization_id) as session:
        yield session
