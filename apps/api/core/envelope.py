from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

T = TypeVar("T")


class Meta(BaseModel):
    page: int | None = None
    per_page: int | None = None
    total: int | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None
    # Optional in-app URL the client can deep-link the user to for
    # context on this error. Today only the codeguard cap-check 429
    # populates it (→ /codeguard/quota), but the field is generic on
    # purpose: a future "subscription expired" 402 could point at
    # /settings/billing, "RLS denied" 403 at /settings/members, etc.
    # Frontend treats null as "no CTA" and renders a plain toast.
    details_url: str | None = None


class Envelope(BaseModel, Generic[T]):
    data: T | None = None
    meta: Meta | None = None
    errors: list[ErrorDetail] | None = None


def ok(data: Any, meta: Meta | None = None) -> dict[str, Any]:
    return {"data": data, "meta": meta.model_dump() if meta else None, "errors": None}


def paginated(items: list[Any], page: int, per_page: int, total: int) -> dict[str, Any]:
    return ok(items, Meta(page=page, per_page=per_page, total=total))


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # `exc.headers` is set by callers that want to surface response headers
    # like `Retry-After` on a 429 or `WWW-Authenticate` on a 401. Forward
    # them verbatim — not doing so silently breaks rate-limit clients that
    # back off based on the header.

    # Two `detail` shapes are accepted:
    #   * str               → traditional FastAPI form, becomes `message`.
    #   * {"message": ...,  → structured form, allows raisers to surface
    #      "details_url":      a deep-link CTA without stuffing it into
    #      ...}                the message text. Today only the codeguard
    #                          cap-check 429 uses the dict form.
    # We don't add a third top-level shape here — adding more keys means
    # fanning out parser branches in every existing 429/401/403 caller.
    if isinstance(exc.detail, dict):
        message = str(exc.detail.get("message", ""))
        details_url = exc.detail.get("details_url")
    else:
        message = str(exc.detail)
        details_url = None

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "data": None,
            "meta": None,
            "errors": [
                {
                    "code": str(exc.status_code),
                    "message": message,
                    "field": None,
                    "details_url": details_url,
                }
            ],
        },
        headers=exc.headers,
    )


def _format_loc(loc: tuple[Any, ...]) -> str | None:
    """Convert FastAPI's `loc` tuple (`("body", "items", 0, "name")`)
    into a dotted path the TS client can use to highlight the offending
    form field (`"items.0.name"`).

    The first element is the source — `body` / `query` / `path` /
    `header` / `cookie`. We strip it: the TS form-error renderer cares
    about the field path inside the body, not whether it came from the
    body or the query string. If the only `loc` element IS the source
    (e.g. `("body",)` for a missing-body case), we keep the source so
    the field has *something* — a null `field` would deny the renderer
    a target.
    """
    if not loc:
        return None
    if len(loc) == 1:
        return str(loc[0])
    rest = loc[1:]
    return ".".join(str(p) for p in rest)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handler for `RequestValidationError` — Pydantic-driven 422s
    from FastAPI's request parsing.

    Without this, FastAPI emits its default `{"detail": [...]}` shape,
    which the TS client's envelope unwrapper can't parse — every form
    submission with a validation error lands in the "unknown error"
    bucket, no field-level highlighting. This handler maps each
    `errors()` entry into the standard envelope shape, preserving the
    `loc` path as `field` so the form renderer can highlight which
    input went wrong.

    Each Pydantic error becomes ONE entry in `errors[]`. A request
    with three missing fields produces three entries — the TS client
    can render all three highlighted at once instead of forcing the
    user through one-at-a-time submit cycles.
    """
    errors_out: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        msg = err.get("msg") or "Invalid value"
        errors_out.append(
            {
                "code": "validation_error",
                "message": str(msg),
                "field": _format_loc(tuple(loc)),
                "details_url": None,
            }
        )
    if not errors_out:
        # Defensive: a RequestValidationError with no `errors()` is
        # rare but not impossible (custom raisers). Surface a generic
        # entry rather than an empty array so the TS client's
        # `errors[0]` access doesn't crash.
        errors_out.append(
            {
                "code": "validation_error",
                "message": "Validation failed",
                "field": None,
                "details_url": None,
            }
        )
    return JSONResponse(
        status_code=422,
        content={"data": None, "meta": None, "errors": errors_out},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "data": None,
            "meta": None,
            "errors": [
                {
                    "code": "internal_error",
                    "message": "An unexpected error occurred",
                    "field": None,
                    "details_url": None,
                }
            ],
        },
    )
