"""Pin the response-envelope shape exposed by `core.envelope`.

Every router in this codebase returns through `core.envelope.ok(...)`
(or its paginated cousin), and every error handler funnels through
`http_exception_handler` / `unhandled_exception_handler`. The frontend
universally unwraps `res.data` from the envelope (see
`apps/web/lib/api.ts::apiFetch`), and every `apps/web/hooks/**` test
verifies the call site does so.

If the envelope's shape drifts on either side, the entire app silently
breaks: the frontend reads `undefined` from a missing field, components
render empty states forever, and nothing 500s — the worst-class
failure mode (a green deploy that quietly stops working).

This file is a read-only contract pin. It survives the upstream-revert
pattern because tests/ files have historically not been a target. If
the envelope helpers ever get reverted to a wrong shape, this test
goes RED on the next CI run rather than allowing the silent-break
state to land.

What we pin:

  * **`ok(data, meta)`** — keys exactly `{data, meta, errors}`.
    `errors` is `None` (frontend looks at `errors == null` to mean
    "successful response").

  * **`paginated(items, page, per_page, total)`** — wraps `ok` with
    a Meta. Keys on `meta` are exactly `{page, per_page, total}`.

  * **`Envelope[T]`** — the typed Pydantic shape. Re-asserts `data`
    is `Optional` so non-list responses (eg `null` from a delete
    that returns nothing) round-trip cleanly.

  * **`ErrorDetail`** — keys `{code, message, field, details_url}`.
    `details_url` is the codeguard 429 deep-link path; a rename
    here = the "go fix your quota" CTA disappears silently.

  * **HTTPException handler** — accepts both `str` and `dict` detail
    shapes (the dict form is how codeguard surfaces `details_url`).

If any of these flip, the change has to be deliberate AND has to
update both this pin and the matching frontend pins in
`apps/web/lib/__tests__/api.test.ts`.
"""

from __future__ import annotations

import inspect

import pytest

# ---------- ok() shape ----------


def test_ok_returns_envelope_keys():
    """The minimal happy-path return: `{data, meta, errors}` with
    `errors=None`. The frontend's `apiFetch` reads `res.data`
    directly; a key rename = silent undefined-everywhere."""
    from core.envelope import ok

    out = ok({"foo": "bar"})
    assert set(out.keys()) == {"data", "meta", "errors"}, (
        f"ok() returned keys {set(out.keys())}; want {'data', 'meta', 'errors'}"
    )
    assert out["data"] == {"foo": "bar"}
    assert out["meta"] is None
    assert out["errors"] is None, (
        "ok() MUST return errors=None — the frontend treats errors==null as the success discriminator."
    )


def test_ok_passes_through_data_unchanged():
    """`ok` is a thin wrapper — it doesn't model_dump or coerce.
    A future refactor that started JSON-coercing here would break
    callers that pass already-coerced ORM-derived dicts (the
    coercion would re-coerce datetimes into strings into bytes
    into…)."""
    from core.envelope import ok

    sentinel = object()
    out = ok(sentinel)
    assert out["data"] is sentinel


def test_ok_wraps_meta_via_model_dump():
    """When meta is provided it's `model_dump`'d to a plain dict —
    the response goes through FastAPI's default JSON encoder, which
    can't serialise BaseModel instances directly without that step."""
    from core.envelope import Meta, ok

    m = Meta(page=1, per_page=20, total=42)
    out = ok([], m)
    assert out["meta"] == {"page": 1, "per_page": 20, "total": 42}


# ---------- paginated() shape ----------


def test_paginated_returns_meta_keys():
    """The list-endpoint convention. Frontend reads
    `res.meta.{page,per_page,total}` directly to drive pagers; a
    rename here = pagers freeze on page 1 forever."""
    from core.envelope import paginated

    out = paginated([1, 2, 3], page=2, per_page=20, total=43)
    assert set(out["meta"].keys()) == {"page", "per_page", "total"}, (
        f"paginated meta keys drifted: {set(out['meta'].keys())}"
    )
    assert out["meta"]["page"] == 2
    assert out["meta"]["per_page"] == 20
    assert out["meta"]["total"] == 43
    assert out["data"] == [1, 2, 3]


def test_paginated_signature_pinned():
    """Pin the keyword names. Callers (every list endpoint) pass these
    by name — a positional rename would silently break every list
    endpoint's pager metadata."""
    from core.envelope import paginated

    sig = inspect.signature(paginated)
    assert list(sig.parameters.keys()) == ["items", "page", "per_page", "total"], (
        f"paginated signature drifted: {list(sig.parameters.keys())}"
    )


# ---------- Envelope[T] schema ----------


def test_envelope_is_generic_with_optional_data():
    """The Pydantic envelope used in OpenAPI signatures. `data` is
    optional so a `null` response (e.g. DELETE returning nothing)
    is a valid envelope without forcing every endpoint to invent
    a placeholder."""
    from core.envelope import Envelope

    fields = Envelope.model_fields
    assert set(fields.keys()) == {"data", "meta", "errors"}, f"Envelope fields drifted: {set(fields.keys())}"

    # `data` MUST default to None (not be required) so a 200 with an
    # empty payload still constructs.
    assert fields["data"].is_required() is False
    assert fields["meta"].is_required() is False
    assert fields["errors"].is_required() is False


# ---------- Meta + ErrorDetail field sets ----------


def test_meta_field_set():
    """The Meta model's field set. Every list endpoint's `meta`
    JSON has these three integer fields."""
    from core.envelope import Meta

    fields = Meta.model_fields
    assert set(fields.keys()) == {"page", "per_page", "total"}, f"Meta fields drifted: {set(fields.keys())}"
    # All optional — a non-list endpoint that wants a custom Meta
    # subset shouldn't fail validation by default.
    for name in ("page", "per_page", "total"):
        assert fields[name].is_required() is False


def test_error_detail_field_set():
    """The error-row model. Frontend's error toast reads `code` +
    `message` + (optionally) `details_url`. The `field` slot is
    used for form-validation surfacing — a rename = inputs lose
    their inline error chrome."""
    from core.envelope import ErrorDetail

    fields = ErrorDetail.model_fields
    assert set(fields.keys()) == {"code", "message", "field", "details_url"}, (
        f"ErrorDetail fields drifted: {set(fields.keys())}"
    )
    # `code` + `message` are required (every error has them);
    # `field` + `details_url` are optional (only some errors carry).
    assert fields["code"].is_required() is True
    assert fields["message"].is_required() is True
    assert fields["field"].is_required() is False
    assert fields["details_url"].is_required() is False


def test_error_detail_details_url_field_present():
    """The `details_url` field is what powers the codeguard 429's
    "go to /codeguard/quota" deep-link CTA. Removing it doesn't
    break the JSON shape (extra-fields tolerant) but DOES silently
    break the CTA. Pin its presence explicitly so the rename has
    to be deliberate."""
    from core.envelope import ErrorDetail

    e = ErrorDetail(code="429", message="quota exceeded", details_url="/codeguard/quota")
    assert e.details_url == "/codeguard/quota"


# ---------- HTTPException handler shape ----------


@pytest.mark.asyncio
async def test_http_exception_handler_accepts_string_detail():
    """The traditional FastAPI form: `HTTPException(401, "Bad token")`.
    This is the form 99% of `raise HTTPException(...)` sites use; a
    regression that only handled the dict form would 500 the API
    everywhere people raise the simple form."""
    from fastapi import HTTPException
    from fastapi.requests import Request

    from core.envelope import http_exception_handler

    req = Request({"type": "http", "method": "GET", "headers": []})
    exc = HTTPException(status_code=401, detail="Invalid token")

    resp = await http_exception_handler(req, exc)
    assert resp.status_code == 401
    body = resp.body.decode()
    assert '"message":"Invalid token"' in body
    assert '"code":"401"' in body
    # No details_url on the str form.
    assert '"details_url":null' in body


@pytest.mark.asyncio
async def test_http_exception_handler_accepts_dict_detail_with_details_url():
    """The structured form codeguard's quota cap-check uses:
    `HTTPException(429, {"message": ..., "details_url": "/codeguard/quota"})`.
    The handler MUST pull `details_url` out and surface it — a
    regression that ignored it would silently kill the CTA."""
    from fastapi import HTTPException
    from fastapi.requests import Request

    from core.envelope import http_exception_handler

    req = Request({"type": "http", "method": "GET", "headers": []})
    exc = HTTPException(
        status_code=429,
        detail={"message": "quota exceeded", "details_url": "/codeguard/quota"},
    )

    resp = await http_exception_handler(req, exc)
    assert resp.status_code == 429
    body = resp.body.decode()
    assert '"message":"quota exceeded"' in body
    assert '"details_url":"/codeguard/quota"' in body


@pytest.mark.asyncio
async def test_http_exception_handler_forwards_response_headers():
    """`exc.headers` is how rate-limited callers surface
    `Retry-After` and 401 callers surface `WWW-Authenticate`. Not
    forwarding silently breaks every rate-limit client that backs
    off based on the header."""
    from fastapi import HTTPException
    from fastapi.requests import Request

    from core.envelope import http_exception_handler

    req = Request({"type": "http", "method": "GET", "headers": []})
    exc = HTTPException(
        status_code=429,
        detail="Too many requests",
        headers={"Retry-After": "30"},
    )

    resp = await http_exception_handler(req, exc)
    assert resp.headers.get("retry-after") == "30", (
        "http_exception_handler dropped exc.headers — rate-limit clients can't back off without Retry-After."
    )


# ---------- 500 handler shape ----------


@pytest.mark.asyncio
async def test_unhandled_exception_handler_envelope_shape():
    """The catch-all 500 path. MUST match the same envelope shape as
    the 4xx handler so the frontend's error parser works uniformly
    on both. Code is the literal string `"internal_error"` —
    consumers grep for that string to differentiate "we crashed"
    from "you sent bad input."""
    from fastapi.requests import Request

    from core.envelope import unhandled_exception_handler

    req = Request({"type": "http", "method": "GET", "headers": []})
    resp = await unhandled_exception_handler(req, RuntimeError("boom"))
    assert resp.status_code == 500
    body = resp.body.decode()
    assert '"code":"internal_error"' in body, (
        "500 handler's error code drifted from `internal_error` — "
        "frontend grep checks would silently miss internal errors."
    )
    # `data` and `meta` are nulled (no payload on a crash).
    assert '"data":null' in body
    assert '"meta":null' in body


# ---------- 422 validation handler shape ----------
#
# Added when `core.envelope.validation_exception_handler` shipped to
# replace FastAPI's default 422 body. Without this handler, every
# form-validation error landed in the TS client's "unknown error"
# bucket because the default `{"detail": [...]}` shape doesn't match
# the envelope contract. These pins guard the contract.


@pytest.mark.asyncio
async def test_validation_handler_emits_envelope_shape():
    """422 responses MUST match the same `{data, meta, errors}`
    envelope as 4xx/5xx so the TS client's parser works uniformly.
    A regression that emitted FastAPI's default `{"detail": [...]}`
    shape would silently break form-error highlighting EVERYWHERE."""
    from fastapi.exceptions import RequestValidationError
    from fastapi.requests import Request

    from core.envelope import validation_exception_handler

    req = Request({"type": "http", "method": "GET", "headers": []})
    exc = RequestValidationError(
        errors=[
            {
                "type": "missing",
                "loc": ("body", "name"),
                "msg": "Field required",
                "input": {},
            }
        ]
    )

    resp = await validation_exception_handler(req, exc)
    assert resp.status_code == 422

    body = resp.body.decode()
    # Envelope shape: data + meta nulled, errors populated.
    assert '"data":null' in body
    assert '"meta":null' in body
    # Code is the literal string `validation_error` — the TS client's
    # form-renderer greps for this discriminator.
    assert '"code":"validation_error"' in body
    # The `loc` tuple `("body", "name")` is rendered as the dotted
    # path `name` (the `body` source prefix is stripped per
    # `_format_loc`'s contract).
    assert '"field":"name"' in body, f"validation handler dropped the field path from loc: {body}"


@pytest.mark.asyncio
async def test_validation_handler_emits_one_error_per_pydantic_failure():
    """A request with three missing fields MUST produce three
    `errors[]` entries, not one bundled message. The form renderer
    highlights each field independently — bundling would force the
    user through three submit cycles to see all three errors."""
    from fastapi.exceptions import RequestValidationError
    from fastapi.requests import Request

    from core.envelope import validation_exception_handler

    req = Request({"type": "http", "method": "GET", "headers": []})
    exc = RequestValidationError(
        errors=[
            {"type": "missing", "loc": ("body", "name"), "msg": "Field required", "input": {}},
            {"type": "missing", "loc": ("body", "email"), "msg": "Field required", "input": {}},
            {"type": "missing", "loc": ("body", "phone"), "msg": "Field required", "input": {}},
        ]
    )

    resp = await validation_exception_handler(req, exc)
    body = resp.body.decode()
    # Three distinct field paths in the response.
    assert '"field":"name"' in body
    assert '"field":"email"' in body
    assert '"field":"phone"' in body


@pytest.mark.asyncio
async def test_validation_handler_falls_back_when_errors_empty():
    """A `RequestValidationError` with an empty `errors()` list is
    rare but legal (custom raisers). The handler MUST still emit
    one envelope error so the TS client's `errors[0]` access doesn't
    crash. Pin the defensive fallback explicitly."""
    from fastapi.exceptions import RequestValidationError
    from fastapi.requests import Request

    from core.envelope import validation_exception_handler

    req = Request({"type": "http", "method": "GET", "headers": []})
    exc = RequestValidationError(errors=[])

    resp = await validation_exception_handler(req, exc)
    body = resp.body.decode()
    assert '"code":"validation_error"' in body, (
        "Empty-errors fallback dropped the discriminator code — TS client's `errors[0].code` access would crash."
    )
    # The fallback uses `field: None` (no specific field to highlight)
    # AND a generic message.
    assert '"field":null' in body
