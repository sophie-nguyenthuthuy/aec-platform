"""Pin the `services.activity_stream` SSE pub/sub contract.

The activity stream is the real-time-update path the dashboard
uses for "approval landed → row appears in <500ms" UX. Three
moving parts must stay in lockstep:

  * **Ticket TTL + key prefix.** `mint_ticket` writes to Redis
    under `aec:sse:ticket:<uuid>` with a 30s TTL; `redeem_ticket`
    GETDELs from the same prefix. A prefix rename here = every
    open EventSource silently can't resume after a server
    restart, AND the frontend's POST-then-EventSource handshake
    reads from a different namespace.

  * **Channel naming.** `aec:activity:<org_id>:<project_id>` (or
    `:org` for org-wide). `services.audit.record` PUBLISHes here;
    SSE handlers SUBSCRIBE here. A drift on one side without the
    other = published events never reach subscribed clients
    (silent "feed froze" failure mode that's only visible by
    comparing timestamps in the UI vs the audit table).

  * **Heartbeat cadence.** 15s comment-frame keeps proxies from
    idle-disconnecting. Proxies typically drop at 60s; 15s gives
    ~3 chances. A regression to 60s+ silently breaks the stream
    behind any LB with default timeouts.

This file is read-only; it imports the module and inspects the
public surface. Survives reverts.

Pinned contracts:

  * `TICKET_TTL_SECONDS == 30` and `HEARTBEAT_INTERVAL_SECONDS == 15`.
  * `_TICKET_KEY_PREFIX == "aec:sse:ticket:"` (frontend handshake
    + audit pubsub assume this exact namespace).
  * `_channel_name(org, project)` produces `"aec:activity:<org>:<proj-or-org>"`.
  * `mint_ticket` / `redeem_ticket` / `publish_activity` / `subscribe_activity`
    are async with documented signatures.
  * `redeem_ticket` is one-shot (uses GETDEL, not GET) — replay
    defense.
  * `publish_activity` and `mint_ticket` short-circuit cleanly
    when redis=None (dev-without-redis path).
"""

from __future__ import annotations

import inspect
from uuid import UUID, uuid4

# ---------- Module presence ----------


def test_activity_stream_module_imports():
    """All public surfaces importable. Hard ImportError on revert =
    desired signal, vs silent broken SSE."""
    from services.activity_stream import (  # noqa: F401
        _TICKET_KEY_PREFIX,
        HEARTBEAT_INTERVAL_SECONDS,
        TICKET_TTL_SECONDS,
        _channel_name,
        _redis_or_none,
        mint_ticket,
        publish_activity,
        redeem_ticket,
        subscribe_activity,
    )


# ---------- Constants ----------


def test_ticket_ttl_pinned_at_30_seconds():
    """30s ticket TTL is the trade-off between:
      * Long enough that a slow CDN edge between mint and EventSource
        connect doesn't expire the ticket (typical happy-path is ~50ms).
      * Short enough that a leaked ticket can't be hoarded for replay.

    A drift up (300s) widens the replay-attack window. A drift down
    (5s) breaks slow-network users behind a CDN.
    """
    from services.activity_stream import TICKET_TTL_SECONDS

    assert TICKET_TTL_SECONDS == 30, (
        f"TICKET_TTL_SECONDS drifted to {TICKET_TTL_SECONDS}. The current "
        "value balances slow-CDN tolerance against ticket-replay window. "
        "Re-tuning has UX + security implications — pin so the change "
        "is deliberate."
    )


def test_heartbeat_interval_pinned_at_15_seconds():
    """15s comment-frame keeps proxies from idle-disconnecting.
    Most LBs drop idle TCP at 60s; 15s gives ~3 chances per minute.
    A drift to 60s+ silently breaks streams behind any default LB."""
    from services.activity_stream import HEARTBEAT_INTERVAL_SECONDS

    assert HEARTBEAT_INTERVAL_SECONDS == 15, (
        f"HEARTBEAT_INTERVAL_SECONDS drifted to "
        f"{HEARTBEAT_INTERVAL_SECONDS}. Default LB idle timeouts are "
        "60s; cadences ≥30s start losing connections silently."
    )


def test_ticket_key_prefix_pinned():
    """`aec:sse:ticket:` is the Redis namespace the frontend's
    handshake and the SSE redeem path both assume. A rename on one
    side without the other = mint writes to namespace A, redeem
    looks up namespace B, every connection 401s."""
    from services.activity_stream import _TICKET_KEY_PREFIX

    assert _TICKET_KEY_PREFIX == "aec:sse:ticket:", (
        f"_TICKET_KEY_PREFIX drifted to {_TICKET_KEY_PREFIX!r}. The "
        "frontend's POST-then-EventSource handshake reads/writes this "
        "literal prefix; a rename has to move both sides in lockstep."
    )


# ---------- Channel naming ----------


def test_channel_name_includes_org_and_project_id():
    """Pub/sub fan-out granularity. The audit module PUBLISHes via
    `_channel_name(org, project)`; SSE subscribers SUBSCRIBE via
    `_channel_name(org, project)`. A rename here = published events
    never reach subscribers (silent "feed frozen" failure)."""
    from services.activity_stream import _channel_name

    org = UUID("11111111-1111-1111-1111-111111111111")
    proj = UUID("22222222-2222-2222-2222-222222222222")

    name = _channel_name(org, proj)
    assert name == f"aec:activity:{org}:{proj}", (
        f"_channel_name drifted: {name!r}. Both audit.record (publisher) "
        "and the SSE handler (subscriber) build channel names from this "
        "function — a format change on one side without the other "
        "silently breaks the realtime feed."
    )


def test_channel_name_for_org_wide_uses_org_sentinel():
    """When `project_id is None` (org-wide events), the suffix is
    the literal string `"org"`. A regression that emitted
    `aec:activity:<org>:None` would silently route org-wide events
    to a different channel than the org-wide-pattern subscribers
    listen on."""
    from services.activity_stream import _channel_name

    org = UUID("11111111-1111-1111-1111-111111111111")
    name = _channel_name(org, None)

    assert name == f"aec:activity:{org}:org", (
        f"_channel_name(org, None) drifted to {name!r}. Org-wide "
        "subscribers match the literal `:org` suffix; a change "
        "here breaks them silently."
    )
    # And explicitly NOT the python-stringification of None.
    assert "None" not in name, (
        f"_channel_name leaked Python's `None` into the channel name: {name!r}. Subscribers match `:org`, not `:None`."
    )


def test_channel_name_pattern_compatible():
    """Org-wide subscribers can use the Redis pattern
    `aec:activity:<org>:*` to match BOTH per-project and org-wide
    channels. Pin that the per-project channel format keeps `<org>:`
    as a discriminator before the project segment.
    """
    from services.activity_stream import _channel_name

    org = UUID("11111111-1111-1111-1111-111111111111")
    proj = UUID("22222222-2222-2222-2222-222222222222")

    per_project = _channel_name(org, proj)
    org_wide = _channel_name(org, None)

    # Both must start with the same `aec:activity:<org>:` prefix
    # so a single PSUBSCRIBE pattern catches them.
    common_prefix = f"aec:activity:{org}:"
    assert per_project.startswith(common_prefix)
    assert org_wide.startswith(common_prefix)


# ---------- Function signatures ----------


def test_mint_ticket_signature_pinned():
    """`mint_ticket(redis, *, user_id, organization_id, project_id)`.
    Routers call this by keyword; a positional rename = TypeError
    in the SSE-ticket route."""
    from services.activity_stream import mint_ticket

    sig = inspect.signature(mint_ticket)
    params = list(sig.parameters.values())

    assert params[0].name == "redis"
    kw_names = [p.name for p in params[1:]]
    assert kw_names == ["user_id", "organization_id", "project_id"], f"mint_ticket keyword block drifted: {kw_names}"
    for p in params[1:]:
        assert p.kind is inspect.Parameter.KEYWORD_ONLY


def test_mint_ticket_is_async():
    """Awaited in the route handler — sync regression silently no-ops."""
    from services.activity_stream import mint_ticket

    assert inspect.iscoroutinefunction(mint_ticket)


def test_redeem_ticket_signature_pinned():
    """`redeem_ticket(redis, ticket)`. Two positional args (the
    ticket is read off the query string and passed positionally)."""
    from services.activity_stream import redeem_ticket

    sig = inspect.signature(redeem_ticket)
    params = list(sig.parameters.values())
    names = [p.name for p in params]
    assert names == ["redis", "ticket"], f"redeem_ticket signature drifted: {names}"


def test_publish_activity_signature_pinned():
    """`publish_activity(redis, *, organization_id, project_id, event)`.
    Called from `services.audit.record`; a rename = silent feed
    breakage (publish becomes a no-op or crashes the audit txn)."""
    from services.activity_stream import publish_activity

    sig = inspect.signature(publish_activity)
    params = list(sig.parameters.values())

    assert params[0].name == "redis"
    kw_names = [p.name for p in params[1:]]
    assert kw_names == ["organization_id", "project_id", "event"], f"publish_activity keyword block drifted: {kw_names}"


def test_subscribe_activity_signature_pinned():
    """`subscribe_activity(redis, *, organization_id, project_id)`.
    Returns an async iterator the SSE handler awaits in a loop."""
    from services.activity_stream import subscribe_activity

    sig = inspect.signature(subscribe_activity)
    params = list(sig.parameters.values())

    assert params[0].name == "redis"
    kw_names = [p.name for p in params[1:]]
    assert kw_names == ["organization_id", "project_id"], f"subscribe_activity keyword block drifted: {kw_names}"


# ---------- Redis-less dev-path safety ----------


def test_mint_ticket_returns_none_when_redis_unavailable():
    """`redis=None` MUST short-circuit cleanly. Dev environments
    without Redis (`docker compose up -d` minus the redis service)
    boot fine and the SSE route 503s gracefully — vs raising and
    crashing the request handler."""
    import asyncio

    from services.activity_stream import mint_ticket

    out = asyncio.run(
        mint_ticket(
            None,
            user_id=uuid4(),
            organization_id=uuid4(),
            project_id=None,
        )
    )
    assert out is None, (
        f"mint_ticket(redis=None) returned {out!r}; want None so the "
        "SSE handshake route can 503 gracefully in dev-without-redis."
    )


def test_redeem_ticket_returns_none_when_redis_unavailable():
    """Symmetric to mint_ticket — None redis = None ticket result."""
    import asyncio

    from services.activity_stream import redeem_ticket

    out = asyncio.run(redeem_ticket(None, "any-ticket-id"))
    assert out is None


def test_publish_activity_is_noop_when_redis_unavailable():
    """`redis=None` MUST silently no-op. Called from
    `services.audit.record` — a raise here would propagate and
    break the audit txn entirely. Dev-without-redis is supposed
    to mean "no realtime stream" not "audit broken."
    """
    import asyncio

    from services.activity_stream import publish_activity

    # Returns None (implicit), never raises.
    asyncio.run(
        publish_activity(
            None,
            organization_id=uuid4(),
            project_id=None,
            event={"action": "test", "actor_id": "x"},
        )
    )


# ---------- Source-level invariants ----------


def test_redeem_ticket_uses_atomic_getdel():
    """SECURITY-CRITICAL pin. The one-shot semantics of redeem_ticket
    rely on atomic GET+DEL — a leaked ticket can be replayed within
    30s, but only by the first connection to win the GETDEL race.
    A regression that just GET'd (without delete) would let a
    leaked ticket be replayed indefinitely until TTL expiry,
    widening the threat model from "30s race window" to "30s
    replay window."
    """
    import services.activity_stream as mod

    src = inspect.getsource(mod.redeem_ticket)
    # Either GETDEL (Redis 6.2+) or a GET+DEL pipeline — both atomic.
    assert "getdel" in src.lower() or ("pipeline" in src and "delete" in src), (
        "redeem_ticket no longer uses atomic GETDEL (or a GET+DEL "
        "pipeline). Without atomicity, a leaked ticket could be "
        "replayed until TTL expiry — widens the SSE replay window."
    )
