"""Pin the `services.idempotency` retry-safety contract.

This module is the most security-and-correctness-sensitive surface
in the API: it's what makes partner integrations safe to retry. A
silent regression here has two distinct failure modes, both bad:

  * **Cache miss when there should be a hit** — partner retries
    after a network blip; we run the handler again. Charges twice,
    creates two RFQs from one submit, sends the same email twice.
    Customers find out via duplicate-data tickets days later.

  * **Cache hit when there should be a miss** — different request
    body collides with a previously-seen key, and we replay the OLD
    response instead of running the handler. Partner thinks their
    new write landed; nothing happened. Strictly worse than the
    duplicate case because the silent-data-loss is unrecoverable.

The Stripe-style invariants that prevent both:

  1. **Body canonicalisation** — `{"a":1,"b":2}` and `{"b":2,"a":1}`
     hash the same. Without this, a partner whose JSON serialiser
     orders keys differently across retries would never hit the
     cache (silent duplicate-process).

  2. **Hash discriminator includes method + path** — same key on a
     different route is a partner integration bug. We 422 it
     rather than silently replaying.

  3. **Signature stability** — every retry-safe handler in the
     codebase calls `maybe_handle(session, api_key_id=..., request=...,
     method=..., path=...)`. A keyword rename = TypeError at
     runtime in handlers that opted in.

This file is read-only; it imports the module and runs its pure
functions. Survives reverts of the source file (the source has so
far been stable, but the cost of a regression here is high enough
that a tripwire is cheap).

Pinned contracts:

  * `MAX_KEY_LEN == 200` (matches the migration's CHECK constraint).
  * `canonicalise_body` produces the same bytes for key-permuted JSON.
  * `canonicalise_body` passes non-JSON bodies through unchanged.
  * `hash_body` returns sha256-hex (64 lowercase hex chars).
  * `IdempotencyResult` discriminator properties: `cached`, `fresh`,
    plus the implicit "mismatch" branch.
  * `maybe_handle` keyword-only signature pinned.
  * `persist_response` keyword-only signature pinned.
  * `lookup_or_lock` keyword-only signature pinned.
"""

from __future__ import annotations

import inspect

# ---------- Module presence ----------


def test_idempotency_module_imports():
    """All public functions importable. A revert that deleted any of
    them surfaces here as a hard ImportError on the next CI run —
    the desired signal vs. silently breaking the retry-safe handlers."""
    from services.idempotency import (  # noqa: F401
        MAX_KEY_LEN,
        IdempotencyResult,
        canonicalise_body,
        hash_body,
        lookup_or_lock,
        maybe_handle,
        persist_response,
    )


# ---------- MAX_KEY_LEN ----------


def test_max_key_len_pinned_at_200():
    """`MAX_KEY_LEN == 200` mirrors the migration's CHECK constraint
    on `idempotency_records.key`. A regression that raised this
    cap in code without a matching migration would let callers
    submit a 500-char key, hash a 1MB body for it, then 23505
    on the INSERT — partner sees a 500 instead of the expected
    422 / replay."""
    from services.idempotency import MAX_KEY_LEN

    assert MAX_KEY_LEN == 200, (
        f"MAX_KEY_LEN drifted to {MAX_KEY_LEN}. The migration's CHECK "
        "is 200; if you raise this in code, the migration has to move "
        "in lockstep AND prod indexes need a rebuild."
    )


# ---------- canonicalise_body ----------


def test_canonicalise_body_sorts_json_keys():
    """SECURITY-CRITICAL pin. Two semantically-identical JSON bodies
    with different key ordering MUST hash the same — otherwise a
    partner whose JSON serialiser doesn't preserve order across
    retries would NEVER hit the cache, and our retry-safety promise
    becomes a lie.
    """
    from services.idempotency import canonicalise_body

    a = b'{"name":"foo","price":10,"qty":2}'
    b = b'{"qty":2,"price":10,"name":"foo"}'

    canon_a = canonicalise_body(a)
    canon_b = canonicalise_body(b)

    assert canon_a == canon_b, (
        f"canonicalise_body produced different bytes for "
        f"key-permuted JSON: {canon_a!r} vs {canon_b!r}. The retry-"
        "safety contract requires deterministic byte output."
    )


def test_canonicalise_body_strips_whitespace():
    """JSON with insignificant whitespace MUST hash the same as the
    minimal form. A partner's pretty-printer-vs-minifier difference
    across retries is a real-world failure mode."""
    from services.idempotency import canonicalise_body

    pretty = b'{\n  "name": "foo",\n  "price": 10\n}'
    minimal = b'{"name":"foo","price":10}'

    assert canonicalise_body(pretty) == canonicalise_body(minimal)


def test_canonicalise_body_passes_non_json_through():
    """Multipart, plain text, binary uploads MUST hash bytes-as-is.
    A regression that tried to JSON-decode every body would either
    raise on binary uploads OR (worse) silently empty out the hash
    input, making every multipart upload collide on the empty hash."""
    from services.idempotency import canonicalise_body

    binary = b"\x00\x01\x02\xff"
    plain = b"this is not JSON"

    assert canonicalise_body(binary) == binary
    assert canonicalise_body(plain) == plain


def test_canonicalise_body_handles_empty():
    """Empty body cases — None, b"", "" — MUST canonicalise to b"".
    Without this guard, a None body would crash before hashing AND
    a partner retrying a no-body POST would never hit the cache."""
    from services.idempotency import canonicalise_body

    assert canonicalise_body(None) == b""
    assert canonicalise_body(b"") == b""
    assert canonicalise_body("") == b""


def test_canonicalise_body_accepts_str_input():
    """Both `bytes` and `str` inputs are valid — handlers may have
    already-decoded the body before passing it in. A regression
    that required only bytes would TypeError at runtime in handlers
    that opted into idempotency on str-typed bodies."""
    from services.idempotency import canonicalise_body

    s = '{"a":1,"b":2}'
    b = b'{"a":1,"b":2}'

    assert canonicalise_body(s) == canonicalise_body(b)


# ---------- hash_body ----------


def test_hash_body_returns_sha256_hex():
    """`hash_body` MUST return sha256 hex (64 lowercase hex chars).
    A drift to MD5 / SHA-1 would weaken the collision resistance;
    a drift to a different hex case (uppercase) would fail to match
    historical rows in the DB."""
    from services.idempotency import hash_body

    h = hash_body(b'{"foo":"bar"}')
    assert isinstance(h, str)
    assert len(h) == 64, f"hash_body returned {len(h)} chars; want 64 (sha256-hex)."
    # Lowercase-hex check.
    assert all(c in "0123456789abcdef" for c in h), (
        f"hash_body produced non-lowercase-hex output: {h!r}. "
        "Historical rows in `idempotency_records` are lowercase-hex; "
        "case drift = no row matches and every retry runs the handler."
    )


def test_hash_body_is_deterministic():
    """Same input → same hash, multiple calls. Defensive against a
    regression that introduced randomness (e.g. salting) without
    realising the cache lookup depends on determinism."""
    from services.idempotency import hash_body

    body = b'{"x":1}'
    assert hash_body(body) == hash_body(body) == hash_body(body)


def test_hash_body_distinguishes_different_bodies():
    """Different bodies MUST hash differently — collision would mean
    "partner sent a different request, but we replay the old
    response" (the silent-data-loss failure mode)."""
    from services.idempotency import hash_body

    h1 = hash_body(b'{"a":1}')
    h2 = hash_body(b'{"a":2}')
    assert h1 != h2


# ---------- IdempotencyResult discriminators ----------


def test_idempotency_result_fresh_state():
    """No cached_status + no mismatch = `fresh`. Caller's branch:
    `if idem.fresh: ...run handler..."""
    from services.idempotency import IdempotencyResult

    fresh = IdempotencyResult(request_hash="abc")
    assert fresh.fresh is True
    assert fresh.cached is False
    assert fresh.mismatch is False


def test_idempotency_result_cached_state():
    """`cached_status` set = `cached`. Caller's branch:
    `if idem.cached: return JSONResponse(idem.cached_body, ...)`."""
    from services.idempotency import IdempotencyResult

    cached = IdempotencyResult(
        request_hash="abc",
        cached_status=200,
        cached_body={"data": {"id": "x"}},
    )
    assert cached.cached is True
    assert cached.fresh is False
    assert cached.mismatch is False


def test_idempotency_result_mismatch_state():
    """`mismatch=True` = caller MUST 422. The "fresh" property MUST
    be False (a mismatch isn't a fresh request — it's a partner
    integration bug)."""
    from services.idempotency import IdempotencyResult

    mismatch = IdempotencyResult(request_hash="abc", mismatch=True)
    assert mismatch.mismatch is True
    assert mismatch.cached is False
    assert mismatch.fresh is False, (
        "A mismatch result MUST NOT report `fresh=True` — caller "
        "would skip the 422 branch and run the handler with the new "
        "body, defeating the conflict-detection purpose."
    )


# ---------- Function signatures ----------


def test_maybe_handle_signature_pinned():
    """`maybe_handle(session, *, api_key_id, request, method, path)`.

    The keyword-only block is the contract every retry-safe handler
    relies on. A positional swap or rename would TypeError every
    handler that opted in.
    """
    from services.idempotency import maybe_handle

    sig = inspect.signature(maybe_handle)
    params = list(sig.parameters.values())

    # First positional: session.
    assert params[0].name == "session"

    # All other params are keyword-only.
    kw_names = [p.name for p in params[1:]]
    assert kw_names == ["api_key_id", "request", "method", "path"], f"maybe_handle keyword block drifted: {kw_names}"
    for p in params[1:]:
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, f"`{p.name}` MUST be keyword-only — handlers pass by name."


def test_maybe_handle_is_async():
    """`maybe_handle` is awaited inside FastAPI handlers. A sync
    regression would silently no-op (await on non-coro returns the
    value immediately AND the DB lookup never runs)."""
    from services.idempotency import maybe_handle

    assert inspect.iscoroutinefunction(maybe_handle), (
        "maybe_handle MUST be async — handlers await it; sync = silent skip."
    )


def test_persist_response_signature_pinned():
    """`persist_response(session, *, api_key_id, key, request_hash,
    method, path, response_status, response_body)`."""
    from services.idempotency import persist_response

    sig = inspect.signature(persist_response)
    params = list(sig.parameters.values())

    assert params[0].name == "session"

    kw_names = [p.name for p in params[1:]]
    expected = [
        "api_key_id",
        "key",
        "request_hash",
        "method",
        "path",
        "response_status",
        "response_body",
    ]
    assert kw_names == expected, f"persist_response keyword block drifted: {kw_names}, want {expected}"


def test_lookup_or_lock_signature_pinned():
    """`lookup_or_lock(session, *, api_key_id, key, request_hash,
    method, path)`. The `method`+`path` discriminator is what makes
    "same key on different route" a 422 rather than a silent replay
    of an unrelated response."""
    from services.idempotency import lookup_or_lock

    sig = inspect.signature(lookup_or_lock)
    params = list(sig.parameters.values())

    assert params[0].name == "session"

    kw_names = [p.name for p in params[1:]]
    expected = ["api_key_id", "key", "request_hash", "method", "path"]
    assert kw_names == expected, (
        f"lookup_or_lock keyword block drifted: {kw_names}. "
        "The (method, path) discriminator is part of the cache key — "
        "dropping either would let 'same key, different route' "
        "silently replay the wrong response."
    )


def test_lookup_or_lock_is_async():
    """Async via FOR UPDATE — a sync regression would deadlock the
    async stack on first call."""
    from services.idempotency import lookup_or_lock

    assert inspect.iscoroutinefunction(lookup_or_lock)


# ---------- FOR UPDATE in source ----------


def test_lookup_or_lock_uses_for_update():
    """SECURITY-CRITICAL pin. `FOR UPDATE` serialises concurrent
    retries through the same key — without it, two parallel retries
    from the same partner could both find no row and both run the
    handler, defeating the entire purpose of idempotency.

    Pin the literal `FOR UPDATE` in the source so a "performance
    optimisation" that drops the row-lock has to be deliberate.
    """
    import services.idempotency as idem_mod

    src = inspect.getsource(idem_mod.lookup_or_lock)
    assert "FOR UPDATE" in src, (
        "`lookup_or_lock` no longer uses `SELECT ... FOR UPDATE`. "
        "Without it, concurrent retries can both find no row and both "
        "run the handler — silent duplicate-process. If this was a "
        "deliberate optimisation, also prove the new path's serialisation."
    )


def test_persist_response_uses_on_conflict_do_nothing():
    """The first writer wins; a near-simultaneous second handler
    invocation that escaped FOR UPDATE serialisation (rare; possible
    across replicas) MUST NOT 500 on PK violation. `ON CONFLICT
    DO NOTHING` is the safety net.
    """
    import services.idempotency as idem_mod

    src = inspect.getsource(idem_mod.persist_response)
    assert "ON CONFLICT" in src and "DO NOTHING" in src, (
        "`persist_response` no longer uses ON CONFLICT DO NOTHING. "
        "A cross-replica race that escaped FOR UPDATE would now 500 "
        "the user-facing response on PK violation, even though the "
        "original write committed."
    )
