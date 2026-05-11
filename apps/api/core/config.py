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

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    openai_embedding_model: str = "text-embedding-3-large"

    aws_region: str = "ap-southeast-1"
    s3_bucket: str = "aec-platform-files"

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

    metrics_token: str | None = Field(default=None, validation_alias="AEC_METRICS_TOKEN")


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ---------- Prod-env boot validation ----------


def validate_prod_settings(settings: Settings) -> list[str]:
    """Return a list of human-readable issues with the current `settings`
    when `environment == 'production'`. Empty list = safe to boot.

    `main.py` calls this at app construction and raises `RuntimeError`
    listing every issue if any are found. The function is split out so
    the test suite can exercise it directly without spinning up the
    full FastAPI app.

    Each rule is conservative — it fails on a default that's CLEARLY
    a dev value (localhost, http://, hardcoded ID-like literal). It
    intentionally does NOT try to validate "looks like a real prod
    URL" — that would tip into rejecting legitimate staging
    deployments. Better to fail-fast on obvious dev defaults than to
    second-guess every URL.

    The list is returned (not raised) so the caller can format all
    issues in a single error message — tells an operator EVERY thing
    they need to fix in one boot failure, not "fix this, redeploy,
    discover the next one, fix it, redeploy."
    """
    if settings.environment != "production":
        return []

    issues: list[str] = []

    # JWT secret — the original gate. Even if other dev tokens leak,
    # this is the one that lets ANY caller mint a JWT against a
    # well-known string.
    if settings.supabase_jwt_secret == "dev-secret-change-me":
        issues.append(
            "SUPABASE_JWT_SECRET is the dev default 'dev-secret-change-me' — "
            "ANY caller can mint a valid JWT against it. Set a real secret "
            "(64+ random chars) or migrate to Supabase JWKS via SUPABASE_URL."
        )

    # CORS origins — `["http://localhost:3000"]` is the dev default in
    # the field declaration. A prod deploy that forgot to override
    # would either reject every legitimate request or, if the dev
    # origin happens to be in scope, silently allow localhost-bound
    # malicious tabs to pivot through CORS.
    if settings.cors_origins == ["http://localhost:3000"]:
        issues.append(
            "CORS_ORIGINS still at the dev default ['http://localhost:3000']. "
            "Set to your production web origin(s) — comma-separated in env."
        )
    if any("localhost" in origin or "127.0.0.1" in origin for origin in settings.cors_origins):
        issues.append(
            "CORS_ORIGINS contains a localhost / 127.0.0.1 entry — these "
            "should never be reachable from production callers. Remove them "
            "from the prod manifest."
        )

    # web_base_url — used in email bodies and Slack messages.
    # http:// → links sent to customers are insecure; localhost
    # in the URL → links don't work outside the dev machine.
    if settings.web_base_url.startswith("http://"):
        issues.append(
            f"WEB_BASE_URL is http:// ({settings.web_base_url!r}) — emails / "
            "Slack messages link to an insecure URL. Use https:// in prod."
        )
    if "localhost" in settings.web_base_url:
        issues.append(
            f"WEB_BASE_URL contains 'localhost' ({settings.web_base_url!r}) — links sent to customers won't resolve."
        )

    # public_web_url — RFQ supplier-portal links land here. Same
    # rationale as web_base_url, different field.
    if settings.public_web_url.startswith("http://") and "localhost" in settings.public_web_url:
        issues.append(
            f"PUBLIC_WEB_URL is the dev default ({settings.public_web_url!r}). "
            "Suppliers receive RFQ links pointing there — set to the "
            "customer-facing domain."
        )

    # /metrics — open by design in dev (so a local Prometheus just
    # works). In prod, missing token = ops counters readable from any
    # network-reachable client. Either set a token or front the route
    # with a network-level allowlist (which is fine — explicit choice
    # the operator can make by setting AEC_METRICS_TOKEN_OK_TO_OMIT=1
    # if they really want it open behind a private LB).
    if settings.metrics_token is None:
        issues.append(
            "AEC_METRICS_TOKEN is unset — /metrics is openly readable. "
            "Set a token (any 32+ char random string) so Prometheus scrapes "
            "via ?token=… and unauthenticated callers get 401."
        )

    # SiteEye Ray Serve — service-discovery URL. The dev default
    # points at a docker-compose hostname that doesn't exist outside
    # the local stack.
    if "siteeye-safety:8000" in settings.siteeye_ray_serve_url:
        issues.append(
            f"SITEEYE_RAY_SERVE_URL is the docker-compose default "
            f"({settings.siteeye_ray_serve_url!r}). Set to the prod "
            "Ray-Serve endpoint or the safety-detection module 502s."
        )

    return issues
