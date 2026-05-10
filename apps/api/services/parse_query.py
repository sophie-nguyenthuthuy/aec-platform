"""HTTP query string parser (cycle RR2).

Inverse of PP3's `build_canonical_query`. Today the audit
endpoint's filter parser, the dashboard's URL state hydrator,
and the webhook subscription's URL-encoded form decoder each
parse inline with subtly different repeated-key handling. This
module is the single source of truth.

  parse_query(query_string)  — dict[str, str | list[str]]

Composes with PP3 — round-trip-stable for canonically-built
strings: `parse_query(build_canonical_query(d))` reconstructs `d`
modulo None values (which PP3 drops on emit).

Pinned invariants:
  * Repeated keys collected into list (preserving order).
  * Single-occurrence key yields a string (NOT a single-element
    list).
  * Empty value preserved as `""` (`a=` → `{"a": ""}`).
  * No `=` in pair → empty value (`a` → `{"a": ""}`).
  * Empty / None input → `{}`.
  * Leading `?` stripped if present.
  * Percent-decoded via stdlib unquote.

Pure stdlib.
"""

from __future__ import annotations

from urllib.parse import unquote


def parse_query(
    query_string: str | None,
) -> dict[str, str | list[str]]:
    """Parse a URL query string into a dict.

    Returns:
      * `{}` for None / empty input.
      * `{"key": "value"}` for single-occurrence keys.
      * `{"key": [v1, v2]}` for repeated keys.
    """
    if not query_string:
        return {}
    s = query_string.strip()
    if not s:
        return {}
    # Strip leading `?` if present (defensive — caller may pass
    # the URL fragment).
    if s.startswith("?"):
        s = s[1:]
    if not s:
        return {}

    result: dict[str, str | list[str]] = {}

    for pair in s.split("&"):
        if not pair:
            continue
        if "=" in pair:
            key, _, value = pair.partition("=")
        else:
            key = pair
            value = ""
        decoded_key = unquote(key)
        decoded_value = unquote(value)
        if decoded_key in result:
            existing = result[decoded_key]
            if isinstance(existing, list):
                existing.append(decoded_value)
            else:
                result[decoded_key] = [existing, decoded_value]
        else:
            result[decoded_key] = decoded_value

    return result
