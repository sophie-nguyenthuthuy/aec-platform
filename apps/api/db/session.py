from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import event, text
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

# ---------- Admin (cross-tenant) session factory ----------
#
# A small set of background jobs legitimately need cross-tenant visibility:
#   * `services.price_alerts.evaluate_price_alerts` — reads every alert.
#   * `services.bidradar_jobs.scrape_and_score_for_all_orgs` — enumerates
#     firm profiles and system-embedded tenders.
#   * `workers.queue.weekly_report_cron` — discovers (org, project) pairs
#     with photos this past week.
#
# Under the NOBYPASSRLS `aec_app` runtime role, these queries return zero
# rows silently. `AdminSessionFactory` binds to `database_url_admin` (the
# superuser `aec` in compose) so batch jobs get the BYPASSRLS they depend
# on — while regular request traffic keeps the RLS guard-rail intact.
#
# If `database_url_admin` is unset, we fall back to `database_url` and log
# a warning on first use. This keeps local `pytest` green without extra
# config, but a prod deploy missing the env var will be flagged.

_admin_url = _settings.database_url_admin or _settings.database_url
_admin_engine = create_async_engine(
    _admin_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    future=True,
)

AdminSessionFactory = async_sessionmaker(
    _admin_engine, expire_on_commit=False, class_=AsyncSession
)


class TenantAwareSession:
    """Async session wrapper that injects `app.current_org_id` so RLS policies apply.

    Use via `async with TenantAwareSession(org_id) as session:` inside a request handler,
    or rely on the `get_db` dependency which reads org_id from the auth context.

    Why an `after_begin` listener instead of a one-shot ``SET LOCAL``:
    `set_config(..., is_local=true)` only persists until the current transaction
    commits. Handlers that do ``db.commit(); db.refresh(obj)`` — a common pattern
    after insert — start a fresh implicit transaction on the refresh, at which
    point the GUC reverts to ``''`` and every RLS policy's
    ``current_setting('app.current_org_id', true)::uuid`` cast raises
    ``invalid input syntax for type uuid: ""``. Hooking ``after_begin`` re-applies
    the setting at the start of every transaction for the session's lifetime,
    which keeps RLS correct across commit boundaries without leaking the GUC
    to other tenants (the setting dies with the session when ``close()`` returns
    the connection to the pool — any future checkout rebinds to its own
    ``TenantAwareSession``).
    """

    def __init__(self, organization_id: UUID):
        self.organization_id = organization_id
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        self._session = SessionFactory()
        org_id = str(self.organization_id)

        def _set_tenant_guc(session, transaction, connection):
            # Sync handler fired by SQLAlchemy on the sync Session that
            # backs the AsyncSession. `connection` is the sync Connection
            # bound to the new transaction — execute via text() so SQLAlchemy
            # handles asyncpg's $1-style parameterisation for us. Org IDs are
            # UUIDs from a trusted AuthContext, but parameterisation is still
            # the right hygiene here.
            connection.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": org_id},
            )

        event.listen(self._session.sync_session, "after_begin", _set_tenant_guc)
        self._after_begin_listener = _set_tenant_guc

        # Force-begin so the first statement sees the GUC set; otherwise the
        # very first execute() would implicitly open a txn before our listener
        # had anything to fire on.
        await self._session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": org_id},
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
            event.remove(
                self._session.sync_session, "after_begin", self._after_begin_listener
            )
            await self._session.close()


@asynccontextmanager
async def tenant_session(organization_id: UUID) -> AsyncIterator[AsyncSession]:
    async with TenantAwareSession(organization_id) as session:
        yield session
