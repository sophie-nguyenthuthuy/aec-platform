"""HTTP Cache-Control directive parser (cycle NN2).

Parse RFC 7234 `Cache-Control` headers. Today the API response
emit, the dashboard meta-tag reader, and the audit CSV
download cache-suppress logic each parse inline with subtly
different directive handling. This module is the single source
of truth.

  parse_cache_control(header)  — CacheControl frozen dataclass

Pinned invariants:
  * Directive names case-insensitive.
  * Whitespace tolerated between directives and around `=`.
  * `max-age` validated as non-negative int (negative → field
    is None, not crash).
  * Unknown directives IGNORED (forward compat with future
    RFC additions — pin so a refactor that errors on unknown
    surfaces here).
  * Conflicting directives PRESERVED (`no-cache` + `immutable`
    both set — caller decides precedence).

Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CacheControl:
    """Parsed Cache-Control directives.

    Boolean fields are False when absent. Integer fields are
    None when absent OR malformed. The default constructor
    yields the "no header" state.
    """

    max_age: int | None = None
    s_maxage: int | None = None
    no_cache: bool = False
    no_store: bool = False
    public: bool = False
    private: bool = False
    must_revalidate: bool = False
    immutable: bool = False


def _parse_int_directive(value: str) -> int | None:
    """Parse a non-negative integer directive value.

    Returns None for malformed / negative values.
    """
    try:
        n = int(value)
    except ValueError:
        return None
    if n < 0:
        return None
    return n


def parse_cache_control(header: str | None) -> CacheControl:
    """Parse a Cache-Control header value.

    Empty / None → CacheControl() (all defaults).
    """
    if not header:
        return CacheControl()

    max_age: int | None = None
    s_maxage: int | None = None
    no_cache = False
    no_store = False
    public = False
    private = False
    must_revalidate = False
    immutable = False

    for raw_directive in header.split(","):
        directive = raw_directive.strip().lower()
        if not directive:
            continue

        if "=" in directive:
            name, _, value = directive.partition("=")
            name = name.strip()
            value = value.strip()
            if name == "max-age":
                max_age = _parse_int_directive(value)
            elif name == "s-maxage":
                s_maxage = _parse_int_directive(value)
            # Other name=value directives ignored (forward compat).
        else:
            if directive == "no-cache":
                no_cache = True
            elif directive == "no-store":
                no_store = True
            elif directive == "public":
                public = True
            elif directive == "private":
                private = True
            elif directive == "must-revalidate":
                must_revalidate = True
            elif directive == "immutable":
                immutable = True
            # Unknown flag directives ignored (forward compat).

    return CacheControl(
        max_age=max_age,
        s_maxage=s_maxage,
        no_cache=no_cache,
        no_store=no_store,
        public=public,
        private=private,
        must_revalidate=must_revalidate,
        immutable=immutable,
    )
