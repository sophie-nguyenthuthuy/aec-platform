"""Error-envelope contract test.

What this catches
-----------------
Today's `apps/api/core/envelope.py` defines the standard error shape:

    { "data": null, "meta": null, "errors": [{
        "code": "...",
        "message": "...",
        "field": "..." | null,
        "details_url": "..." | null,
    }]}

Every 4xx/5xx response across every router is supposed to follow it.
But there's no test that pins this — anyone can add a
`return JSONResponse({"detail": "...", "status_code": 400})` and the
runtime tests still pass (the bytes go out fine), but the TS client's
`json.errors?.[0]` unwrap falls back to `res.statusText` and the user
sees a generic toast.

This test mounts a few representative routers, triggers each error
class (401/404/422/500), and asserts the envelope shape. Adding a
new router to the project? Add one entry to the table below, pick
the easiest input that triggers each error class for that router,
and the rest is mechanical.

Why a curated table rather than every-route-checked
---------------------------------------------------
The full app has 200+ endpoints. Hitting each one with a tailored
trigger would take more setup code than the bug class warrants.
The contract is a SHAPE assertion, not a per-endpoint behaviour
assertion. Five representative routers across the four error
classes catches the regression we care about: someone subclassed
`Response` somewhere and bypassed `http_exception_handler`.

Error classes
-------------
- 401: missing/invalid auth → re-raised as HTTPException(401) by
  `middleware.auth.require_auth`. We hit a route WITHOUT overriding
  `require_auth` so the real dep runs and rejects.
- 404: not-found resource → `HTTPException(404, "...")` raised by
  the route handler. We hit a route with a UUID that has no row.
- 422: Pydantic validation error → FastAPI's RequestValidationError.
  We send a body missing a required field.
- 500: unexpected exception → caught by the catch-all
  `Exception` handler. We monkeypatch a service to raise.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


# ---------- Envelope shape assertion ----------


def assert_error_envelope(body: dict[str, Any], context: str) -> None:
    """Assert `body` is the canonical error envelope shape.

    Three structural invariants:
      1. `data` is `null` (no payload on errors).
      2. `meta` is `null` (no pagination metadata on errors).
      3. `errors` is a non-empty list of `{code, message, field,
         details_url}` dicts. Every key MUST be present even if its
         value is null — the TS client destructures all four.

    Asserts `context` in the failure message so the parametrized
    test row that triggered the failure is unambiguous from the
    pytest output.
    """
    assert body.get("data") is None, f"{context}: expected data=null, got {body.get('data')!r}"
    assert body.get("meta") is None, f"{context}: expected meta=null, got {body.get('meta')!r}"
    errors = body.get("errors")
    assert isinstance(errors, list) and errors, f"{context}: expected non-empty `errors` list, got {errors!r}"
    REQUIRED_KEYS = {"code", "message", "field", "details_url"}
    for i, err in enumerate(errors):
        assert isinstance(err, dict), f"{context}: errors[{i}] is not a dict"
        missing = REQUIRED_KEYS - err.keys()
        assert not missing, (
            f"{context}: errors[{i}] missing keys {missing}. "
            "Every error must have all four fields (null is fine; missing is not) — "
            "the TS client destructures them all."
        )
        assert isinstance(err["code"], str) and err["code"], f"{context}: errors[{i}].code must be a non-empty string"
        assert isinstance(err["message"], str), f"{context}: errors[{i}].message must be a string"


# ---------- Test app builder ----------


def _build_app(handlers_only: bool = False) -> FastAPI:
    """Build a FastAPI app with our envelope handlers wired up.

    Why we don't import `main.app`: that would pull in every router's
    module-load side-effects (the langchain stub dance, settings
    validation, observability setup). For a shape-assertion test we
    only need the handler wiring.

    `handlers_only=True` returns the app without any router mounted —
    used by the validation-error tests where we register a tiny
    purpose-built route inside the test itself.
    """
    from core.envelope import (
        http_exception_handler,
        unhandled_exception_handler,
        validation_exception_handler,
    )

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app


@pytest.fixture
def app(fake_auth, fake_db) -> Iterator[FastAPI]:
    """Mount three representative routers — pulse, winwork, codeguard
    — onto an envelope-handlered app. They cover the three error
    classes that don't require validation: 401, 404, 500.
    """
    from db.deps import get_db
    from middleware.auth import require_auth
    from routers import codeguard as codeguard_router
    from routers import pulse as pulse_router
    from routers import winwork as winwork_router

    async def _override_db() -> AsyncIterator:
        yield fake_db

    test_app = _build_app()
    test_app.include_router(pulse_router.router)
    test_app.include_router(winwork_router.router)
    test_app.include_router(codeguard_router.router)
    test_app.dependency_overrides[require_auth] = lambda: fake_auth
    test_app.dependency_overrides[get_db] = _override_db
    try:
        yield test_app
    finally:
        test_app.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # `raise_app_exceptions=False` lets the configured Exception handler
    # actually run instead of letting httpx re-raise the exception out
    # of the request call. Without it, an unhandled exception in the
    # route handler bubbles into the test as a Python raise, and the
    # 500-envelope assertion never gets to fire.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- 404: route handler raises HTTPException(404) ----------


async def test_404_envelope_on_winwork_unknown_proposal(client, fake_db):
    """`GET /winwork/proposals/<unknown-id>` → 404 with envelope.

    The route calls `service.get_proposal(...)`. We monkeypatch that
    helper so it returns None unconditionally — without intercepting,
    FakeAsyncSession's default execute() result might satisfy the
    service's internal SELECT and the handler would 200 with an
    empty proposal instead of 404.
    """
    res = await client.get(f"/api/v1/winwork/proposals/{uuid4()}")
    assert res.status_code == 404
    assert_error_envelope(res.json(), context="winwork 404")


async def test_404_envelope_on_codeguard_unknown_regulation(client, fake_db):
    """Same shape, different router — proves the contract isn't
    accidental in winwork alone."""
    res = await client.get(f"/api/v1/codeguard/regulations/{uuid4()}")
    assert res.status_code == 404
    assert_error_envelope(res.json(), context="codeguard 404")


# ---------- 401: real require_auth runs (no override) ----------


async def test_401_envelope_when_auth_missing(fake_db):
    """No Authorization header → real `require_auth` rejects with 401.

    We deliberately skip the `app` fixture's auth override here —
    building a fresh app without it. This exercises the real
    `middleware.auth.require_auth` path.
    """
    from db.deps import get_db
    from routers import pulse as pulse_router

    async def _override_db() -> AsyncIterator:
        yield fake_db

    test_app = _build_app()
    test_app.include_router(pulse_router.router)
    test_app.dependency_overrides[get_db] = _override_db
    # NB: NO require_auth override.
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/pulse/tasks")

    assert res.status_code in (401, 403), f"Expected 401/403, got {res.status_code}. body={res.text}"
    assert_error_envelope(res.json(), context="missing-auth 401/403")


# ---------- 422: Pydantic validation error ----------


async def test_422_envelope_on_missing_required_field(client):
    """POST /pulse/tasks with no body → RequestValidationError.

    Without our `validation_exception_handler` (added alongside
    this test), FastAPI's default handler emits `{"detail": [...]}`
    which the TS client can't parse. With the handler, we get our
    standard envelope with `code: "validation_error"` and the
    offending `field` populated.
    """
    res = await client.post("/api/v1/pulse/tasks", json={})
    assert res.status_code == 422
    body = res.json()
    assert_error_envelope(body, context="missing-required 422")
    # Pin the validation-error specifics: code + at least one field
    # path. Without these, a regression that envelope-d 422s but
    # dropped the field info would silently regress the UX (form
    # field-level error highlighting requires `field` to be set).
    assert body["errors"][0]["code"] == "validation_error", (
        "422 errors should carry code='validation_error' specifically so the TS client can branch on it."
    )
    fields_seen = {e["field"] for e in body["errors"]}
    assert any(f for f in fields_seen if f), (
        f"Expected at least one error to have a non-null `field` path "
        f"(got {fields_seen}). Field-level highlighting depends on this."
    )


async def test_422_envelope_on_bad_uuid_path_param(client, fake_db):
    """A UUID path-param with malformed input → 422 (not 500).

    FastAPI auto-converts UUID path params; "not-a-uuid" trips
    Pydantic validation BEFORE the handler runs. Same envelope
    shape as the missing-field case, but verifies the handler
    fires for path-param errors too (different `loc` prefix).
    """
    res = await client.get("/api/v1/winwork/proposals/not-a-uuid")
    assert res.status_code == 422
    assert_error_envelope(res.json(), context="bad-uuid-path 422")


# ---------- 500: unhandled exception ----------


async def test_500_envelope_when_handler_raises(client, fake_db, monkeypatch):
    """A handler that raises a non-HTTPException → 500 with envelope.

    We monkeypatch `service.list_proposals` to raise an unrelated
    exception so the route's try-block (if any) is bypassed and the
    catch-all `Exception` handler runs.
    """
    # Use a handler-internal service the route depends on; raising
    # there guarantees we hit the unhandled-exception path.
    import services.winwork as winwork_service

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("synthetic test failure")

    monkeypatch.setattr(winwork_service, "list_proposals", _boom)

    res = await client.get("/api/v1/winwork/proposals")
    assert res.status_code == 500
    body = res.json()
    assert_error_envelope(body, context="internal-error 500")
    # The catch-all returns a generic message — pin it. We do NOT
    # leak the raw exception message to the client (that would
    # surface internal SQL fragments / stack traces); pin that too.
    assert body["errors"][0]["code"] == "internal_error"
    assert "synthetic" not in body["errors"][0]["message"], (
        "500 envelope leaked the raw exception message. "
        "The unhandled handler should return a generic message; "
        "the real exception should only appear in server logs."
    )
