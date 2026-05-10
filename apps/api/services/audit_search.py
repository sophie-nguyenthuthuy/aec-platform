"""Audit search query parser (cycle II1).

Parses a free-text search like
`actor:user@example.com action:pulse.* since:7d some free text`
into structured filters. Today the audit search bar and the CLI
audit-export tool each tokenize inline with subtly different
prefix vocabularies. This module is the single source of truth.

  KNOWN_PREFIXES         — closed prefix vocabulary
  SearchQuery            — frozen dataclass with parsed filters
  parse_search_query(s)  — main entry point

Composes with prior cycles:
  * Z2 (`audit_action_meta.AUDIT_MODULES`) — `module:` values
    must be in the closed module set.
  * GG3 (`email.parse_email`) — `actor:` values must be valid
    emails (invalid → free-text fallback).
  * Z3 (`time_window.parse_since_days` semantics) — `since:Nd`
    relative shorthand alongside ISO dates.

Pinned invariants:
  * Empty / None input → empty SearchQuery (all filters None/empty).
  * Unknown prefixes treated as free-text (NOT errors).
  * Invalid `actor:` values fall back to free-text (defensive
    against a hand-edited search URL with a typo).
  * `since:` accepts ISO date OR `Nd` shorthand (`7d` → 7 days ago).
  * Quoted multi-word values via `prefix:"value with spaces"`.
  * Bare quoted text (without a prefix) is NOT supported — quotes
    inside free text become literal token boundaries.

Pure stdlib + Z2 + GG3 + Z3 (composition).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from services.audit_action_meta import AUDIT_MODULES
from services.email import parse_email

# Closed prefix vocabulary. Adding a prefix requires updating
# this set + the parser switch + the test catalog. Pin so a
# sneaky add doesn't slip past three-way review.
KNOWN_PREFIXES: frozenset[str] = frozenset(
    {
        "actor",
        "action",
        "module",
        "since",
        "until",
    }
)


@dataclass(frozen=True)
class SearchQuery:
    """Parsed search query with structured filters.

    All fields are required. Empty tuples / None for absent
    filters. The caller composes these into a SQL `WHERE`
    clause (or pgsearch query) — this module's job is purely
    structural.
    """

    actors: tuple[str, ...] = field(default_factory=tuple)
    actions: tuple[str, ...] = field(default_factory=tuple)
    modules: tuple[str, ...] = field(default_factory=tuple)
    since: date | None = None
    until: date | None = None
    free_text: tuple[str, ...] = field(default_factory=tuple)


# Token regex:
#   Group 1: prefix:"quoted value with spaces"
#   Group 2: prefix:value (no spaces)
#   Group 3: bareword
_TOKEN_RE = re.compile(r'(\w+:"[^"]*")|(\S+:\S+)|(\S+)')


_REL_DAYS_RE = re.compile(r"^(\d+)d$")


def _tokenize(input_str: str) -> list[str]:
    """Tokenize a search string. Handles `prefix:"quoted"` syntax."""
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(input_str):
        quoted = match.group(1)
        prefixed = match.group(2)
        bareword = match.group(3)
        if quoted is not None:
            # Strip the quotes from the value part.
            prefix, _, rest = quoted.partition(":")
            # rest is `"value"`, strip outer quotes.
            value = rest[1:-1] if rest.startswith('"') and rest.endswith('"') else rest
            tokens.append(f"{prefix}:{value}")
        elif prefixed is not None:
            tokens.append(prefixed)
        elif bareword is not None:
            tokens.append(bareword)
    return tokens


def _parse_relative_or_iso(value: str, today: date) -> date | None:
    """Parse a date value: ISO `YYYY-MM-DD` or `Nd` shorthand
    (relative days ago). Returns None for malformed input."""
    rel_match = _REL_DAYS_RE.match(value)
    if rel_match:
        n = int(rel_match.group(1))
        if 1 <= n <= 365:
            return today - timedelta(days=n)
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_search_query(
    input_str: str | None,
    today: date | None = None,
) -> SearchQuery:
    """Parse a free-text search into structured filters.

    `today` defaults to `date.today()` and is exposed for
    deterministic testing of `since:Nd` relative shorthand.

    Empty / None input returns an empty SearchQuery (no filters,
    no free text).
    """
    if not input_str:
        return SearchQuery()

    today = today or date.today()
    tokens = _tokenize(input_str)

    actors: list[str] = []
    actions: list[str] = []
    modules: list[str] = []
    since: date | None = None
    until: date | None = None
    free_text: list[str] = []

    for token in tokens:
        if ":" not in token:
            free_text.append(token)
            continue
        prefix, _, value = token.partition(":")
        prefix_lc = prefix.lower()
        if prefix_lc not in KNOWN_PREFIXES or not value:
            # Unknown prefix or empty value → free text fallback.
            free_text.append(token)
            continue

        if prefix_lc == "actor":
            canonical = parse_email(value)
            if canonical is not None:
                actors.append(canonical)
            else:
                free_text.append(token)
        elif prefix_lc == "action":
            actions.append(value)
        elif prefix_lc == "module":
            if value in AUDIT_MODULES:
                modules.append(value)
            else:
                free_text.append(token)
        elif prefix_lc == "since":
            parsed = _parse_relative_or_iso(value, today)
            if parsed is not None:
                # If multiple `since:` tokens, take the EARLIEST
                # (broader window — more inclusive).
                if since is None or parsed < since:
                    since = parsed
            else:
                free_text.append(token)
        elif prefix_lc == "until":
            parsed = _parse_relative_or_iso(value, today)
            if parsed is not None:
                # If multiple `until:` tokens, take the LATEST
                # (broader window).
                if until is None or parsed > until:
                    until = parsed
            else:
                free_text.append(token)

    return SearchQuery(
        actors=tuple(actors),
        actions=tuple(actions),
        modules=tuple(modules),
        since=since,
        until=until,
        free_text=tuple(free_text),
    )
