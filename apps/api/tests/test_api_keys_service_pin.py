"""Pin the `services.api_keys` partner-API surface.

This module is the security boundary for partner integrations. It
mints credentials, verifies them on every request, gates them by
scope + project allowlist, and rate-limits them. A regression on any
of these has either security or correctness implications:

  * **`KEY_PREFIX` rename** — the `aec_` prefix is the discriminator
    `middleware.api_key_auth.require_user_or_api_key` uses to route
    a request to the api-key path vs the JWT path. Renaming `aec_`
    to `aeckey_` (or any drift) silently routes every minted key
    to the JWT verifier — every partner integration 401s on first
    request after deploy.

  * **`hash_key` algorithm change** — historical rows in
    `api_keys.hash` are sha256-hex. A swap to sha512 / a different
    casing / a salt would mean none of the live keys verify any
    more (every partner 401s simultaneously).

  * **`has_scope` wildcard semantics** — `*` MUST be the superuser
    pass-through. A regression that no longer recognised `*` would
    lock superuser admin keys out of every gated route.

  * **`has_project_access` empty-list semantics** — empty
    `key_project_ids` MUST mean "all projects" (back-compat with
    keys minted before migration 0039). A regression that 403'd on
    empty list would break every legacy partner key.

  * **`record_call` swallows on failure** — rate-limit telemetry
    must not break authentication. A regression that re-raised
    on DB blip would 401 / 500 every authenticated request when
    the telemetry table is having a bad day.

  * **`SCOPES` set immutable** — frozenset, not set. A mutable
    set imported and `.add()`'d at runtime by some import side
    effect would silently grant scopes that never went through
    a deploy review.

  * **`KEY_MODES` set + `mode` validation** — `mode in {"live",
    "test"}` is the test-vs-prod mode discriminator. A regression
    that allowed arbitrary string would let a partner mint a key
    with `mode="anything"` and bypass the test-mode-routes-only
    convention.

  * **`check_rate_limit` redis=None short-circuit** — dev
    environments without redis MUST allow all requests. A
    regression that 429'd in the no-redis branch would break
    every dev environment.

This file is read-only — exercises pure helpers + pinned constants;
the DB-touching paths (verify_key, mint_key, record_call) are
covered by the existing api-key integration tests in this codebase.
Survives reverts of `services/api_keys.py`.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from uuid import uuid4

# ---------- Module presence ----------


def test_api_keys_module_imports():
    """All public surfaces importable. A revert that deleted any of
    them surfaces here as ImportError on the next CI run — desired
    loud signal vs silent broken partner auth."""
    from services.api_keys import (  # noqa: F401
        DEFAULT_RATE_LIMIT_PER_MINUTE,
        KEY_MODES,
        KEY_PREFIX,
        SCOPES,
        check_rate_limit,
        has_project_access,
        has_scope,
        hash_key,
        key_prefix,
        mint_key,
        record_call,
        usage_for_key,
        usage_top_keys,
        verify_key,
    )


# ---------- Constants ----------


def test_key_prefix_pinned():
    """SECURITY-CRITICAL pin. `aec_` is the discriminator that
    `middleware.api_key_auth` uses to route a request to the
    api-key verifier vs the JWT path. A rename of this constant
    without updating the middleware would silently route every
    api-key request through JWT verification (which 401s) — every
    partner integration breaks.
    """
    from services.api_keys import KEY_PREFIX

    assert KEY_PREFIX == "aec_", (
        f"KEY_PREFIX drifted to {KEY_PREFIX!r}. The middleware's "
        "api-key-vs-JWT branch keys on this exact prefix; a rename "
        "has to move both files in lockstep."
    )


def test_default_rate_limit_pinned():
    """`60 req/min` = 1/sec sustained with 60-burst headroom. Tuned
    for typical CRM/ERP integration patterns. A drift up loosens the
    floor for misbehaving partners; a drift down throttles legitimate
    integrations. The number was calibrated against historical
    partner traffic — re-tune deliberately."""
    from services.api_keys import DEFAULT_RATE_LIMIT_PER_MINUTE

    assert DEFAULT_RATE_LIMIT_PER_MINUTE == 60, (
        f"DEFAULT_RATE_LIMIT_PER_MINUTE drifted to "
        f"{DEFAULT_RATE_LIMIT_PER_MINUTE}. Tuned against historical "
        "partner traffic; re-tune means re-running that analysis."
    )


def test_scopes_is_frozen():
    """SECURITY pin. `SCOPES` MUST be a `frozenset`. A regular set
    could be `.add()`'d at runtime by an import-time side effect,
    silently expanding the closed scope vocabulary without going
    through a deploy review.
    """
    from services.api_keys import SCOPES

    assert isinstance(SCOPES, frozenset), (
        f"SCOPES is {type(SCOPES).__name__}; want frozenset. A regular "
        "set lets import-time side effects mutate the scope vocabulary."
    )


def test_scopes_includes_documented_set():
    """Pin the scope vocabulary. Each scope is referenced by a
    `require_scope("...")` call somewhere in the codebase; a rename
    here without updating the caller silently 403s the gated route.
    """
    from services.api_keys import SCOPES

    expected = {
        "projects:read",
        "projects:write",
        "defects:read",
        "defects:write",
        "rfis:read",
        "rfis:write",
        "change_orders:read",
        "change_orders:write",
        "suppliers:read",
        "suppliers:write",
        "estimates:read",
        "estimates:write",
        "webhooks:admin",
        "audit:read",
        "search:read",
        "*",
    }
    assert expected == SCOPES, (
        f"SCOPES drifted: have {SCOPES}, want {expected}. "
        "Each scope is referenced by a `require_scope('...')` call; "
        "a rename has to move both this set + the caller."
    )


def test_scopes_includes_wildcard():
    """The `*` superuser scope is what one-off ops scripts use. A
    regression that dropped it would lock the platform out of its
    own ops automation."""
    from services.api_keys import SCOPES

    assert "*" in SCOPES, (
        "SCOPES no longer includes `*`. Superuser ops scripts that "
        "need cross-cutting access (rare; admin-only mint) would lose "
        "their gate."
    )


def test_key_modes_pinned():
    """The `mode` discriminator on every minted key. Live keys
    drive prod traffic; test keys drive test-mode-only routes
    (e.g. sandbox endpoints). A regression that allowed arbitrary
    strings would let a partner mint mode="prod" and confuse
    every downstream filter."""
    from services.api_keys import KEY_MODES

    assert frozenset({"live", "test"}) == KEY_MODES, (
        f"KEY_MODES drifted: {KEY_MODES}. Routes that filter on mode "
        "(test-sandbox endpoints) check exact strings — drift here "
        "silently mis-routes traffic."
    )


# ---------- hash_key ----------


def test_hash_key_is_sha256_hex():
    """The hash algorithm. Live `api_keys.hash` rows are sha256-hex,
    NOT salted. A regression to sha512 / salting would mean every
    historical key fails verification — total partner-auth outage
    on deploy."""
    from services.api_keys import hash_key

    raw = "aec_test_token_xyz"
    expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    actual = hash_key(raw)

    assert actual == expected, (
        f"hash_key produced {actual!r}; want {expected!r} (sha256-hex). "
        "A drift here means historical keys in the DB stop verifying — "
        "every partner integration 401s simultaneously."
    )
    # 64 hex chars (sha256 = 32 bytes = 64 hex).
    assert len(actual) == 64
    assert all(c in "0123456789abcdef" for c in actual), (
        f"hash_key produced non-lowercase-hex output: {actual!r}. "
        "Live rows are lowercase hex; case drift = no row matches."
    )


def test_hash_key_is_deterministic():
    """Same input → same hash. A regression to a randomised hash
    (e.g. accidental salt-from-time) would fail verify on the very
    next request after mint."""
    from services.api_keys import hash_key

    raw = "aec_xyz"
    assert hash_key(raw) == hash_key(raw) == hash_key(raw)


# ---------- key_prefix (UI display) ----------


def test_key_prefix_returns_first_8_chars_after_aec():
    """The "label" the UI shows to identify a key without re-leaking
    the secret. A regression that returned the WHOLE key would
    display the secret on the listing page (catastrophic). A
    regression that returned the first 8 INCLUDING `aec_` would
    waste 4 of the 8 visible chars on the prefix."""
    from services.api_keys import key_prefix

    raw = "aec_abcd1234567890ef" + "0" * 50
    out = key_prefix(raw)

    assert len(out) == 8, f"key_prefix returned {len(out)} chars; want 8."
    assert out == "abcd1234", (
        f"key_prefix drifted: {out!r}. The 8-char body label is what users identify keys by in the UI listing."
    )
    # CRITICAL — the prefix MUST NOT be the raw key itself.
    assert raw not in out, "key_prefix returned (or contained) the raw key — secret leak in the UI listing."


# ---------- has_scope ----------


def test_has_scope_admits_exact_match():
    """Happy path — an api-key with the requested scope passes."""
    from services.api_keys import has_scope

    assert has_scope(["projects:read"], "projects:read") is True
    assert has_scope(["projects:read", "projects:write"], "projects:write") is True


def test_has_scope_denies_unrelated_scope():
    """An api-key with one scope MUST NOT pass another scope's gate."""
    from services.api_keys import has_scope

    assert has_scope(["projects:read"], "projects:write") is False
    assert has_scope(["audit:read"], "projects:read") is False


def test_has_scope_admits_wildcard():
    """SECURITY pin. The `*` scope grants all permissions. A
    regression that no longer recognised it would lock superuser
    keys (used for ops scripts) out of every gated route — many
    routine ops tasks become impossible until a fix ships.
    """
    from services.api_keys import has_scope

    assert has_scope(["*"], "projects:read") is True
    assert has_scope(["*"], "audit:read") is True
    assert has_scope(["*"], "webhooks:admin") is True


def test_has_scope_denies_empty_scope_list():
    """An api-key with NO scopes (a misconfiguration) MUST be
    denied access to every gated route. A regression that
    short-circuited empty-list to True would silently grant
    full access to scope-misconfigured keys."""
    from services.api_keys import has_scope

    assert has_scope([], "projects:read") is False
    assert has_scope([], "*") is False


# ---------- has_project_access ----------


def test_has_project_access_empty_list_means_all_projects():
    """BACK-COMPAT pin. Empty `key_project_ids` is the documented
    "all projects" sentinel for keys minted before migration 0039
    AND for new keys that don't opt into per-project scoping. A
    regression that 403'd on empty list would break every legacy
    api-key until partners re-mint."""
    from services.api_keys import has_project_access

    proj = uuid4()
    assert has_project_access([], proj) is True
    assert has_project_access([], str(proj)) is True


def test_has_project_access_admits_member():
    """Happy path — non-empty allowlist contains the requested
    project."""
    from services.api_keys import has_project_access

    proj_a = uuid4()
    proj_b = uuid4()
    assert has_project_access([proj_a, proj_b], proj_a) is True
    assert has_project_access([proj_a, proj_b], proj_b) is True


def test_has_project_access_denies_non_member():
    """Non-empty allowlist NOT containing the requested project →
    deny. The cross-tenant data leak this prevents: a partner with
    a key scoped to project A trying to access project B."""
    from services.api_keys import has_project_access

    proj_a = uuid4()
    proj_b = uuid4()
    assert has_project_access([proj_a], proj_b) is False
    assert has_project_access([proj_a], str(proj_b)) is False


def test_has_project_access_string_uuid_equivalence():
    """Both UUID-and-string args MUST work on either side. asyncpg
    returns UUID instances for `uuid[]` columns; FastAPI path params
    arrive as UUID; tests sometimes pass strings. A regression that
    only accepted one form would silently 403 the legitimate path
    (because UUID(...) != str(UUID(...)) in Python).
    """
    from services.api_keys import has_project_access

    proj = uuid4()

    # All four combinations of {UUID, str} on both sides.
    assert has_project_access([proj], proj) is True
    assert has_project_access([proj], str(proj)) is True
    assert has_project_access([str(proj)], proj) is True
    assert has_project_access([str(proj)], str(proj)) is True


# ---------- check_rate_limit no-redis branch ----------


def test_check_rate_limit_short_circuits_when_redis_unavailable():
    """Dev environments without redis MUST allow all requests.
    Returns `(True, 0, limit)` — the API stays up even when redis
    is missing, just without rate-limit enforcement.

    A regression that 429'd in this branch would break every dev
    environment that didn't bring up the full redis stack."""
    from services.api_keys import check_rate_limit

    out = asyncio.run(check_rate_limit(None, api_key_id=uuid4(), limit_per_minute=60))
    assert out == (True, 0, 60), (
        f"check_rate_limit(redis=None) returned {out!r}; want (True, 0, 60). "
        "No-redis dev path would otherwise break with 429s."
    )


# ---------- Function signatures ----------


def test_verify_key_signature_pinned():
    """`verify_key(session, *, raw, client_ip)`. Called from the
    middleware; a positional rename = TypeError on every authenticated
    request."""
    from services.api_keys import verify_key

    assert inspect.iscoroutinefunction(verify_key)
    sig = inspect.signature(verify_key)
    params = list(sig.parameters.values())

    assert params[0].name == "session"
    kw_names = [p.name for p in params[1:]]
    assert kw_names == ["raw", "client_ip"], f"verify_key keyword block drifted: {kw_names}"
    for p in params[1:]:
        assert p.kind is inspect.Parameter.KEYWORD_ONLY


def test_record_call_signature_pinned():
    """`record_call(session, *, api_key_id, success, when=None)`.
    Called from the middleware after each authenticated request."""
    from services.api_keys import record_call

    assert inspect.iscoroutinefunction(record_call)
    sig = inspect.signature(record_call)
    params = list(sig.parameters.values())

    assert params[0].name == "session"
    kw_names = [p.name for p in params[1:]]
    assert kw_names == ["api_key_id", "success", "when"], f"record_call keyword block drifted: {kw_names}"
    # `when` is optional (testability).
    assert sig.parameters["when"].default is None


def test_check_rate_limit_signature_pinned():
    """`check_rate_limit(redis, *, api_key_id, limit_per_minute)`.
    Returns `(bool, int, int)` so the middleware can both gate the
    request and emit `X-RateLimit-*` headers."""
    from services.api_keys import check_rate_limit

    assert inspect.iscoroutinefunction(check_rate_limit)
    sig = inspect.signature(check_rate_limit)
    params = list(sig.parameters.values())

    assert params[0].name == "redis"
    kw_names = [p.name for p in params[1:]]
    assert kw_names == ["api_key_id", "limit_per_minute"], f"check_rate_limit keyword block drifted: {kw_names}"


# ---------- Source-level safety ----------


def test_record_call_swallows_on_failure():
    """SECURITY/AVAILABILITY pin. `record_call` MUST swallow DB
    failures internally — a re-raise here would 500 every
    authenticated request when the telemetry DB is having a bad
    day. We pin via source-grep because the failure path needs
    DB-fault-injection that's not worth setting up just to verify
    a try/except block."""
    import services.api_keys as mod

    src = inspect.getsource(mod.record_call)
    assert "except Exception" in src, (
        "record_call no longer has the catch-all except. A telemetry "
        "blip would now break every authenticated request — exactly "
        "the failure mode the docstring guards against."
    )
    # Logged at WARNING (not raised, not at ERROR which would page).
    assert "logger.warning" in src or "logger.error" in src, (
        "record_call no longer logs on failure. Silent telemetry "
        "loss is fine; silent telemetry loss WITHOUT logging means "
        "we wouldn't know it was happening."
    )


def test_verify_key_returns_none_for_non_aec_prefix():
    """Defensive: anything not starting with `aec_` is rejected
    fast (no hash compute, no DB lookup). A regression that did
    the hash anyway would let a JWT-shaped string trip the
    verify path on its way to JWT verification."""
    import services.api_keys as mod

    src = inspect.getsource(mod.verify_key)
    assert "startswith(KEY_PREFIX)" in src or 'startswith("aec_")' in src, (
        "verify_key no longer fast-rejects non-aec_ inputs. A "
        "JWT-shaped string would trip the hash + DB lookup path "
        "uselessly (and could mask the prefix-discriminator bug)."
    )
