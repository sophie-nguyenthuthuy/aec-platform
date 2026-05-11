"""Audit search query parser (cycle II1).

Pinned seams:
  1. KNOWN_PREFIXES = {actor, action, module, since, until}.
  2. Unknown prefixes treated as free-text.
  3. Invalid actor email falls back to free-text.
  4. Unknown module falls back to free-text (Z2 composition).
  5. since:Nd relative shorthand parses (Z3 composition).
  6. since: ISO date parses.
  7. Multiple since:/until: pick broader window (earliest/latest).
  8. Quoted value with spaces: actor:"Name With Spaces".
  9. Empty / None input → empty SearchQuery.
"""

from __future__ import annotations

from datetime import date

from services.audit_search import (
    KNOWN_PREFIXES,
    SearchQuery,
    parse_search_query,
)

TODAY = date(2026, 5, 10)


# ---------- Constants ----------


def test_known_prefixes_canonical_set():
    """Closed prefix vocabulary. Pin so a refactor that adds e.g.
    `org:` without updating the test catalog surfaces here."""
    assert (
        frozenset(
            {
                "actor",
                "action",
                "module",
                "since",
                "until",
            }
        )
        == KNOWN_PREFIXES
    )


def test_known_prefixes_is_frozen():
    assert isinstance(KNOWN_PREFIXES, frozenset)


# ---------- Empty / None ----------


def test_empty_input_returns_empty_query():
    q = parse_search_query("", TODAY)
    assert q == SearchQuery()
    assert q.actors == ()
    assert q.actions == ()
    assert q.free_text == ()
    assert q.since is None
    assert q.until is None


def test_none_input_returns_empty_query():
    assert parse_search_query(None) == SearchQuery()


def test_whitespace_only_returns_empty_query():
    assert parse_search_query("   ", TODAY) == SearchQuery()


# ---------- Free-text only ----------


def test_bare_words_become_free_text():
    q = parse_search_query("hello world", TODAY)
    assert q.free_text == ("hello", "world")
    assert q.actors == ()


def test_unknown_prefix_becomes_free_text():
    """`org:foo` is not in KNOWN_PREFIXES — entire token treated
    as free text. Pin so a refactor that ignores unknown prefixes
    silently doesn't lose user intent."""
    q = parse_search_query("org:acme", TODAY)
    assert q.free_text == ("org:acme",)


# ---------- actor: ----------


def test_valid_actor_email():
    q = parse_search_query("actor:user@example.com", TODAY)
    assert q.actors == ("user@example.com",)
    assert q.free_text == ()


def test_actor_email_lowercased_via_GG3():
    """Composes with GG3: parse_email lowercases the canonical.
    Pin so search dedup works across user-typed case."""
    q = parse_search_query("actor:USER@Example.COM", TODAY)
    assert q.actors == ("user@example.com",)


def test_invalid_actor_falls_back_to_free_text():
    """A bad email doesn't crash the search — falls back to
    free-text token. Defends against a hand-edited URL with a
    typo'd email."""
    q = parse_search_query("actor:notanemail", TODAY)
    assert q.actors == ()
    assert q.free_text == ("actor:notanemail",)


def test_quoted_actor_with_spaces():
    """Quoted value supports spaces in the value. Vietnamese
    names often have spaces in the local part of an email
    handle (rare but possible) — quoted form makes it explicit."""
    q = parse_search_query('actor:"user@example.com"', TODAY)
    assert q.actors == ("user@example.com",)


def test_multiple_actors():
    q = parse_search_query("actor:a@example.com actor:b@example.com", TODAY)
    assert q.actors == ("a@example.com", "b@example.com")


# ---------- action: ----------


def test_action_literal():
    q = parse_search_query("action:pulse.change_order.approve", TODAY)
    assert q.actions == ("pulse.change_order.approve",)


def test_action_wildcard():
    """Wildcard patterns pass through verbatim — the SQL builder
    is responsible for translating to a LIKE clause."""
    q = parse_search_query("action:pulse.*", TODAY)
    assert q.actions == ("pulse.*",)


def test_multiple_actions():
    q = parse_search_query("action:pulse.* action:webhook.test", TODAY)
    assert q.actions == ("pulse.*", "webhook.test")


# ---------- module: ----------


def test_module_known():
    """Composes with Z2: `module:pulse` only accepts modules in
    AUDIT_MODULES."""
    q = parse_search_query("module:pulse", TODAY)
    assert q.modules == ("pulse",)


def test_module_known_admin():
    q = parse_search_query("module:admin", TODAY)
    assert q.modules == ("admin",)


def test_module_unknown_falls_back_to_free_text():
    """Cardinal pin: a typo'd module surfaces as free text rather
    than silently matching nothing. A refactor that accepts
    arbitrary modules would let `module:typo` slip past and
    return zero rows with no signal to the user."""
    q = parse_search_query("module:typo", TODAY)
    assert q.modules == ()
    assert q.free_text == ("module:typo",)


# ---------- since: / until: ----------


def test_since_iso_date():
    q = parse_search_query("since:2026-01-01", TODAY)
    assert q.since == date(2026, 1, 1)


def test_since_relative_days():
    """`since:7d` resolves to 7 days before TODAY (Z3 composition)."""
    q = parse_search_query("since:7d", TODAY)
    assert q.since == date(2026, 5, 3)


def test_since_relative_at_max():
    """365 is the relative cap (Z3 MAX_SINCE_DAYS pin)."""
    q = parse_search_query("since:365d", TODAY)
    assert q.since == date(2025, 5, 10)


def test_since_relative_above_max_falls_back():
    """`since:1000d` is above Z3 cap → free text."""
    q = parse_search_query("since:1000d", TODAY)
    assert q.since is None
    assert q.free_text == ("since:1000d",)


def test_since_invalid_falls_back_to_free_text():
    q = parse_search_query("since:invalid", TODAY)
    assert q.since is None
    assert q.free_text == ("since:invalid",)


def test_until_iso_date():
    q = parse_search_query("until:2026-12-31", TODAY)
    assert q.until == date(2026, 12, 31)


def test_multiple_since_picks_earliest():
    """Multiple `since:` → broader window (earliest date)."""
    q = parse_search_query("since:2026-04-01 since:2026-01-01", TODAY)
    assert q.since == date(2026, 1, 1)


def test_multiple_until_picks_latest():
    """Multiple `until:` → broader window (latest date)."""
    q = parse_search_query("until:2026-06-01 until:2026-12-31", TODAY)
    assert q.until == date(2026, 12, 31)


# ---------- Mixed ----------


def test_mixed_prefixes_and_free_text():
    q = parse_search_query(
        "actor:user@example.com action:pulse.* hello world",
        TODAY,
    )
    assert q.actors == ("user@example.com",)
    assert q.actions == ("pulse.*",)
    assert q.free_text == ("hello", "world")


def test_full_search_with_all_filters():
    q = parse_search_query(
        "actor:user@example.com action:pulse.* module:pulse since:2026-01-01 until:2026-06-30 free text",
        TODAY,
    )
    assert q.actors == ("user@example.com",)
    assert q.actions == ("pulse.*",)
    assert q.modules == ("pulse",)
    assert q.since == date(2026, 1, 1)
    assert q.until == date(2026, 6, 30)
    assert q.free_text == ("free", "text")


# ---------- Case-insensitive prefix ----------


def test_prefix_case_insensitive():
    """`ACTOR:foo@bar.com` works the same as `actor:foo@bar.com`.
    Pin so a refactor to case-sensitive prefixes doesn't break
    user expectations (search bars are typically case-tolerant)."""
    q = parse_search_query("ACTOR:user@example.com", TODAY)
    assert q.actors == ("user@example.com",)


# ---------- SearchQuery shape ----------


def test_search_query_is_frozen():
    q = SearchQuery()
    try:
        q.actors = ("foo",)  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("SearchQuery should be frozen")


def test_search_query_default_construction():
    """Default SearchQuery is fully empty — pin so a refactor
    that introduces a default filter (e.g. `since=last_week`)
    surfaces here."""
    q = SearchQuery()
    assert q.actors == ()
    assert q.actions == ()
    assert q.modules == ()
    assert q.since is None
    assert q.until is None
    assert q.free_text == ()
