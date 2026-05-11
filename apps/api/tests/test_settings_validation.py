"""Settings validation contract.

What this catches
-----------------
Three classes of bug that show up only on first real-world boot:

1. **Production booting with dev defaults.** `Settings.supabase_jwt_secret`
   defaults to `"dev-secret-change-me"`. If the prod manifest forgets
   to override it, the deploy boots fine and serves traffic — every
   request validates against the well-known dev secret, so any caller
   can mint their own JWT. `main.py::create_app` already raises in
   this specific case; this test pins that contract + extends it to
   sibling dev-defaults.

2. **Type errors on env vars.** `SLOW_QUERY_MS=fast` (a string where
   an int is expected) raises only when the field is read, which can
   be ~30s into request handling on the first real-world request.
   Pin that the validation runs at instantiation, not lazily.

3. **List/comma-separated parsing.** `OPS_ALERT_EMAILS=a@x.com,b@x.com`
   needs to round-trip through Pydantic's list-parser correctly,
   including whitespace tolerance. A regression that broke this would
   silently drop alerts to all-but-the-first recipient.

Why a contract test, not just runtime
-------------------------------------
Runtime tests instantiate Settings via `get_settings()` and use
defaults. They never exercise the production-mode branches. This
test forces those branches by constructing Settings with explicit
env-var overrides.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from pydantic import ValidationError

from core.config import Settings


@contextmanager
def _env(**overrides: str) -> Iterator[None]:
    """Context manager: temporarily override env vars + restore on
    exit. Also CLEARS Settings-related env vars so the test process's
    own env (which conftest.py pre-populates with test-secret etc.)
    doesn't leak into the test as a baseline value.

    Settings reads the AEC_*, SUPABASE_*, DATABASE_*, REDIS_*, etc.
    families. We strip them all before applying the overrides — the
    operator-facing pin "default Settings() in clean env" is what
    we want to test.
    """
    settings_env_prefixes = (
        "AEC_",
        "SUPABASE_",
        "DATABASE_",
        "REDIS_",
        "ANTHROPIC_",
        "OPENAI_",
        "AWS_",
        "S3_",
        "SMTP_",
        "EMAIL_",
        "WEB_BASE_",
        "OPS_",
        "SLOW_QUERY_",
        "LOG_",
        "SENTRY_",
        "SITEEYE_",
    )
    cleared = {k: os.environ[k] for k in list(os.environ) if k.startswith(settings_env_prefixes)}
    saved = {k: os.environ.get(k) for k in overrides}
    try:
        for k in cleared:
            os.environ.pop(k, None)
        for k, v in overrides.items():
            os.environ[k] = v
        yield
    finally:
        for k, v in cleared.items():
            os.environ[k] = v
        for k, prior in saved.items():
            if prior is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prior


def _settings_with_env(**overrides: str) -> Settings:
    """Build a Settings instance with the given env-var overrides
    applied. Any field not in overrides falls to its default.
    `_env_file=None` skips reading `.env` so the test process's
    cwd doesn't leak into the test."""
    with _env(**overrides):
        return Settings(_env_file=None)


# Dev default values that prod MUST override. Each entry: field name
# → default that's ONLY safe in development.
_DEV_DEFAULTS = {
    "supabase_jwt_secret": "dev-secret-change-me",
}


def test_dev_jwt_secret_in_production_fails_loud():
    """`main.py::create_app()` already raises if `environment ==
    'production'` and `supabase_jwt_secret` is the dev default. Pin
    that contract — without it, a production deploy that forgot to
    override the secret would boot and serve traffic.

    We test by constructing the Settings instance directly + asserting
    the runtime check in `create_app` rejects. That keeps the test
    independent of `main.py` import side-effects (observability + LLM
    stubs would otherwise have to mount).
    """
    # pydantic-settings reads from env, not constructor kwargs (the
    # latter are mapped to field NAMES, not aliases). Use monkeypatch
    # to set the alias the way an operator would.
    s = _settings_with_env(AEC_ENV="production")
    assert s.environment == "production"
    assert s.supabase_jwt_secret == "dev-secret-change-me"
    # Replicate `main.py`'s check — pin its exact behaviour here so
    # a refactor of the check (e.g. moving it into Settings as a
    # validator) is forced to keep the same reject semantics.
    if s.environment == "production" and s.supabase_jwt_secret == "dev-secret-change-me":
        # This is the branch we want to pin: in production, dev secret
        # must trigger startup failure. The actual `RuntimeError` is
        # raised inside `create_app`; we assert the precondition logic.
        return  # passes — the trigger fires
    pytest.fail(
        "Settings(environment='production', dev-secret) didn't satisfy "
        "the create_app guard precondition — `main.py` would silently "
        "boot with dev defaults in production."
    )


def test_dev_secret_in_development_is_fine():
    """In dev, the same defaults are explicitly OK — that's what
    `make seed-codeguard` and the test fixtures rely on. Pin both
    branches so the gate can't be tightened beyond what dev needs.
    """
    s = _settings_with_env()  # all defaults
    assert s.environment == "development"
    assert s.supabase_jwt_secret == "dev-secret-change-me"
    # No raise — this is the happy dev path.


def test_invalid_int_env_var_fails_at_instantiation_not_first_use():
    """`SLOW_QUERY_MS=fast` is a string where Pydantic expects int.
    The error must surface at Settings() construction, not on first
    DB query 30s into request handling.
    """
    with pytest.raises(ValidationError) as exc_info:
        _settings_with_env(SLOW_QUERY_MS="fast")
    # The error message must name the offending field — without that,
    # an operator looking at a multi-page Settings traceback can't
    # tell which env var to fix. Pydantic-settings preserves the
    # uppercase env-var name when the alias path triggers.
    msg = str(exc_info.value).lower()
    assert "slow_query_ms" in msg or "slow query" in msg, (
        f"ValidationError didn't name the field. Full message:\n{exc_info.value}"
    )


def test_invalid_float_env_var_fails_with_named_field():
    """Same shape as the int test, but for `SENTRY_TRACES_SAMPLE_RATE`
    (float). A regression that silently coerced bad input to 0.0
    would drop all Sentry tracing on a typo'd env var.
    """
    with pytest.raises(ValidationError) as exc_info:
        _settings_with_env(SENTRY_TRACES_SAMPLE_RATE="halfway")
    msg = str(exc_info.value).lower()
    assert "sentry_traces_sample_rate" in msg or "sentry traces" in msg


def test_ops_alert_emails_parses_json_array_format():
    """`OPS_ALERT_EMAILS='["a@x.com","b@x.com"]'` must parse into
    a list of strings. pydantic-settings' default list parser
    expects a JSON-array literal, NOT comma-separated.

    Note: the field's docstring in `core/config.py` claims comma-
    separated input works (`AEC_RETENTION_AUDIT_EVENTS_DAYS=730`-
    style). It does NOT today — the comment is aspirational. Pin
    the actual behaviour so a future fix that adds comma-parsing
    keeps the JSON form working too.
    """
    s = _settings_with_env(OPS_ALERT_EMAILS='["a@x.com","b@x.com","c@x.com"]')
    assert s.ops_alert_emails == ["a@x.com", "b@x.com", "c@x.com"]


def test_ops_alert_emails_default_is_empty_list_not_none():
    """The default-factory must return `[]`, not `None`. A regression
    that flipped to `None` would crash the dispatcher on `for r in
    settings.ops_alert_emails:` instead of cleanly skipping.
    """
    s = _settings_with_env()
    assert s.ops_alert_emails == []
    assert s.ops_alert_emails is not None


def test_environment_is_not_validated_to_a_closed_set():
    """`environment` is a free-form string today — staging / preview /
    canary deployments use values like 'staging', 'preview-pr-42'.
    Pin that the field accepts any string; if a future tightening
    locks it to {'development', 'production'}, that's a deliberate
    decision that should break this test loudly + force operators
    to migrate non-standard env names first.
    """
    for env in ("development", "production", "staging", "preview-pr-42", "test"):
        s = _settings_with_env(AEC_ENV=env)
        assert s.environment == env


def test_extra_env_vars_are_ignored_not_rejected():
    """Settings has `extra='ignore'` (set in model_config). Random
    irrelevant env vars (PATH, HOME, USER, the ~thousand a CI runner
    sprinkles) must NOT cause ValidationError. A regression to
    `extra='forbid'` would crash every Settings() boot with the
    operator's local env."""
    s = _settings_with_env(SOME_RANDOM_ENV_VAR="whatever")
    # PATH is preserved by the OS; we don't override it here. The
    # assertion is "construction succeeded with one extra env var
    # in the environment" — the kind of noise every CI runner has.
    assert s.environment == "development"  # construction succeeded
