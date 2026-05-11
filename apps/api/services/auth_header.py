"""HTTP Authorization header parser (cycle JJ3).

Parse RFC 7235 `Authorization: <scheme> <value>` headers.
Today the webhook subscription's secret-rotation auth path,
the HMAC verification preamble, and the audit endpoint's
bearer-token gate each parse inline with subtly different
case-handling. This module is the single source of truth.

  parse_auth_header(input)  — AuthHeader or None
  KNOWN_SCHEMES             — closed scheme set
  AuthHeader                — frozen dataclass: (scheme, value)

Closed scheme set:
  * `bearer`      — RFC 6750 token-based auth.
  * `basic`       — RFC 7617 username:password (base64).
  * `hmac-sha256` — Custom; matches `services.webhook_sig` (Y2).

Pinned invariants:
  * Scheme detection case-insensitive; lowercased in output.
  * Value preserved verbatim (no decoding — caller decides
    whether to base64-decode Basic).
  * Multiple-whitespace between scheme and value tolerated
    (Python `split(None, 1)` collapses runs).
  * Empty value → None.
  * Unknown scheme → None.
  * None / empty → None.

Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass

# Closed scheme set. Adding a scheme requires touching this
# AND updating the documentation. Pin via test.
KNOWN_SCHEMES: frozenset[str] = frozenset(
    {
        "bearer",
        "basic",
        "hmac-sha256",
    }
)


@dataclass(frozen=True)
class AuthHeader:
    """Parsed Authorization header.

    `scheme` is always lowercased. `value` is verbatim from the
    header (no decoding — caller decides whether to base64-decode
    a Basic value or hex-decode an HMAC signature).
    """

    scheme: str
    value: str


def parse_auth_header(input_str: str | None) -> AuthHeader | None:
    """Parse an Authorization header value.

    Returns AuthHeader for known schemes with a non-empty value.
    Returns None for empty / malformed / unknown-scheme input.

    Examples:
      * "Bearer abc"           → AuthHeader("bearer", "abc")
      * "BEARER abc"           → AuthHeader("bearer", "abc")
      * "Basic dXNlcjpwYXNz"   → AuthHeader("basic", "dXNlcjpwYXNz")
      * "HMAC-SHA256 deadbeef" → AuthHeader("hmac-sha256", "deadbeef")
      * "Unknown abc"          → None
      * "Bearer"               → None  (no value)
      * ""                     → None
      * None                   → None
    """
    if input_str is None:
        return None
    s = input_str.strip()
    if not s:
        return None
    # Split on first whitespace run. `split(None, 1)` collapses
    # multiple whitespace and yields at most 2 parts.
    parts = s.split(None, 1)
    if len(parts) != 2:
        return None
    scheme = parts[0].lower()
    value = parts[1]
    if scheme not in KNOWN_SCHEMES:
        return None
    if not value:
        return None
    return AuthHeader(scheme=scheme, value=value)
