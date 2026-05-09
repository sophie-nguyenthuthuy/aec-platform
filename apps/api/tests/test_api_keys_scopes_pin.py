"""Pin `services.api_keys.SCOPES` (the closed-set scope vocabulary).

Why this exists: every api-key carries a `scopes` array; every
auth-gated endpoint reads from it via `require_scope("foo:bar")`.
A typo in `SCOPES` has two failure modes:

  1. **Silent permission loss**: `SCOPES` drops `defects:read` →
     every key with that scope still has it in `api_keys.scopes` but
     `mint_key` rejects new ones for typing the now-unknown value.
     Existing keys keep working until reissued.

  2. **Silent privilege expansion**: `SCOPES` adds a typo'd entry
     (`projects:wrtie` instead of `projects:write`) → mint_key
     accepts the typo, but no endpoint check matches it →
     a key that requested write access silently gets read-only
     behaviour without any error.

Both failure modes are silent at the per-request level. Pinning
the absolute set turns either into a loud test failure.

The `*` wildcard scope is included intentionally — it's the
"this api-key can do anything" superuser bucket, used for
ops-internal keys. Removing `*` would silently break the few keys
that legitimately need it.

If you intentionally change SCOPES, update `EXPECTED` below in the
same PR + audit every endpoint that calls `require_scope` to make
sure the change doesn't grant or remove access unintentionally.

Note on `KEY_MODES`: the sister constant for sandbox/test-mode
gating has been reverted multiple times across recent batches and
is currently absent from the source. A pin for it lives in this
file's docstring as a TODO and should be added once the sandbox
work re-lands.
"""

from __future__ import annotations

from services.api_keys import SCOPES

# Source of truth, pinned 2026-05-04. Two-segment `domain:action`
# form everywhere; the wildcard is the only single-token entry.
EXPECTED: frozenset[str] = frozenset(
    {
        # ---- Wildcard (ops-internal superuser keys only)
        "*",
        # ---- Per-domain scopes. Two `<domain>:<action>` tokens per
        # entry; `read` and `write` are the only actions today,
        # except for `webhooks:admin` which is a single elevated
        # bucket.
        "audit:read",
        "change_orders:read",
        "change_orders:write",
        "defects:read",
        "defects:write",
        "estimates:read",
        "estimates:write",
        "projects:read",
        "projects:write",
        "rfis:read",
        "rfis:write",
        "search:read",
        "suppliers:read",
        "suppliers:write",
        "webhooks:admin",
    }
)


def test_scopes_matches_expected_set_exactly():
    """Hard equality. Two-way diff in the failure message names
    exactly which scopes are off — drop, addition, or rename.
    """
    missing = EXPECTED - SCOPES
    unexpected = SCOPES - EXPECTED
    assert not missing, (
        f"SCOPES lost entries vs the pin: {sorted(missing)}. "
        "If this is intentional, remove from EXPECTED in the same PR + "
        "verify no endpoint still calls `require_scope` for the dropped "
        "value (silent 500 if it does)."
    )
    assert not unexpected, (
        f"SCOPES gained entries the pin doesn't know about: {sorted(unexpected)}. "
        "If this is intentional, add to EXPECTED in the same PR + verify the "
        "new scope is actually checked by some endpoint (otherwise you've "
        "added a permission users can request but no path enforces — silent "
        "privilege expansion)."
    )


def test_scopes_is_a_frozenset():
    """`SCOPES` must be a `frozenset` (or compatible Set with `in`
    semantics) — `mint_key` does `if s not in SCOPES` for each
    requested scope. A regression to a list/tuple would still pass
    `in` but be O(n) per check; a regression to a dict would pass
    `in` on keys but break the equality assertion above.
    """
    # `frozenset` is the canonical choice; `set` is also acceptable
    # at runtime but the immutability is documented + stable.
    assert isinstance(SCOPES, frozenset | set), f"SCOPES should be a (froz|)set; got {type(SCOPES).__name__}"


def test_scopes_have_no_whitespace_or_capitals():
    """Convention: scopes are lowercase, snake-case-ish (no spaces,
    no capitals). The DB stores them verbatim; case-sensitive
    matching means a typo'd `Projects:Read` is a different bucket
    from `projects:read`. Pin the convention.
    """
    for scope in SCOPES:
        assert isinstance(scope, str), f"non-string in SCOPES: {scope!r}"
        assert scope == scope.lower(), (
            f"SCOPES entry {scope!r} should be lowercase. The DB stores it verbatim and matching is case-sensitive."
        )
        assert " " not in scope, f"SCOPES entry {scope!r} contains whitespace"
        # Reject `XX...XX` mangling that's appeared on sibling
        # closed sets during upstream-revert events.
        assert not scope.startswith("XX"), f"SCOPES entry {scope!r} looks mangled (`XX...` prefix)."


def test_scopes_follow_domain_action_form_or_wildcard():
    """Every scope is either `*` (wildcard) or two-token
    `<domain>:<action>`. A three-token entry (e.g. `foo:bar:baz`)
    would silently break `mint_key`'s scope-validation logic, which
    treats each token as a verbatim string. Pin the shape so a
    refactor to e.g. `domain:resource:action` has to update this
    test too.
    """
    for scope in SCOPES:
        if scope == "*":
            continue
        parts = scope.split(":")
        assert len(parts) == 2, (
            f"SCOPES entry {scope!r} should be `<domain>:<action>` (two parts) "
            f"or `*` (wildcard); got {len(parts)} parts."
        )
        domain, action = parts
        assert domain, f"SCOPES entry {scope!r} has empty domain"
        assert action, f"SCOPES entry {scope!r} has empty action"


def test_scopes_includes_wildcard_for_internal_ops_keys():
    """The `*` wildcard is the canonical "this is an ops-internal
    key" marker. Removing it would silently strip access from the
    handful of internal keys that use it for cross-tenant
    automation. Pin its presence explicitly so a "let's enumerate
    all scopes" refactor doesn't drop it accidentally.
    """
    assert "*" in SCOPES, (
        "SCOPES no longer includes the `*` wildcard. Internal ops keys rely "
        "on it for cross-tenant automation; a removal silently breaks them."
    )
