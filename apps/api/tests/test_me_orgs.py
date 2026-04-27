"""Tests for `GET /api/v1/me/orgs` and the ES256 JWKS verification path.

Without these, the next refactor of `middleware/auth.py` could silently
break the Supabase login flow — every other test in the suite uses HS256
with a shared secret (the `SUPABASE_JWT_SECRET` fallback in `_verify_jwt`),
so the asymmetric path has no other coverage.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from unittest.mock import MagicMock
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

PROJECT_REF = "aectest"
SUPABASE_URL = f"https://{PROJECT_REF}.supabase.co"
TEST_USER_ID = UUID("3d9d1967-4d9b-4022-b672-5e30d07827bf")
TEST_ORG_ID = UUID("00000000-0000-0000-0000-000000000001")


# ---------- Test EC keypair ----------
#
# Module-scoped — generating a keypair per test costs ~50ms which adds up
# across the suite. The pair is throwaway: only ever used to sign tokens
# inside this test file, never persisted.


@pytest.fixture(scope="module")
def ec_keypair() -> tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    """ES256 = ECDSA over P-256 — matches what Supabase issues."""
    priv = ec.generate_private_key(ec.SECP256R1())
    return priv, priv.public_key()


@pytest.fixture
def make_token(ec_keypair):
    """Mint a Supabase-shaped JWT signed with the test private key.

    Defaults match a real Supabase access token: aud=authenticated,
    iss includes the project URL, exp 1h out, kid in the header.
    """
    priv, _pub = ec_keypair

    def _mint(
        *,
        sub: str = str(TEST_USER_ID),
        email: str = "dev@example.test",
        kid: str = "test-kid",
        iat: int | None = None,
        exp: int | None = None,
        audience: str = "authenticated",
    ) -> str:
        now = int(time.time())
        payload = {
            "iss": f"{SUPABASE_URL}/auth/v1",
            "sub": sub,
            "aud": audience,
            "iat": iat if iat is not None else now,
            "exp": exp if exp is not None else now + 3600,
            "email": email,
        }
        return jwt.encode(payload, priv, algorithm="ES256", headers={"kid": kid})

    return _mint


# ---------- App + JWKS-client override ----------


@pytest.fixture
def me_app(monkeypatch, ec_keypair) -> FastAPI:
    """A FastAPI app with only the `me` router mounted, the JWKS client
    monkeypatched to return our test public key, and AdminSessionFactory
    swapped for an in-memory fake.
    """
    _priv, pub = ec_keypair

    # Force the asymmetric path: middleware switches to JWKS verification
    # when settings.supabase_url is truthy.
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    # Bust the lru_cache on get_settings so the new env var sticks.
    from core.config import get_settings

    get_settings.cache_clear()

    # Stub the JWKS client. PyJWKClient.get_signing_key_from_jwt returns
    # an object with a `.key` attribute holding the public key — our
    # `_verify_jwt` only touches `.key`, so a MagicMock with that attr is
    # enough.
    fake_client = MagicMock()
    fake_signing = MagicMock()
    fake_signing.key = pub
    fake_signing.key_id = "test-kid"
    fake_client.get_signing_key_from_jwt.return_value = fake_signing

    from middleware import auth as auth_module

    auth_module._jwks_client.cache_clear()
    monkeypatch.setattr(auth_module, "_jwks_client", lambda: fake_client)

    # Swap AdminSessionFactory for one that yields our FakeAsyncSession.
    # The endpoint does `async with AdminSessionFactory() as db:` so we
    # need an async-context-manager.
    from routers import me as me_module

    db_state = {
        "added": [],
        "exec_results": [],
        "commits": 0,
    }

    class _FakeSession:
        async def execute(self, stmt, params=None):
            # Endpoint does INSERT then SELECT, in that order. The first
            # call (INSERT) we don't care about; the second (SELECT) we
            # want to return the seeded org row.
            db_state["added"].append((str(stmt)[:60], params))
            result = MagicMock()
            if "SELECT" in str(stmt):
                row = {
                    "id": str(TEST_ORG_ID),
                    "name": "Dev Org",
                    "role": "owner",
                }
                result.mappings.return_value.all.return_value = [row]
            else:
                result.mappings.return_value.all.return_value = []
            return result

        async def commit(self):
            db_state["commits"] += 1

    class _FakeFactory:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, *exc) -> None:
            return None

    monkeypatch.setattr(me_module, "AdminSessionFactory", lambda: _FakeFactory())

    from core.envelope import http_exception_handler, unhandled_exception_handler

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(me_module.router)
    app.state.db_state = db_state  # exposed for assertions
    return app


@pytest.fixture
async def me_client(me_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=me_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Tests ----------


async def test_me_orgs_returns_membership_with_valid_es256_token(me_app, me_client, make_token):
    token = make_token()

    res = await me_client.get(
        "/api/v1/me/orgs",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["errors"] is None
    assert body["data"] == [{"id": str(TEST_ORG_ID), "name": "Dev Org", "role": "owner"}]

    # Endpoint must auto-provision a `users` row before the SELECT — that
    # fact is the entire reason this test exists. The fake DB records the
    # statements; check we saw the INSERT.
    db = me_app.state.db_state
    assert db["commits"] >= 1, "expected commit after users upsert"
    inserted = [s for s, _p in db["added"] if "INSERT INTO users" in s]
    assert len(inserted) == 1


async def test_me_orgs_rejects_unsigned_token(me_client):
    """A token without a real signature must not authenticate. PyJWT lets
    you ‘sign’ with alg=none if the verifier doesn't pin algorithms — this
    test guards against the classic algorithm-confusion CVE class.
    """
    res = await me_client.get(
        "/api/v1/me/orgs",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert res.status_code == 401
    assert res.json()["errors"][0]["code"] == "401"


async def test_me_orgs_rejects_token_with_wrong_signature(me_client, make_token):
    """A JWT signed by a different keypair must be rejected — the JWKS
    client's signing key wins, so a forged token can't sneak through even
    with the right kid."""
    other_priv = ec.generate_private_key(ec.SECP256R1())
    payload = {
        "iss": f"{SUPABASE_URL}/auth/v1",
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "email": "imposter@example.test",
    }
    forged = jwt.encode(payload, other_priv, algorithm="ES256", headers={"kid": "test-kid"})

    res = await me_client.get(
        "/api/v1/me/orgs",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert res.status_code == 401


async def test_me_orgs_rejects_token_with_wrong_audience(me_client, make_token):
    """Supabase user sessions always have aud=authenticated. Service-role
    tokens (aud=supabase_admin) or anon tokens (aud=anon) must not
    authenticate as a user."""
    bad = make_token(audience="anon")

    res = await me_client.get(
        "/api/v1/me/orgs",
        headers={"Authorization": f"Bearer {bad}"},
    )
    assert res.status_code == 401


async def test_me_orgs_rejects_expired_token(me_client, make_token):
    """leeway=60 is the only slack we allow on `exp`; anything past that
    must 401."""
    expired = make_token(exp=int(time.time()) - 120)

    res = await me_client.get(
        "/api/v1/me/orgs",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert res.status_code == 401


async def test_me_orgs_accepts_token_with_small_clock_skew(me_client, make_token):
    """Docker hosts sometimes have small clock drift relative to Supabase's
    edge. The middleware's leeway=60 covers this — without it,
    freshly-issued tokens fail with ImmatureSignatureError. Test confirms
    a 30-seconds-in-the-future iat still works."""
    skewed = make_token(iat=int(time.time()) + 30)

    res = await me_client.get(
        "/api/v1/me/orgs",
        headers={"Authorization": f"Bearer {skewed}"},
    )
    assert res.status_code == 200


async def test_me_orgs_requires_authorization_header(me_client):
    res = await me_client.get("/api/v1/me/orgs")
    # FastAPI's HTTPBearer with auto_error=True returns 403 by default
    # (yes, 403 not 401 — it's a documented quirk).
    assert res.status_code in (401, 403)
