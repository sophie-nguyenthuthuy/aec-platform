from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CHAR, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

# Postgres columns are `timestamp with time zone`; mirror that at the ORM layer
# so asyncpg round-trips tz-aware datetimes without "can't subtract offset-naive
# and offset-aware" errors at flush time.
TZ = DateTime(timezone=True)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(Text, default="starter", nullable=False)
    modules: Mapped[list] = mapped_column(JSONB, default=list)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    country_code: Mapped[str] = mapped_column(CHAR(2), default="VN")
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    preferred_language: Mapped[str] = mapped_column(Text, default="vi")
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class OrgMember(Base):
    __tablename__ = "org_members"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class Invitation(Base):
    """Admin-issued one-time token granting org membership.

    See migration 0017_invitations for the flow rationale. The accept
    endpoint runs without an X-Org-ID header (the invitee has no org
    yet), so it uses `AdminSessionFactory` to bypass RLS — the row is
    found by `token` which is itself the bearer credential.
    """

    __tablename__ = "invitations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    token: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(TZ)
    invited_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    address: Mapped[dict | None] = mapped_column(JSONB)
    area_sqm: Mapped[float | None] = mapped_column(Numeric)
    floors: Mapped[int | None] = mapped_column(Integer)
    budget_vnd: Mapped[int | None] = mapped_column(BigInteger)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class File(Base):
    """Shared file object. Every module that stores binary artifacts references
    this table so S3 keys, ingestion status, and RLS are centrally managed.
    DDL lives in migration 0001_core; this mapping is what routers import."""

    __tablename__ = "files"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    source_module: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str] = mapped_column(Text, default="pending")
    extracted_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ProjectWatch(Base):
    """Per-user "I want activity digests for this project" subscription.

    Drives the `daily_activity_digest_cron`: only watched projects feed
    into a user's morning email. The activity feed *page* remains
    org-wide; watches are purely about who gets pushed out-of-band.

    `(user_id, project_id)` is unique so a user can't double-watch the
    same project. Tenant-scoped via `organization_id` (RLS-enforced) so
    a misbehaving handler can't subscribe a user to another tenant's
    project — the FK to projects already prevents that, but the org
    column lines up with our standard RLS policy shape.
    """

    __tablename__ = "project_watches"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ScraperRun(Base):
    """Per-invocation telemetry row for `services.price_scrapers.run_scraper`.

    Global ops data — no `organization_id`, no RLS. Persisted via
    `AdminSessionFactory` (BYPASSRLS `aec` role). See migration
    `0012_scraper_runs.py` for the schema rationale and the
    `(slug, started_at DESC)` index supporting "last N runs for slug".
    """

    __tablename__ = "scraper_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    scraped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rule_hits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    unmatched_sample: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class NotificationPreference(Base):
    """Per-user, per-org opt-in for an alert kind.

    `key` is a stable string discriminator (`scraper_drift`,
    `rfq_deadline_summary`, …) chosen by callers in `services.ops_alerts`
    and friends. The two channel booleans are independent so users can
    opt into email but not Slack, or vice versa, once Slack delivery
    exists.

    Schema rationale + migration: see `0025_notification_prefs.py`.
    """

    __tablename__ = "notification_preferences"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    slack_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TZ)
    updated_at: Mapped[datetime] = mapped_column(TZ)
