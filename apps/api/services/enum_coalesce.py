"""Enum coalescer (cycle RR1, Python half).

Server-side mirror of `apps/web/lib/coalesce-enum.ts`. Used by
the API endpoint validators (status filter chips), the
notification preferences seeder, and the MIME category
resolver.

  coalesce_enum(input, choices, default=None)  — canonical or default

Pure stdlib.
"""

from __future__ import annotations

from collections.abc import Iterable


def coalesce_enum(
    input_str: str | None,
    choices: Iterable[str],
    default: str | None = None,
) -> str | None:
    """Match `input_str` against `choices` and return canonical
    form (or `default` if no match).

    Algorithm:
      1. None / empty input → default.
      2. Exact (case-sensitive) match first.
      3. Case-insensitive + whitespace-stripped fallback.
      4. No match → default.
    """
    if input_str is None:
        return default
    s = input_str.strip()
    if not s:
        return default

    # Materialize so we can iterate twice.
    choices_list = list(choices)
    if not choices_list:
        return default

    # Exact match first.
    for choice in choices_list:
        if choice == s:
            return choice

    # Case-insensitive fallback.
    s_lower = s.lower()
    for choice in choices_list:
        if choice.strip().lower() == s_lower:
            return choice

    return default
