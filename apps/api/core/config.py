from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Deployment env marker. "production" disables every dev stub and
    # tightens secret validation at startup. Read from `AEC_ENV` to match
    # the rest of the platform's `AEC_*` env convention.
    environment: str = Field(default="development", validation_alias="AEC_ENV")

    # Runtime DB — non-superuser (aec_app) so RLS policies actually fire.
    # Request-scoped sessions use this via db.session.SessionFactory.
    database_url: str = "postgresql+asyncpg://aec:aec@localhost:5432/aec"
    # Migrations use this; Alembic needs DDL privileges so it stays as the
    # superuser `aec`.
    database_url_sync: str = "postgresql://aec:aec@localhost:5432/aec"
    # Admin async URL for background jobs that MUST read/write across tenants
    # (e.g. price-alert evaluator, bidradar scrape fanout, weekly-report cron
    # discovery). Only `db.session.AdminSessionFactory` should use this.
    # Defaults to `database_url`; in dev/prod compose, override to the `aec`
    # superuser so BYPASSRLS lets the job see all tenants.
    database_url_admin: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    supabase_jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    openai_embedding_model: str = "text-embedding-3-large"

    aws_region: str = "ap-southeast-1"
    s3_bucket: str = "aec-platform-files"

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str = "no-reply@aec-platform.vn"

    cors_origins: list[str] = ["http://localhost:3000"]

    # Public-facing web URL — used to build supplier-portal links embedded
    # in RFQ emails. Suppliers click these to land on the no-auth response
    # page. In dev this matches the Next.js dev server; in prod set it to
    # the customer-facing domain so the link works from a supplier's inbox.
    public_web_url: str = "http://localhost:3000"

    # Token validity window for RFQ supplier-portal links. Defaults to 60
    # days, which covers the deadline (typically 7-30 days) plus grace for
    # a late supplier. Tokens carry no DB row — they're stateless JWTs —
    # so revocation is implicit-via-expiry.
    rfq_token_ttl_seconds: int = 60 * 60 * 24 * 60

    # SiteEye Ray Serve (YOLOv8m safety model). Read by apps.ml.pipelines.siteeye.
    # Override via env `SITEEYE_RAY_SERVE_URL` in deployment manifests.
    siteeye_ray_serve_url: str = "http://siteeye-safety:8000"

    # ---------- Observability ----------
    #
    # `log_level` is the floor (DEBUG/INFO/WARNING/ERROR). `log_format` is
    # `pretty` for dev (single-line readable) or `json` for prod (one
    # log-line-per-record, parseable by any log shipper). `slow_query_ms`
    # logs a WARN when a single SQL statement exceeds the threshold —
    # caught by the SQLAlchemy `before_cursor_execute` /
    # `after_cursor_execute` listeners installed in `core.observability`.
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_format: str = Field(default="pretty", validation_alias="LOG_FORMAT")
    slow_query_ms: int = Field(default=500, validation_alias="SLOW_QUERY_MS")

    # Sentry DSN. None disables Sentry entirely (no-op init, no SDK overhead
    # beyond a `getenv`). Set in prod manifests; leave empty in dev.
    sentry_dsn: str | None = Field(default=None, validation_alias="SENTRY_DSN")
    sentry_traces_sample_rate: float = Field(default=0.1, validation_alias="SENTRY_TRACES_SAMPLE_RATE")


@lru_cache
def get_settings() -> Settings:
    return Settings()
