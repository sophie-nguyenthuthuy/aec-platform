"""HTTP redirect target URL canonicalizer (cycle SS1).

Validate and canonicalize redirect URLs to defend against
open-redirect attacks. Today the post-login `?next=` redirect
handler, the OAuth callback URL builder, and the audit row
"resource link" handler each validate inline with subtly
different scheme rules. This module is the single source of
truth.

  canonical_redirect(url, allowed_hosts)  — canonical or None
  is_safe_redirect(url, allowed_hosts)    — bool
  DANGEROUS_SCHEMES                       — closed reject set
  ALLOWED_SCHEMES                         — closed accept set

Pinned defenses:
  * Scheme-relative URLs (`//evil.com/path`) REJECTED — common
    open-redirect bypass technique.
  * `data:` / `javascript:` / `file:` / `about:` / `vbscript:`
    REJECTED (XSS / exfiltration vectors).
  * URLs with embedded credentials (`user:pass@host`) REJECTED.
  * Absolute URLs validated against `allowed_hosts` set.
  * Relative URLs MUST start with `/` (path-absolute) — bare
    `dashboard` rejected (path-relative is ambiguous).
  * Host comparison case-insensitive, trailing dot tolerated.

Pure stdlib.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

# Schemes EXPLICITLY rejected for redirect targets. Pin so a
# refactor that adds e.g. `mailto:` (which can leak) surfaces
# in review.
DANGEROUS_SCHEMES: frozenset[str] = frozenset(
    {
        "data",
        "javascript",
        "file",
        "about",
        "vbscript",
    }
)


# Schemes accepted for absolute-URL redirects. HTTP and HTTPS
# only — pin so a refactor that adds e.g. `ftp:` surfaces.
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def canonical_redirect(
    url: str | None,
    allowed_hosts: set[str],
) -> str | None:
    """Validate and canonicalize a redirect URL.

    Returns the canonical URL string, or None if rejected.

    Accepts:
      * Path-absolute relative URLs (`/dashboard`, `/audit?x=1`).
      * Absolute URLs (`https://allowed.com/path`) where host
        is in `allowed_hosts`.

    Rejects:
      * Scheme-relative URLs (`//evil.com/...`).
      * Dangerous schemes (`data:`, `javascript:`, etc).
      * URLs with embedded credentials.
      * Hosts not in `allowed_hosts`.
      * Path-relative URLs (`dashboard` without leading `/`).
    """
    if not url:
        return None
    s = url.strip()
    if not s:
        return None

    # Reject scheme-relative URLs FIRST (before urlparse decides
    # what to do with `//evil.com`).
    if s.startswith("//"):
        return None

    parsed = urlparse(s)

    # Relative URL: no scheme, no netloc.
    if not parsed.scheme and not parsed.netloc:
        if not s.startswith("/"):
            return None
        return s

    # Absolute URL: validate scheme + host.
    scheme = parsed.scheme.lower()
    if scheme in DANGEROUS_SCHEMES:
        return None
    if scheme not in ALLOWED_SCHEMES:
        return None

    # Reject embedded credentials.
    if parsed.username or parsed.password:
        return None

    host = parsed.hostname
    if host is None:
        return None

    # Normalize host: lowercase + strip trailing dot.
    host_lower = host.lower().rstrip(".")

    # Normalize allowed_hosts the same way.
    normalized_allowed = {h.lower().rstrip(".") for h in allowed_hosts if h}

    if host_lower not in normalized_allowed:
        return None

    # Canonical form: rebuild via urlunparse to normalize.
    return urlunparse(
        (
            scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def is_safe_redirect(
    url: str | None,
    allowed_hosts: set[str],
) -> bool:
    """True iff `canonical_redirect(url, allowed_hosts)` returns
    a non-None canonical."""
    return canonical_redirect(url, allowed_hosts) is not None
