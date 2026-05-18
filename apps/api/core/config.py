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

    # Supabase project URL. When set, the auth middleware switches to
    # ES256/EdDSA verification via JWKS at `<url>/auth/v1/.well-known/jwks.json`.
    # Leave empty in tests / legacy deploys to keep the HS256 fallback below.
    supabase_url: str | None = Field(default=None, validation_alias="SUPABASE_URL")
    # Server-only secret key (`sb_secret_*`). Required for admin Supabase
    # API calls (e.g. listing users, sending magic links). Never ship to the
    # browser.
    supabase_secret_key: str | None = Field(default=None, validation_alias="SUPABASE_SECRET_KEY")

    # Legacy HS256 secret. Used only when `supabase_url` is unset (tests,
    # migrating deployments). Has no effect once the asymmetric path is on.
    supabase_jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"

    # ---------- AI providers ----------
    #
    # Self-hosted OSS stack via an OpenAI-compatible endpoint (Ollama in
    # dev/CPU, vLLM / SGLang in production GPU). All pipelines go through
    # the factory at `apps/ml/llm.py`; change the endpoint by editing these
    # settings — never reach for a vendor SDK directly.
    llm_base_url: str = Field(
        default="http://localhost:11434/v1",
        validation_alias="LLM_BASE_URL",
    )
    llm_api_key: str | None = Field(default=None, validation_alias="LLM_API_KEY")
    # 7b is the CPU/laptop dev default; production GPU should set
    # LLM_CHAT_MODEL=qwen2.5:32b-instruct in the deploy environment.
    llm_chat_model: str = Field(
        default="qwen2.5:7b-instruct",
        validation_alias="LLM_CHAT_MODEL",
    )
    llm_vision_model: str = Field(
        default="qwen2.5vl:7b",
        validation_alias="LLM_VISION_MODEL",
    )
    llm_embedding_model: str = Field(
        # `nomic-embed-text` is 768-dim native and Apache-2.0 — matches the
        # existing pgvector(768) columns (see `0041_gemini_embedding_dim`).
        # Swap to `bge-m3` (1024-dim) for better Vietnamese retrieval; that
        # needs a migration widening the vector columns.
        default="nomic-embed-text",
        validation_alias="LLM_EMBEDDING_MODEL",
    )

    # Object storage (S3-compatible). Defaults below target AWS S3 in
    # ap-southeast-1; set `s3_endpoint_url` to a MinIO endpoint to
    # switch over. `s3_access_key_id`/`s3_secret_access_key` are
    # required for MinIO, optional on AWS (default provider chain
    # handles IAM role).
    aws_region: str = "ap-southeast-1"
    s3_bucket: str = "aec-platform-files"
    s3_endpoint_url: str | None = Field(default=None, validation_alias="S3_ENDPOINT_URL")
    s3_access_key_id: str | None = Field(default=None, validation_alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = Field(default=None, validation_alias="S3_SECRET_ACCESS_KEY")
    s3_force_path_style: bool = Field(default=False, validation_alias="S3_FORCE_PATH_STYLE")
    s3_public_base_url: str | None = Field(default=None, validation_alias="S3_PUBLIC_BASE_URL")

    # Per-table retention overrides for the nightly prune cron
    # (`services.retention.run_retention_cron`). When unset, each
    # table falls back to `RetentionPolicy.default_days`. Set in env as
    # `AEC_RETENTION_AUDIT_EVENTS_DAYS=730` to extend audit retention
    # for a compliance-conscious tenant. The cron is platform-global,
    # so per-org overrides aren't a thing — those would need a real
    # `retention_policies` table.
    retention_audit_events_days: int | None = Field(default=None, validation_alias="AEC_RETENTION_AUDIT_EVENTS_DAYS")
    retention_webhook_deliveries_days: int | None = Field(
        default=None, validation_alias="AEC_RETENTION_WEBHOOK_DELIVERIES_DAYS"
    )
    retention_search_queries_days: int | None = Field(
        default=None, validation_alias="AEC_RETENTION_SEARCH_QUERIES_DAYS"
    )
    retention_import_jobs_days: int | None = Field(default=None, validation_alias="AEC_RETENTION_IMPORT_JOBS_DAYS")

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str = "no-reply@aec-platform.vn"

    # Resend transactional-email backend. When `RESEND_API_KEY` is set the
    # mailer routes via the Resend HTTP API instead of SMTP — Resend handles
    # DKIM/SPF, bounce processing, and gives us per-message delivery
    # webhooks without us having to babysit an MTA. SMTP plumbing is kept
    # as a fallback for customers who require self-hosted email.
    #
    # `resend_from` defaults to `email_from` so existing callers don't need
    # to be updated. Override when sending from a verified Resend domain
    # that differs from `email_from`.
    resend_api_key: str | None = Field(default=None, validation_alias="RESEND_API_KEY")
    resend_from: str | None = Field(default=None, validation_alias="RESEND_FROM")
    resend_reply_to: str | None = Field(default=None, validation_alias="RESEND_REPLY_TO")

    # Public-facing web app origin used when building absolute URLs for
    # email bodies, Slack messages, etc. The codeguard threshold-warning
    # emails use this to render `<base>/codeguard/quota` — relative paths
    # render as non-clickable text in most email clients (Gmail, Outlook
    # web). No trailing slash convention: callers append `/codeguard/...`
    # so the helper enforces it via `.rstrip('/')`.
    #
    # Default `https://app.aec-platform.vn` is the production hostname;
    # local dev overrides via `WEB_BASE_URL=http://localhost:3000`.
    web_base_url: str = Field(
        default="https://app.aec-platform.vn",
        validation_alias="WEB_BASE_URL",
    )

    # Recipients for ops drift alerts (codeguard quota drift, queue-depth
    # alarms, etc.). Empty list disables alerting entirely — services check
    # this list and short-circuit before rendering bodies. Comma-separated
    # in env: `OPS_ALERT_EMAILS=ops@x.com,ops2@x.com`.
    ops_alert_emails: list[str] = Field(default_factory=list, validation_alias="OPS_ALERT_EMAILS")

    # Slack incoming-webhook URL for ops alerts. Single global webhook
    # rather than per-org because drift is platform-ops data, not
    # tenant-scoped. When this is empty, Slack delivery silently
    # short-circuits — same posture as `OPS_ALERT_EMAILS`. To
    # configure: create an Incoming Webhook in your Slack workspace
    # (https://api.slack.com/messaging/webhooks) and set the URL here.
    ops_slack_webhook_url: str | None = Field(default=None, validation_alias="OPS_SLACK_WEBHOOK_URL")

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
    # Profiling sample rate (0.0–1.0). Activates the Sentry Profiler
    # which samples CPU stacks for the slow ~1% of requests, so we can
    # actually find the hot path on the SiteEye image pipeline or the
    # CodeGuard embedding round-trip. Multiplicative with the traces
    # sample rate — `traces=0.1 * profiles=0.5` means 5% of all
    # requests get a profile. Keep low; profiling has measurable CPU
    # overhead beyond plain tracing.
    sentry_profiles_sample_rate: float = Field(
        default=0.0, validation_alias="SENTRY_PROFILES_SAMPLE_RATE"
    )
    # Release identifier — typically the git SHA injected by the build
    # pipeline (Railway: `RAILWAY_GIT_COMMIT_SHA`; Vercel:
    # `VERCEL_GIT_COMMIT_SHA`). Sentry uses this to correlate errors
    # to specific deploys + show the deploy timeline. Empty = "no
    # release tag", which still works but loses the deploy correlation.
    sentry_release: str | None = Field(default=None, validation_alias="SENTRY_RELEASE")


@lru_cache
def get_settings() -> Settings:
    return Settings()
