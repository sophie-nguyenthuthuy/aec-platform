"""Pin the actor-routing + webhook-coupling invariants in
`services.audit.record`.

The function signature is already pinned in
`tests/test_audit_record_signature_pin.py`. THIS file pins the
behavioural invariants of the body — the bits that don't show up
in the signature but determine whether the audit log is correct
and the webhook outbox is consistent:

  * **Actor-routing branch.** The function takes an `AuthContext`,
    which can be either a user-JWT context (`auth.role != "api_key"`,
    `auth.user_id` IS a real users.id UUID) OR an api-key context
    (`auth.role == "api_key"`, `auth.user_id` IS actually an api_keys.id
    UUID — see the synthesis in `middleware.api_key_auth._api_key_auth`).
    The two columns `actor_user_id` and `actor_api_key_id` are FKs
    into different tables. Routing the api-key id into `actor_user_id`
    would either:
      - 23503 violate the FK to `users.id` at flush time (loud), or
      - happen to match a real users.id and silently mis-attribute
        the action to the wrong principal (quiet, worst-case).

  * **Webhook outbox coupling.** Every audit-recorded action
    enqueues a `webhook_deliveries` row in the SAME session, so the
    caller's transaction is the unit of consistency: rollback rolls
    back both. A regression that committed the audit row directly
    (or fetched a fresh session) would let customers receive
    webhooks for actions whose surrounding write failed — silent
    "phantom approval" notifications.

  * **System-actor branch.** When `auth is None` (cron jobs, queue
    workers), BOTH actor columns stay NULL. A regression that put
    a placeholder UUID in either column would corrupt the audit-
    log filtering ("show me actions by user X" would return system
    actions misattributed to the placeholder).

  * **Default empty diffs.** `before` / `after` default to `{}` (NOT
    `None`) on the row. JSONB-NOT-NULL on the column would 500
    every audit insert; a regression to None propagation surfaces
    here.

This file is read-only — exercises `record()` against an in-memory
SQLite session with a stubbed `services.webhooks.enqueue_event` so
no real webhook subscription is needed. Survives reverts.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

# ---------- Webhook coupling — source-grep pins ----------


def test_record_uses_lazy_import_for_webhook_enqueue():
    """The webhook outbox enqueue is lazy-imported inside `record()`.
    A regression that hoisted the import to module-top would create
    the circular import the docstring guards against
    (webhooks → audit → webhooks). Pin the lazy form via source-grep.
    """
    import services.audit as audit_mod

    src = inspect.getsource(audit_mod.record)
    assert "from services.webhooks import enqueue_event" in src, (
        "audit.record no longer lazy-imports webhook enqueue inside "
        "the function body. Hoisting to module-top would re-introduce "
        "the circular import (webhooks.enqueue_event imports from "
        "audit context indirectly)."
    )


def test_record_passes_session_to_webhook_enqueue():
    """SECURITY-CRITICAL pin. The webhook outbox row MUST be inserted
    via the SAME session the caller passed in — that's what makes
    audit + webhook atomic with the caller's surrounding write. A
    regression that opened a fresh session for the enqueue would
    let webhooks fire for actions whose audit row rolled back
    (phantom-notification failure mode)."""
    import services.audit as audit_mod

    src = inspect.getsource(audit_mod.record)
    # Verify the call site passes `session` as the first positional
    # arg to enqueue_event — NOT `AdminSessionFactory()` or similar.
    assert "_webhook_enqueue(\n        session," in src or "_webhook_enqueue(session," in src, (
        "audit.record no longer passes the caller's session to the "
        "webhook enqueue. Atomicity is broken — a rolled-back write "
        "could still fire a customer webhook for the action."
    )


def test_record_forwards_action_as_event_type():
    """The `event_type` on the webhook row MUST be the same string
    as the audit `action`. Customer subscriptions filter on
    event_type; if these drift, every audit-driven webhook
    silently stops matching the subscription."""
    import services.audit as audit_mod

    src = inspect.getsource(audit_mod.record)
    assert "event_type=action" in src, (
        "audit.record no longer forwards `action` as the webhook "
        "`event_type`. A drift here means customer subscriptions "
        "filtering on documented event types stop matching."
    )


def test_record_includes_actor_ids_in_webhook_payload():
    """The webhook payload MUST carry both `actor_user_id` and
    `actor_api_key_id` so customer-side handlers can attribute
    the action without joining back to our DB. A regression
    that omitted either would let a customer's "who did this?"
    log lose the discriminator between human and machine actors.
    """
    import services.audit as audit_mod

    src = inspect.getsource(audit_mod.record)
    assert '"actor_user_id"' in src, "audit.record's webhook payload no longer carries actor_user_id."
    assert '"actor_api_key_id"' in src, "audit.record's webhook payload no longer carries actor_api_key_id."


# ---------- Actor-routing — runtime exercise ----------


@pytest.fixture
def patched_webhook_enqueue(monkeypatch):
    """Stub `services.webhooks.enqueue_event` so the audit-record
    flow doesn't try to look up subscriptions in a real DB. The
    pins above already cover the wiring; this fixture lets us
    exercise the actor-routing branch without DB infrastructure."""
    calls: list[dict] = []

    async def _stub(session, **kwargs):
        calls.append(kwargs)

    # Patch by attribute on the imported module — `services.audit`
    # imports inside `record()`, so we have to patch the source
    # module not just the local name.
    import services.webhooks as webhooks_mod

    monkeypatch.setattr(webhooks_mod, "enqueue_event", _stub)
    return calls


class _StubSession:
    """Minimal AsyncSession stand-in. Captures `add()` calls and
    is otherwise inert — `record()` doesn't commit, so we don't
    need any real DB plumbing."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)


@pytest.mark.asyncio
async def test_record_routes_user_actor_to_actor_user_id(patched_webhook_enqueue):
    """User-JWT caller (`role != "api_key"`) — the AuthContext's
    `user_id` IS a real users.id UUID. MUST land on `actor_user_id`.
    """
    from middleware.auth import AuthContext
    from services.audit import record

    user_id = uuid4()
    org_id = uuid4()
    user_ctx = AuthContext(
        user_id=user_id,
        organization_id=org_id,
        role="admin",
        email="admin@example.com",
    )

    session = _StubSession()
    event = await record(
        session,  # type: ignore[arg-type]
        organization_id=org_id,
        auth=user_ctx,
        action="org.member.role_change",
        resource_type="org_member",
        resource_id=uuid4(),
    )

    assert event.actor_user_id == user_id, (
        f"User-JWT context's user_id was NOT routed to actor_user_id; "
        f"got {event.actor_user_id!r}. Audit log loses attribution."
    )
    assert event.actor_api_key_id is None, (
        f"actor_api_key_id leaked a value ({event.actor_api_key_id!r}) "
        "for a user-JWT actor. Both columns set on the same row "
        "would mis-attribute the action."
    )


@pytest.mark.asyncio
async def test_record_routes_api_key_actor_to_actor_api_key_id(patched_webhook_enqueue):
    """SECURITY-CRITICAL pin. Api-key caller (`role == "api_key"`) —
    the AuthContext's `user_id` is actually an api_keys.id (per the
    synthesis in `middleware.api_key_auth._api_key_auth`). MUST
    land on `actor_api_key_id` so the FK to users.id doesn't fail.
    """
    from middleware.auth import AuthContext
    from services.audit import record

    api_key_id = uuid4()
    org_id = uuid4()
    api_key_ctx = AuthContext(
        user_id=api_key_id,  # SYNTHESISED — actually api_keys.id
        organization_id=org_id,
        role="api_key",
        email="",
        api_key_id=api_key_id,
    )

    session = _StubSession()
    event = await record(
        session,  # type: ignore[arg-type]
        organization_id=org_id,
        auth=api_key_ctx,
        action="costpulse.boq.import",
        resource_type="boq_import",
        resource_id=uuid4(),
    )

    assert event.actor_api_key_id == api_key_id, (
        f"Api-key context's user_id was NOT routed to actor_api_key_id; "
        f"got {event.actor_api_key_id!r}. The audit row would 23503 "
        "the FK to users.id at flush time."
    )
    assert event.actor_user_id is None, (
        f"actor_user_id leaked a value ({event.actor_user_id!r}) "
        "for an api-key actor. The id WILL match the FK shape but "
        "is in the WRONG table — silent mis-attribution."
    )


@pytest.mark.asyncio
async def test_record_with_no_auth_writes_null_actor(patched_webhook_enqueue):
    """System-driven events (cron jobs, workers) — auth=None. BOTH
    actor columns MUST stay NULL. Pin so a regression that defaulted
    to a placeholder UUID can't slip through."""
    from services.audit import record

    org_id = uuid4()
    session = _StubSession()
    event = await record(
        session,  # type: ignore[arg-type]
        organization_id=org_id,
        auth=None,
        action="costpulse.rfq.slots_expired",
        resource_type="rfq_slot",
        resource_id=uuid4(),
    )

    assert event.actor_user_id is None, (
        f"System actor (auth=None) leaked actor_user_id={event.actor_user_id!r}. "
        "Audit log would mis-attribute cron actions to a placeholder user."
    )
    assert event.actor_api_key_id is None, (
        f"System actor (auth=None) leaked actor_api_key_id={event.actor_api_key_id!r}."
    )


# ---------- Default-empty diffs ----------


@pytest.mark.asyncio
async def test_record_defaults_before_and_after_to_empty_dicts(patched_webhook_enqueue):
    """JSONB-NOT-NULL on the columns means a None value 500s the
    INSERT. The function defaults both to `{}` when the caller
    doesn't supply them. A regression that propagated None would
    surface as 500s on every audit-emitting endpoint that didn't
    explicitly pass before/after."""
    from services.audit import record

    org_id = uuid4()
    session = _StubSession()
    event = await record(
        session,  # type: ignore[arg-type]
        organization_id=org_id,
        auth=None,
        action="costpulse.rfq.slots_expired",
        resource_type="rfq_slot",
        resource_id=None,
        # before / after intentionally omitted
    )
    assert event.before == {}, (
        f"audit.record didn't default before to {{}}; got {event.before!r}. "
        "JSONB NOT NULL columns would 500 the INSERT."
    )
    assert event.after == {}, f"audit.record didn't default after to {{}}; got {event.after!r}."


@pytest.mark.asyncio
async def test_record_passes_diffs_through_when_supplied(patched_webhook_enqueue):
    """When the caller supplies `before` / `after`, they go onto the
    row verbatim. Pinning the pass-through guards against a
    regression that re-coerced or sanitised the diffs (would
    silently drop fields the caller intended to log)."""
    from services.audit import record

    org_id = uuid4()
    session = _StubSession()
    event = await record(
        session,  # type: ignore[arg-type]
        organization_id=org_id,
        auth=None,
        action="org.member.role_change",
        resource_type="org_member",
        resource_id=uuid4(),
        before={"role": "member"},
        after={"role": "admin"},
    )

    assert event.before == {"role": "member"}
    assert event.after == {"role": "admin"}


# ---------- Webhook payload pass-through ----------


@pytest.mark.asyncio
async def test_record_forwards_actor_ids_to_webhook_payload(patched_webhook_enqueue):
    """Cross-module pin: the webhook payload MUST carry the same
    actor ids as the audit row. Pin via the captured stub call."""
    from middleware.auth import AuthContext
    from services.audit import record

    api_key_id = uuid4()
    org_id = uuid4()
    api_key_ctx = AuthContext(
        user_id=api_key_id,
        organization_id=org_id,
        role="api_key",
        email="",
        api_key_id=api_key_id,
    )

    session = _StubSession()
    await record(
        session,  # type: ignore[arg-type]
        organization_id=org_id,
        auth=api_key_ctx,
        action="costpulse.boq.import",
        resource_type="boq_import",
        resource_id=None,
    )

    assert len(patched_webhook_enqueue) == 1, (
        f"audit.record didn't enqueue exactly one webhook; got {len(patched_webhook_enqueue)} enqueues."
    )
    payload = patched_webhook_enqueue[0]["payload"]

    assert payload["actor_api_key_id"] == str(api_key_id), (
        f"Webhook payload's actor_api_key_id drifted: {payload['actor_api_key_id']!r}; want {str(api_key_id)!r}."
    )
    assert payload["actor_user_id"] is None
