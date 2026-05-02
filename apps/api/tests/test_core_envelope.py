"""Unit tests for `core.envelope.http_exception_handler`.

The envelope handler accepts two shapes for `HTTPException.detail`:

  * `str`               — traditional FastAPI form. Becomes `message`,
                          `details_url` is null.
  * `{"message": ...,   — structured form. Lets raisers attach a
     "details_url": ...}    deep-link CTA without stuffing it into
                            the message text. The codeguard cap-check
                            429 uses this to point at /codeguard/quota.

Pinning both paths here so a refactor of the handler can't silently
break the dict path (the only contract an unsuspecting maintainer
might think they can simplify away).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from core.envelope import http_exception_handler


@pytest.mark.asyncio
async def test_string_detail_becomes_message_with_null_details_url():
    """Traditional FastAPI form. The string detail surfaces as the
    `message`, and `details_url` is null — proving the new field is
    additive and existing callers that raise with a string don't
    suddenly need to opt in."""
    exc = HTTPException(status_code=403, detail="Forbidden")
    res = await http_exception_handler(MagicMock(), exc)
    body = _decode(res)
    assert body["errors"][0] == {
        "code": "403",
        "message": "Forbidden",
        "field": None,
        "details_url": None,
    }


@pytest.mark.asyncio
async def test_dict_detail_unpacks_message_and_details_url():
    """Structured form. The dict's `message` key becomes the response
    `message`, and `details_url` flows through verbatim. Pin the keys
    by name so a refactor that renames either side breaks visibly."""
    exc = HTTPException(
        status_code=429,
        detail={
            "message": "Monthly input-token quota exceeded",
            "details_url": "/codeguard/quota",
        },
    )
    res = await http_exception_handler(MagicMock(), exc)
    body = _decode(res)
    assert body["errors"][0]["code"] == "429"
    assert body["errors"][0]["message"] == "Monthly input-token quota exceeded"
    assert body["errors"][0]["details_url"] == "/codeguard/quota"


@pytest.mark.asyncio
async def test_dict_detail_without_details_url_is_safe():
    """A dict detail with only `message` (no `details_url`) must not
    crash the handler — the URL key is optional. Pin the safe-default
    so a future raiser that uses the dict form for, say, a 401 with
    just a message can do so without remembering to set the URL."""
    exc = HTTPException(status_code=400, detail={"message": "Bad input"})
    res = await http_exception_handler(MagicMock(), exc)
    body = _decode(res)
    assert body["errors"][0]["message"] == "Bad input"
    assert body["errors"][0]["details_url"] is None


@pytest.mark.asyncio
async def test_headers_pass_through_unchanged():
    """`exc.headers` must reach the response — `Retry-After` on 429s
    and `WWW-Authenticate` on 401s rely on this. The dict-detail
    refactor mustn't break header forwarding (regression check)."""
    exc = HTTPException(
        status_code=429,
        detail={"message": "Too fast", "details_url": "/codeguard/quota"},
        headers={"Retry-After": "60"},
    )
    res = await http_exception_handler(MagicMock(), exc)
    assert res.headers.get("Retry-After") == "60"


def _decode(response) -> dict:
    """JSONResponse.body is bytes; decode for assertion."""
    import json

    return json.loads(response.body)
