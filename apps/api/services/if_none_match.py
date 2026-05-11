"""HTTP If-None-Match parser (cycle VV2).

Parse RFC 7232 `If-None-Match` headers (used for safe-method
conditional requests / etag-based 304 caching).

Structurally identical to LL2's `If-Match` parser — same syntax,
same wildcard rules. The SEMANTIC difference is in how callers
USE the result:

  * `If-Match` (LL2) — for unsafe methods (PUT/DELETE):
    request requires AT LEAST ONE matching etag, else 412.

  * `If-None-Match` (this module) — for safe methods (GET):
    request requires NO matching etag, else 304 Not Modified.

This module reuses LL2's parser directly (same parsing logic)
and adds the `should_return_304` helper that encodes the GET
304-decision logic.

  parse_if_none_match(header)              — IfMatchList or None
  should_return_304(if_none_match, etag)   — bool

Composes with LL2's `IfMatchList`, `ETag`, and `parse_if_match`.

Pinned invariants:
  * Parser delegates to LL2 — same behaviour.
  * `should_return_304(None, anything)` → False (no header,
    no condition).
  * Wildcard `*` matches any non-None etag → True (304).
  * Etag list match is by VALUE (weak/strong both match for GET).
  * Missing resource (current_etag=None) with wildcard → False
    (resource doesn't exist, GET should 404 elsewhere — 304
    means "you have it, it's still current").

Pure stdlib + LL2.
"""

from __future__ import annotations

from services.etag import ETag, IfMatchList, parse_if_match


def parse_if_none_match(header: str | None) -> IfMatchList | None:
    """Parse an If-None-Match header value.

    Reuses LL2's `parse_if_match` since the syntax is identical.
    The semantic difference (104 caching vs concurrency) is in
    how the caller uses the result, not in the parsing.

    Returns:
      * `IfMatchList((), False)` for None / empty (no precondition).
      * `IfMatchList((), True)` for `*` wildcard.
      * `IfMatchList(etags, False)` for valid list.
      * `None` for malformed.
    """
    return parse_if_match(header)


def should_return_304(
    if_none_match: IfMatchList | None,
    current_etag: ETag | None,
) -> bool:
    """True iff a GET request should return 304 Not Modified
    given the parsed `If-None-Match` and the resource's
    current ETag.

    RFC 7232 §3.2 semantics:
      * Header None / not parseable → False (no precondition).
      * Wildcard `*` → True iff resource exists (current_etag
        is not None).
      * Etag list → True iff ANY listed etag matches by value.
        Weak/strong distinction is IGNORED for GET (matches
        either way per RFC 7232 §3.2 weak comparison).
      * Empty etag list (no precondition) → False.

    Returning True means the caller should respond with HTTP
    304 (NOT modified) and skip the body. False means proceed
    with normal 200 response.
    """
    if if_none_match is None:
        return False

    if if_none_match.is_wildcard:
        # Wildcard matches any existing resource.
        return current_etag is not None

    if not if_none_match.etags:
        # Empty list = no precondition.
        return False

    if current_etag is None:
        # Resource doesn't exist — can't match.
        return False

    return any(etag.value == current_etag.value for etag in if_none_match.etags)
