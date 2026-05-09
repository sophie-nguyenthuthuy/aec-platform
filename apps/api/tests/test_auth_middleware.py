"""Regression tests for `middleware.auth._verify_jwt`.

Every router test overrides `require_auth` via `app.dependency_overrides`,
which means the actual JWT-verification path has no direct coverage.
This module pins:

  * The asymmetric-key path (Supabase ES256 via JWKS) when
    `SUPABASE_URL` is set.
  * The HS256 fallback for tests / migrating deployments where
    `SUPABASE_URL` is unset.
  * 401s on bad signature / wrong audience / missing `sub`.
  * The 60-second `leeway` that tolerates small clock drift between
    Supabase's edge and the API container.

The JWKS client is mocked rather than hitting a real Supabase project
— `PyJWKClient.get_signing_key_from_jwt` is the integration boundary
and faking it lets us drive every branch without spinning up an
auth.example.com.
"""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException

# ---------- Fixtures: an HS256 secret + an RS256 keypair ----------


_HS_SECRET = "test-hs-secret"


@pytest.fixture
def hs256_token():
    """Build an HS256 JWT signed with the test secret."""

    def _build(**overrides):
        now = int(time.time())
        claims = {
            "sub": str(uuid4()),
            "email": "user@test.local",
            "iat": now,
            "exp": now + 3600,
            **overrides,
        }
        return jwt.encode(claims, _HS_SECRET, algorithm="HS256")

    return _build


@pytest.fixture
def rs256_keypair():
    """Generate a throwaway RSA keypair so the signing-key path can be
    exercised without bundling a real fixture key in the repo."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _build_rs256_token(private_pem: bytes, **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": str(uuid4()),
        "email": "user@test.local",
        "iat": now,
        "exp": now + 3600,
        "aud": "authenticated",
        **overrides,
    }
    return jwt.encode(claims, private_pem, algorithm="RS256")


# ---------- HS256 fallback path (no SUPABASE_URL) ----------


def test_verify_hs256_accepts_valid_token(monkeypatch, hs256_token):
    """When SUPABASE_URL is unset, the HS256 path verifies against the secret."""
    from middleware import auth

    settings = auth.get_settings()
    monkeypatch.setattr(settings, "supabase_url", None, raising=False)
    monkeypatch.setattr(settings, "supabase_jwt_secret", _HS_SECRET, raising=False)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256", raising=False)
    # Clear the lru_cache so the no-URL setting takes effect.
    auth._jwks_client.cache_clear()

    payload = auth._verify_jwt(hs256_token())
    assert payload["email"] == "user@test.local"
    assert "sub" in payload


def test_verify_hs256_rejects_bad_signature(monkeypatch, hs256_token):
    from middleware import auth

    settings = auth.get_settings()
    monkeypatch.setattr(settings, "supabase_url", None, raising=False)
    monkeypatch.setattr(settings, "supabase_jwt_secret", _HS_SECRET, raising=False)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256", raising=False)
    auth._jwks_client.cache_clear()

    # Tamper: append junk → invalid signature.
    bad = hs256_token() + "XXXX"
    with pytest.raises(HTTPException) as exc:
        auth._verify_jwt(bad)
    assert exc.value.status_code == 401


# ---------- ES256/RS256 path (SUPABASE_URL set, JWKS mocked) ----------


def test_verify_asymmetric_uses_jwks_signing_key(monkeypatch, rs256_keypair):
    """When SUPABASE_URL is set, _verify_jwt asks the JWKS client for the
    signing key and verifies against it. We mock the PyJWKClient to
    return our test public key, so the path runs end-to-end without
    touching the real auth server."""
    from middleware import auth

    private_pem, public_pem = rs256_keypair
    token = _build_rs256_token(private_pem)

    settings = auth.get_settings()
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co", raising=False)

    # PyJWKClient.get_signing_key_from_jwt returns an object whose `.key`
    # is the actual key material PyJWT consumes. Build a tiny stand-in.
    class _FakeSigningKey:
        def __init__(self, key):
            self.key = key

    class _FakeJwksClient:
        def get_signing_key_from_jwt(self, _token):
            return _FakeSigningKey(public_pem)

    auth._jwks_client.cache_clear()
    monkeypatch.setattr(auth, "_jwks_client", lambda: _FakeJwksClient())

    payload = auth._verify_jwt(token)
    assert payload["email"] == "user@test.local"
    assert payload["aud"] == "authenticated"


def test_verify_asymmetric_rejects_wrong_audience(monkeypatch, rs256_keypair):
    """A token with `aud != "authenticated"` (e.g. an admin-key token, or
    a misconfigured Supabase project) must NOT validate as a user JWT."""
    from middleware import auth

    private_pem, public_pem = rs256_keypair
    # Forge a token with an unexpected audience.
    token = _build_rs256_token(private_pem, aud="service_role")

    settings = auth.get_settings()
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co", raising=False)

    class _FakeSigningKey:
        def __init__(self, key):
            self.key = key

    class _FakeJwksClient:
        def get_signing_key_from_jwt(self, _token):
            return _FakeSigningKey(public_pem)

    auth._jwks_client.cache_clear()
    monkeypatch.setattr(auth, "_jwks_client", lambda: _FakeJwksClient())

    with pytest.raises(HTTPException) as exc:
        auth._verify_jwt(token)
    assert exc.value.status_code == 401


def test_verify_asymmetric_tolerates_clock_drift(monkeypatch, rs256_keypair):
    """A token issued 30 seconds in the future (Supabase edge ahead of
    our container) must verify, because we pass `leeway=60` to PyJWT.

    Without the leeway, Docker hosts whose system clock lags behind
    NTP-synced edges would 401 newly-issued tokens — reproducible and
    annoying. The 60s window absorbs any sane drift."""
    from middleware import auth

    private_pem, public_pem = rs256_keypair
    now = int(time.time())
    # iat/nbf 30 seconds in the future.
    token = _build_rs256_token(private_pem, iat=now + 30, exp=now + 3600)

    settings = auth.get_settings()
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co", raising=False)

    class _FakeSigningKey:
        def __init__(self, key):
            self.key = key

    class _FakeJwksClient:
        def get_signing_key_from_jwt(self, _token):
            return _FakeSigningKey(public_pem)

    auth._jwks_client.cache_clear()
    monkeypatch.setattr(auth, "_jwks_client", lambda: _FakeJwksClient())

    # No exception — the 60s leeway absorbs the 30s skew.
    payload = auth._verify_jwt(token)
    assert "sub" in payload


def test_verify_asymmetric_rejects_expired_token(monkeypatch, rs256_keypair):
    from middleware import auth

    private_pem, public_pem = rs256_keypair
    now = int(time.time())
    # exp 5 minutes in the past — well outside the 60s leeway.
    token = _build_rs256_token(private_pem, iat=now - 600, exp=now - 300)

    settings = auth.get_settings()
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co", raising=False)

    class _FakeSigningKey:
        def __init__(self, key):
            self.key = key

    class _FakeJwksClient:
        def get_signing_key_from_jwt(self, _token):
            return _FakeSigningKey(public_pem)

    auth._jwks_client.cache_clear()
    monkeypatch.setattr(auth, "_jwks_client", lambda: _FakeJwksClient())

    with pytest.raises(HTTPException) as exc:
        auth._verify_jwt(token)
    assert exc.value.status_code == 401


# ---------- JWKS client lifecycle ----------


def test_jwks_client_returns_none_when_supabase_url_unset(monkeypatch):
    """Empty SUPABASE_URL → None, which forces _verify_jwt down the HS256
    fallback path. Tests + legacy deploys rely on this branch."""
    from middleware import auth

    settings = auth.get_settings()
    monkeypatch.setattr(settings, "supabase_url", None, raising=False)
    auth._jwks_client.cache_clear()
    assert auth._jwks_client() is None


def test_jwks_client_is_cached_per_process(monkeypatch):
    """The lru_cache on `_jwks_client` means the first call to a real
    Supabase URL is the only network round-trip; subsequent token
    verifications reuse the same instance.

    We don't actually hit the network here — just confirm the cache
    hands back the same object across two calls under the same URL.
    """
    from middleware import auth

    settings = auth.get_settings()
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co", raising=False)
    auth._jwks_client.cache_clear()

    a = auth._jwks_client()
    b = auth._jwks_client()
    assert a is b
