from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi import HTTPException
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


class Envelope(BaseModel, Generic[T]):
    data: T | None = None
    meta: Meta | None = None
    errors: list[ErrorDetail] | None = None


def ok(data: Any, meta: Meta | None = None) -> dict[str, Any]:
    return {"data": data, "meta": meta.model_dump() if meta else None, "errors": None}


def paginated(items: list[Any], page: int, per_page: int, total: int) -> dict[str, Any]:
    return ok(items, Meta(page=page, per_page=per_page, total=total))


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "data": None,
            "meta": None,
            "errors": [{"code": str(exc.status_code), "message": str(exc.detail), "field": None}],
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "data": None,
            "meta": None,
            "errors": [{"code": "internal_error", "message": "An unexpected error occurred", "field": None}],
        },
    )
