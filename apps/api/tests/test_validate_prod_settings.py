"""Unit tests for `core.config.validate_prod_settings`.

The validator is the gate that prevents a prod deploy from booting
with dev-default settings (JWT secret, CORS origins, localhost URLs,
unset metrics token, etc). main.py calls it at app construction and
raises with the joined issue list.

Tests below construct `Settings` instances with one rule violated at
a time so each rule is exercised in isolation. The "all clean" test
locks the happy path: a fully-configured prod settings object
returns no issues.

Why not just test main.py boot: this isolates the validation logic
from FastAPI / observability / DB-pool side effects. A test that's
"build a Settings dict, call the function, assert" is fast (~10ms
per test) and catches regressions in the rule list without spinning
up the whole app.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.config import validate_prod_settings


def _prod_settings(**overrides: object) -> SimpleNamespace:
    """Build a duck-typed settings object that PASSES validation, with
    kwargs overriding individual fields per test.

    Why SimpleNamespace and not `Settings(**defaults)`:
    `pydantic_settings.BaseSettings` reads from env vars at
    construction time, which overrides init kwargs. The CI runs with
    `AEC_ENV=test` set (and various test JWT secrets), so passing
    `environment='production'` as a kwarg gets silently overwritten
    by the env. SimpleNamespace bypasses pydantic entirely and just
    stores the attributes the validator reads. The validator only
    inspects attributes — it never instantiates Settings — so a
    duck-typed object works exactly the same.
    """
    defaults: dict[str, object] = {
        "environment": "production",
        "supabase_jwt_secret": "x" * 64,
        "cors_origins": ["https://app.aec-platform.vn"],
        "web_base_url": "https://app.aec-platform.vn",
        "public_web_url": "https://app.aec-platform.vn",
        "metrics_token": "metrics-token-32chars-or-more-yes-yes",
        "siteeye_ray_serve_url": "https://siteeye.aec-platform.vn",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------- Happy path: all clean ----------------------------------


def test_clean_prod_settings_have_no_issues():
    """The reference 'fully-configured prod' settings dict produces an
    empty list. Locks the happy path so a future rule that's
    accidentally too strict (rejects every prod settings) gets caught
    here, not by an operator at 2am."""
    issues = validate_prod_settings(_prod_settings())
    assert issues == [], f"Expected no issues, got {issues}"


def test_dev_environment_skips_validation_entirely():
    """The validator only fires when environment == 'production'.
    Local dev with every dev default must return [] so `make dev`
    doesn't error at boot."""
    s = SimpleNamespace(
        environment="development",
        supabase_jwt_secret="dev-secret-change-me",
        cors_origins=["http://localhost:3000"],
        web_base_url="http://localhost:3000",
        public_web_url="http://localhost:3000",
        metrics_token=None,
        siteeye_ray_serve_url="http://siteeye-safety:8000",
    )
    assert validate_prod_settings(s) == []


def test_staging_environment_skips_validation():
    """Staging is intentionally lax — it's a dev environment with a
    different name. Adding a 'staging' branch would create a third
    posture; we explicitly want only prod to gate."""
    s = SimpleNamespace(
        environment="staging",
        supabase_jwt_secret="dev-secret-change-me",
        cors_origins=["http://localhost:3000"],
        web_base_url="http://localhost:3000",
        public_web_url="http://localhost:3000",
        metrics_token=None,
        siteeye_ray_serve_url="http://siteeye-safety:8000",
    )
    assert validate_prod_settings(s) == []


# ---------- Per-rule violations ------------------------------------


def test_dev_jwt_secret_caught():
    issues = validate_prod_settings(_prod_settings(supabase_jwt_secret="dev-secret-change-me"))
    assert any("SUPABASE_JWT_SECRET" in i for i in issues), issues


def test_default_cors_caught():
    issues = validate_prod_settings(_prod_settings(cors_origins=["http://localhost:3000"]))
    assert any("CORS_ORIGINS" in i for i in issues), issues


def test_localhost_in_cors_caught_even_when_other_entries_present():
    """A prod CORS list with a real prod origin AND a stray localhost
    entry must still fail — the localhost one is the security risk."""
    issues = validate_prod_settings(
        _prod_settings(cors_origins=["https://app.aec-platform.vn", "http://localhost:3000"])
    )
    assert any("localhost" in i.lower() for i in issues), issues


def test_127_0_0_1_in_cors_also_caught():
    """`localhost` and `127.0.0.1` are equivalent attack vectors —
    catching one without the other would leave a half-closed door."""
    issues = validate_prod_settings(_prod_settings(cors_origins=["http://127.0.0.1:3000"]))
    assert any("127.0.0.1" in i for i in issues), issues


def test_http_web_base_url_caught():
    issues = validate_prod_settings(_prod_settings(web_base_url="http://app.aec-platform.vn"))
    assert any("WEB_BASE_URL" in i and "http://" in i for i in issues), issues


def test_localhost_web_base_url_caught():
    issues = validate_prod_settings(_prod_settings(web_base_url="https://localhost.aec-platform.vn"))
    assert any("WEB_BASE_URL" in i and "localhost" in i for i in issues), issues


def test_dev_public_web_url_caught():
    issues = validate_prod_settings(_prod_settings(public_web_url="http://localhost:3000"))
    assert any("PUBLIC_WEB_URL" in i for i in issues), issues


def test_https_localhost_public_web_url_passes():
    """A `https://localhost` URL is weird but technically not the dev
    default — only the http+localhost combo is. Don't over-reject —
    operators using a self-signed cert on localhost during staging
    deserve to fail on the http rule, not on this one."""
    issues = validate_prod_settings(_prod_settings(public_web_url="https://localhost"))
    assert not any("PUBLIC_WEB_URL" in i for i in issues), issues


def test_unset_metrics_token_caught():
    issues = validate_prod_settings(_prod_settings(metrics_token=None))
    assert any("AEC_METRICS_TOKEN" in i for i in issues), issues


def test_dev_siteeye_ray_serve_url_caught():
    issues = validate_prod_settings(_prod_settings(siteeye_ray_serve_url="http://siteeye-safety:8000"))
    assert any("SITEEYE_RAY_SERVE_URL" in i for i in issues), issues


def test_real_siteeye_ray_serve_url_passes():
    issues = validate_prod_settings(_prod_settings(siteeye_ray_serve_url="https://siteeye.aec-platform.vn"))
    assert not any("SITEEYE_RAY_SERVE_URL" in i for i in issues), issues


# ---------- Aggregation ---------------------------------------------


def test_multiple_violations_all_reported():
    """Operator triaging a boot failure should see EVERY issue at once
    — not "fix this, redeploy, discover the next." Pin that the
    function returns multiple rules in one call."""
    issues = validate_prod_settings(
        _prod_settings(
            supabase_jwt_secret="dev-secret-change-me",
            cors_origins=["http://localhost:3000"],
            metrics_token=None,
        )
    )
    assert len(issues) >= 3, f"Expected at least 3 issues, got: {issues}"
    joined = " | ".join(issues)
    assert "SUPABASE_JWT_SECRET" in joined
    assert "CORS_ORIGINS" in joined
    assert "AEC_METRICS_TOKEN" in joined


# ---------- Boot-integration smoke test -----------------------------


def test_main_app_boots_in_dev_with_defaults():
    """Sanity-check the integration: importing main with the dev
    settings (the test fixture's default) must succeed. If the
    validator regressed and started rejecting dev defaults, this
    catches it before the dev environment goes red."""
    # Imports inside the test so monkeypatched settings don't leak
    # into other tests. The fixture loads `Settings()` from the env,
    # which in CI defaults to AEC_ENV=test (dev-equivalent), so the
    # production gate doesn't fire.
    from main import app  # noqa: F401 — import-as-execution

    # Reaching here means create_app() didn't raise.
    assert app is not None
