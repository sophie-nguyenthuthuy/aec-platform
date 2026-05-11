"""Security-headers middleware.

Adds the standard set of defense-in-depth response headers every modern
browser respects. Today the API serves JSON to a single first-party SPA
on a different origin — meaning iframe embedding, MIME sniffing, and
mixed-content fetches are all bug shapes, not features. Lock them down
at the response layer so a future router that forgets to opt in still
gets the protection.

Header reasoning
----------------
- `X-Content-Type-Options: nosniff` — prevents browsers from re-typing a
  JSON response as text/html (a vector for stored-XSS via an attacker-
  controlled JSON field). No downside; always on.

- `X-Frame-Options: DENY` — refuses to render inside ANY iframe. The
  dashboard isn't designed to embed; this is clickjacking defense.
  Stricter than `SAMEORIGIN` because we don't legitimately frame
  ourselves either.

- `Referrer-Policy: strict-origin-when-cross-origin` — sends the bare
  origin (no path) on cross-origin requests, full URL on same-origin.
  Standard SPA-friendly default; tighter than the browser default.

- `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`
  — for a JSON API, no resource needs to load. The `frame-ancestors`
  clause is the modern equivalent of X-Frame-Options (we send both for
  belt-and-suspenders since some scanners check one or the other).

- `Permissions-Policy` — opts out of every powerful browser API the
  JSON API has no business using. Camera/mic/geolocation/etc. None of
  them should fire from an /api/v1/... response.

- `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`
  — HSTS, 2-year max-age + preload-list-eligible. Only sent in
  production; local dev runs over HTTP and emitting HSTS there would
  brick the localhost UX after one accidental https:// load.

Why a middleware (not per-route)
--------------------------------
Headers must apply to EVERY response, including 404s, errors, and
routes added by future modules that don't know about this concern.
Middleware is the only layer that catches all of those.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Static headers — same on every response. Defined as a module-level
# tuple so the test layer can import the canonical list without
# duplicating the values (the test would otherwise drift from the
# middleware silently).
STATIC_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    # Disable every powerful API explicitly. Empty `()` means "no origin
    # may use this." Listed alphabetically so the diff stays clean when
    # we add new ones.
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
    ),
}

# HSTS only in production. Local dev runs over HTTP; emitting HSTS there
# pins the developer's browser to https://localhost which then refuses
# the dev server's HTTP responses for the next 2 years.
HSTS_HEADER_VALUE = "max-age=63072000; includeSubDomains; preload"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stamps the canonical security headers onto every response."""

    def __init__(self, app: Callable, *, production: bool) -> None:
        super().__init__(app)
        self._production = production

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for k, v in STATIC_SECURITY_HEADERS.items():
            # `setdefault` semantics — don't clobber a route that
            # legitimately set a tighter value (e.g. a future PDF
            # download route that wants `Content-Security-Policy:
            # default-src 'self'` to allow inline assets).
            response.headers.setdefault(k, v)
        if self._production:
            response.headers.setdefault("Strict-Transport-Security", HSTS_HEADER_VALUE)
        return response
