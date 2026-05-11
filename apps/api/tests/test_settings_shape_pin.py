"""Pin the field set of `core.config.Settings`.

Why this exists: `Settings` is the closed registry of every
environment-variable-driven configuration value. A revert that
drops a field means the matching feature silently can't be
configured at deploy time:

  * Drop `ops_slack_webhook_url` → Slack alerts can't be enabled
    (`services.slack.send_slack` reads `get_settings().ops_slack_webhook_url`
    and silently no-ops on missing-attr).

  * Drop `metrics_token` → /metrics endpoint loses its auth token
    check; scrapes from anywhere accepted (silent privilege bug
    on a public-by-default endpoint).

  * Drop `retention_*_days` → the retention cron's per-table
    overrides revert to defaults; tenants who customised their
    audit retention silently lose their config.

  * Add a field without a default → every existing deployment's
    `Settings()` instantiation 422s on startup because the env
    var wasn't set. New fields MUST have a sensible default for
    deployment compatibility.

This test pins:
  1. The exact set of fields (catches drops + unannounced additions).
  2. No required fields (every Settings field MUST have a default
     so the app boots without a fully-configured env).
  3. Specific high-value fields are present + typed correctly
     (Slack webhook is `str | None`, secrets are nullable, the
     CORS origins list isn't a single string, etc.).

If you intentionally change Settings, update `EXPECTED_FIELDS`
below in the same PR + verify the matching `os.environ` lookup
in any consumer code is still wired.
"""

from __future__ import annotations

from core.config import Settings

# Source of truth, pinned 2026-05-04. Each comment names the
# canonical consumer so a reviewer dropping a field knows what
# breaks downstream.
EXPECTED_FIELDS: frozenset[str] = frozenset(
    {
        # Environment / deploy posture
        "environment",  # main.py uses this to gate the dev-secret-rejection check
        # Database
        "database_url",  # db.session — the aec_app NOBYPASSRLS DSN
        "database_url_sync",  # alembic migrations (sync DSN)
        "database_url_admin",  # AdminSessionFactory BYPASSRLS DSN
        # Redis (arq queue)
        "redis_url",
        # Supabase auth
        "supabase_url",
        "supabase_secret_key",
        "supabase_jwt_secret",  # main.py rejects the dev default in production
        "jwt_algorithm",
        # LLM providers
        "anthropic_api_key",  # services.assistant gates stub vs. live on this
        "openai_api_key",  # codeguard embedding pipeline
        "anthropic_model",
        "openai_embedding_model",
        # S3 / archive
        "aws_region",
        "s3_bucket",  # retention archives, file uploads
        # Retention overrides — per-table opt-in env-var override
        # of the default-days in `RETENTION_POLICIES`. Dropping
        # any of these silently reverts a tenant's customised
        # retention to the default.
        "retention_audit_events_days",
        "retention_webhook_deliveries_days",
        "retention_search_queries_days",
        "retention_import_jobs_days",
        # SMTP (mailer)
        "smtp_host",
        "smtp_port",
        "smtp_user",
        "smtp_password",
        "email_from",
        # URLs
        "web_base_url",  # invitation email links, supplier portal links
        "public_web_url",  # CORS-allowed origin for the public RFQ portal
        # Ops alert routing
        "ops_alert_emails",  # services.ops_alerts fallback when no users opted in
        "ops_slack_webhook_url",  # services.slack.send_slack
        # CORS
        "cors_origins",  # main.py CORSMiddleware
        # Tokens / TTLs
        "rfq_token_ttl_seconds",
        # External services
        "siteeye_ray_serve_url",  # ml.pipelines.siteeye
        # Observability
        "log_level",
        "log_format",
        "slow_query_ms",  # observability slow-query threshold
        "sentry_dsn",
        "sentry_traces_sample_rate",
        # Metrics auth
        "metrics_token",  # /metrics scrape token (None = open)
    }
)


def test_settings_field_set_matches_pin():
    """Hard equality on the field set. The two-way diff names
    exactly which side drifted.
    """
    actual = frozenset(Settings.model_fields.keys())
    missing = EXPECTED_FIELDS - actual
    unexpected = actual - EXPECTED_FIELDS
    assert not missing, (
        f"Settings lost fields: {sorted(missing)}. If this is intentional, "
        "remove from EXPECTED_FIELDS in the same PR + audit consumers "
        "(`grep -rn 'get_settings().<field_name>' apps/api`) — silent "
        "no-ops downstream are the canonical regression."
    )
    assert not unexpected, (
        f"Settings gained fields the pin doesn't know about: {sorted(unexpected)}. "
        "If this is intentional, add to EXPECTED_FIELDS in the same PR + "
        "verify the new field has a sensible default (see the no-required-fields "
        "test below)."
    )


def test_no_settings_field_is_required():
    """Every `Settings` field MUST have a default. The app's boot
    sequence reads `Settings()` (no kwargs) — a required field
    means deployments that haven't set the matching env var crash
    on startup with `pydantic.ValidationError`. New fields must
    ship with a sensible default.

    The `dev-secret-change-me` default for `supabase_jwt_secret`
    is intentionally a known-bad value: main.py rejects it in
    production but accepts it in dev/staging. That's the right
    pattern (default-bad-but-replaceable beats default-required-
    crash-on-boot).
    """
    required = [n for n, f in Settings.model_fields.items() if f.is_required()]
    assert not required, (
        f"Settings has required fields: {required}. Each one would crash "
        "deployment boot if its env var wasn't set. Add a sensible default "
        "(or a known-bad default + production-time rejection like "
        "`supabase_jwt_secret`)."
    )


def test_secrets_are_optional_with_none_default():
    """Sensitive credential fields MUST default to None — never to
    a hardcoded value, even a placeholder. A typo to e.g.
    `default="ci-placeholder"` would silently let prod boot with
    a fake credential, and the LLM-call paths (which check
    `if not settings.anthropic_api_key:`) would take the
    "configured" branch with a junk key.

    Tested fields are the ones whose presence-vs-absence gates
    feature behaviour:
      * LLM keys (live vs. stub assistant)
      * SMTP creds (mailer no-op vs. real send)
      * Slack webhook (alert no-op vs. real post)
      * Sentry DSN (instrumentation off vs. on)
      * Supabase secret key (admin-API access)
      * metrics_token (open vs. token-gated /metrics)
    """
    presence_gated = (
        "anthropic_api_key",
        "openai_api_key",
        "smtp_host",
        "smtp_user",
        "smtp_password",
        "ops_slack_webhook_url",
        "sentry_dsn",
        "supabase_secret_key",
        "supabase_url",
        "metrics_token",
        "database_url_admin",
    )
    for name in presence_gated:
        field = Settings.model_fields[name]
        assert field.default is None, (
            f"Settings.{name} default is {field.default!r}, expected None. "
            "Presence-gated fields must default to None — a placeholder "
            "would silently take the 'configured' branch in callers that "
            "check `if not value:`."
        )


def test_supabase_jwt_secret_default_is_known_bad():
    """`supabase_jwt_secret` defaults to `"dev-secret-change-me"` —
    a known-bad value that `main.create_app()` explicitly rejects
    in production. This is the canonical "default-bad-but-
    replaceable" pattern; flipping it to a generic-but-passable
    string would silently let prod boot with a guessable secret."""
    field = Settings.model_fields["supabase_jwt_secret"]
    assert field.default == "dev-secret-change-me", (
        f"Settings.supabase_jwt_secret default is {field.default!r}. "
        "MUST stay the documented `dev-secret-change-me` so production "
        "boot rejects unconfigured deploys — main.py's prod-default "
        "check string-matches this exact value."
    )


def test_cors_origins_is_list_not_str():
    """A revert that flipped `cors_origins: list[str]` to plain
    `str` would cause CORSMiddleware to receive the string and
    treat each CHARACTER as a separate origin (or accept all
    origins on `"*"`). The default value must be a list literal
    so the FastAPI middleware reads a sequence."""
    field = Settings.model_fields["cors_origins"]
    # Annotation should be `list[str]` (or a union containing it).
    ann_str = str(field.annotation)
    assert "list[str]" in ann_str, (
        f"Settings.cors_origins annotation is {ann_str!r}, expected "
        "list[str]. CORSMiddleware iterates this value; a plain str "
        "would either iterate characters or wildcard everything."
    )
    # Default must be a list.
    assert isinstance(field.default, list), (
        f"Settings.cors_origins default is {type(field.default).__name__}; must be a list."
    )


def test_retention_override_fields_default_to_none():
    """The four `retention_*_days` env-var overrides MUST default
    to None — None means "use the default-days in
    RETENTION_POLICIES", anything else overrides it. A regression
    to e.g. `default=30` would silently shorten the audit-events
    retention window for every deployment that didn't explicitly
    set a longer override.
    """
    for name in (
        "retention_audit_events_days",
        "retention_webhook_deliveries_days",
        "retention_search_queries_days",
        "retention_import_jobs_days",
    ):
        field = Settings.model_fields[name]
        assert field.default is None, (
            f"Settings.{name} default is {field.default!r}, expected None. "
            "A non-None default silently overrides the matching policy's "
            "default_days for every deployment."
        )


def test_settings_field_count():
    """Belt-and-suspenders. The set-equality test above would also
    fail, but a count check makes "schema gained N fields" loud."""
    actual = len(Settings.model_fields)
    expected = len(EXPECTED_FIELDS)
    assert actual == expected, (
        f"Settings has {actual} fields; EXPECTED_FIELDS has {expected}. "
        "The set-equality test will name which side is off."
    )
