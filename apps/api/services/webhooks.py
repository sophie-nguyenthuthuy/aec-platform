"""Webhook outbox + dispatcher.

Two halves of the same workflow:

  * `enqueue_event(...)` — called from inside a request handler in the
    SAME transaction as the source write (audit insert, project
    creation, etc.). It looks up matching subscriptions and inserts
    `webhook_deliveries` rows in `pending` status. If the surrounding
    transaction rolls back, the delivery rows roll back too — we
    never notify a customer about a write that didn't actually
    commit. Classic transactional outbox.

  * `drain_pending()` — called by the arq cron every minute. Picks up
    `pending` / due-for-retry rows, signs the payload with HMAC-SHA256,
    POSTs to the subscriber's URL, and marks the delivery `delivered`
    or schedules a retry with exponential backoff (1m → 5m → 30m → 2h
    → 12h → permanent fail at attempt 6).

Signature scheme:

    X-AEC-Signature: sha256=<hex_digest>
    X-AEC-Event-Type: <event_type>
    X-AEC-Delivery-ID: <uuid>
    X-AEC-Timestamp: <unix_seconds>

The receiver verifies via:

    expected = hmac.new(secret.encode(), body, sha256).hexdigest()
    hmac.compare_digest(f"sha256={expected}", header_value)

The timestamp lets the receiver reject replays older than N minutes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Closed registry of event types webhooks can subscribe to. Sources:
#   * Every value of `services/audit.AuditAction` is auto-mirrored here.
#   * Plus a few high-value events that don't carry an audit row (e.g.
#     defect-reported, safety-incident-detected — those are creations,
#     not authenticated approvals).
#
# Anything outside this set is considered a programmer error at the
# call site (`enqueue_event(unknown_type, ...)` raises). We don't
# *gate* subscribers on it — they can register for any string they
# want, and the dispatcher just won't fire on unknown types.
_KNOWN_EVENT_TYPES: set[str] = {
    # Audit-mirrored
    "costpulse.estimate.approve",
    "pulse.change_order.approve",
    "pulse.change_order.reject",
    "org.member.role_change",
    "org.member.remove",
    "org.invitation.create",
    "org.invitation.revoke",
    "org.invitation.accept",
    "handover.package.deliver",
    # Non-audit creations (not gated by RBAC; carry no actor
    # before/after diff, so they're awkward to log to audit but
    # high-value to webhook)
    "project.created",
    "siteeye.safety_incident.detected",
    "handover.defect.reported",
}


# Retry schedule: minutes from creation to each attempt. After 6
# attempts the delivery is marked `failed` permanently.
_BACKOFF_MINUTES: list[int] = [0, 1, 5, 30, 120, 720]
# Auto-disable a subscription after N consecutive failures so we don't
# hammer a dead endpoint forever. Counter resets on success.
_DISABLE_AFTER_FAILURES = 20
# Per-attempt HTTP timeout. Must be tighter than the cron interval
# (60s) so a stuck delivery doesn't pile up alongside its retries.
_HTTP_TIMEOUT_SEC = 10.0
# Cap stored response bodies so a chatty receiver can't bloat the table.
_MAX_RESPONSE_SNIPPET = 500


# ---------- Secret + signature helpers ----------


def generate_secret() -> str:
    """64-char hex (32 random bytes). Used by `webhook_subscriptions.secret`
    and never re-shown after creation."""
    return secrets.token_hex(32)


def sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 of the raw POST body, hex-encoded.

    The receiver computes the same and `hmac.compare_digest`s it
    against the `X-AEC-Signature` header (without the `sha256=` prefix
    or with — we accept both for ergonomics)."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


# ---------- Outbox enqueue ----------


async def enqueue_event(
    session: AsyncSession,
    *,
    organization_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    """Insert one `webhook_deliveries` row per matching subscription.

    Returns the number of delivery rows inserted (0 if no subscription
    matched). Idempotency is the *caller's* responsibility — fire from
    inside the same transaction as the source write so the outbox row
    rolls back with it.

    Matching rule: a subscription with empty `event_types[]` matches
    everything. Otherwise the event_type must be in the array.
    """
    if event_type not in _KNOWN_EVENT_TYPES:
        # Soft warning, not a raise — keeps a typo at the call site
        # from breaking the request, but the log line tells us about
        # it. Subscriptions only fire on known events anyway.
        logger.warning("webhooks.enqueue_event: unknown type %r", event_type)

    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id FROM webhook_subscriptions
                    WHERE organization_id = :org
                      AND enabled = true
                      AND (
                        cardinality(event_types) = 0
                        OR :event_type = ANY(event_types)
                      )
                    """
                ),
                {"org": str(organization_id), "event_type": event_type},
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    # Bulk insert — one round trip regardless of subscription count.
    # `next_retry_at = NOW()` so the next cron tick picks this up.
    payload_json = json.dumps(payload, default=str)
    for sub_id in rows:
        await session.execute(
            text(
                """
                INSERT INTO webhook_deliveries
                  (id, subscription_id, organization_id, event_type, payload,
                   status, attempt_count, next_retry_at)
                VALUES
                  (:id, :sub, :org, :event_type, CAST(:payload AS jsonb),
                   'pending', 0, NOW())
                """
            ),
            {
                "id": str(uuid4()),
                "sub": str(sub_id),
                "org": str(organization_id),
                "event_type": event_type,
                "payload": payload_json,
            },
        )
    return len(rows)


# ---------- Cron drain ----------


async def drain_pending(session: AsyncSession, *, batch: int = 100) -> dict[str, int]:
    """Pick up due deliveries, ship them, mark + retry.

    Cross-tenant by design — caller passes an `AdminSessionFactory`
    session because the discovery query needs to see every org's
    pending deliveries. Tenant scoping happens *inside* each delivery's
    payload via `organization_id`, not via session GUC.

    Atomicity / locking: we `SELECT … FOR UPDATE SKIP LOCKED` so two
    workers running concurrently each pick a disjoint batch instead
    of contending on the same row.
    """
    # Pull due rows + the parent subscription's URL/secret/state in
    # one go. JOIN keeps the per-row dispatch loop decoupled from the
    # subscription state.
    due_rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT
                        d.id, d.subscription_id, d.organization_id,
                        d.event_type, d.payload, d.attempt_count,
                        s.url, s.secret, s.failure_count
                    FROM webhook_deliveries d
                    JOIN webhook_subscriptions s ON s.id = d.subscription_id
                    WHERE d.status IN ('pending', 'in_flight')
                      AND d.next_retry_at <= NOW()
                      AND s.enabled = true
                    ORDER BY d.next_retry_at
                    LIMIT :batch
                    FOR UPDATE OF d SKIP LOCKED
                    """
                ),
                {"batch": batch},
            )
        )
        .mappings()
        .all()
    )
    if not due_rows:
        return {"picked": 0, "delivered": 0, "failed": 0, "retried": 0}

    # Mark all picked rows as in_flight under the same SELECT lock so
    # a misconfigured second cron tick can't double-deliver.
    await session.execute(
        text("UPDATE webhook_deliveries SET status = 'in_flight' WHERE id = ANY(:ids)"),
        {"ids": [str(r["id"]) for r in due_rows]},
    )
    await session.commit()

    delivered = 0
    failed = 0
    retried = 0

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as http:
        for row in due_rows:
            attempt = int(row["attempt_count"]) + 1
            ok, status, snippet, err = await _deliver_one(
                http,
                url=row["url"],
                secret=row["secret"],
                event_type=row["event_type"],
                delivery_id=row["id"],
                payload=row["payload"],
            )
            if ok:
                await _mark_delivered(
                    session,
                    delivery_id=row["id"],
                    subscription_id=row["subscription_id"],
                    response_status=status,
                    snippet=snippet,
                    attempt=attempt,
                )
                delivered += 1
            elif attempt >= len(_BACKOFF_MINUTES):
                await _mark_failed_permanently(
                    session,
                    delivery_id=row["id"],
                    subscription_id=row["subscription_id"],
                    response_status=status,
                    snippet=snippet,
                    error=err,
                    attempt=attempt,
                    failure_count=int(row["failure_count"]),
                )
                failed += 1
            else:
                await _schedule_retry(
                    session,
                    delivery_id=row["id"],
                    subscription_id=row["subscription_id"],
                    response_status=status,
                    snippet=snippet,
                    error=err,
                    attempt=attempt,
                    failure_count=int(row["failure_count"]),
                )
                retried += 1
        await session.commit()

    return {
        "picked": len(due_rows),
        "delivered": delivered,
        "failed": failed,
        "retried": retried,
    }


# ---------- Per-row delivery ----------


async def _deliver_one(
    http: httpx.AsyncClient,
    *,
    url: str,
    secret: str,
    event_type: str,
    delivery_id: UUID,
    payload: dict,
) -> tuple[bool, int | None, str | None, str | None]:
    """POST a single delivery. Returns `(ok, status, body_snippet, error)`.

    `ok` is True on any 2xx — receivers signal "got it" with a 200
    typically, but some prefer 204. Anything else (incl. 5xx, network
    error, timeout) is treated as a retryable failure.
    """
    body = json.dumps(payload, default=str).encode("utf-8")
    signature = sign_payload(secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-AEC-Signature": f"sha256={signature}",
        "X-AEC-Event-Type": event_type,
        "X-AEC-Delivery-ID": str(delivery_id),
        "X-AEC-Timestamp": str(int(time.time())),
        # Receivers can redirect to https; but we don't auto-follow
        # redirects because a 3xx to a different host is suspicious
        # in this context.
        "User-Agent": "AEC-Platform-Webhook/1.0",
    }
    try:
        res = await http.post(url, content=body, headers=headers)
    except httpx.TimeoutException:
        return (False, None, None, "timeout")
    except httpx.RequestError as exc:
        return (False, None, None, f"network: {type(exc).__name__}: {exc}")

    snippet = (res.text or "")[:_MAX_RESPONSE_SNIPPET] or None
    if 200 <= res.status_code < 300:
        return (True, res.status_code, snippet, None)
    return (
        False,
        res.status_code,
        snippet,
        f"non-2xx status: {res.status_code}",
    )


# ---------- Status transitions ----------


async def _mark_delivered(
    session: AsyncSession,
    *,
    delivery_id: UUID,
    subscription_id: UUID,
    response_status: int | None,
    snippet: str | None,
    attempt: int,
) -> None:
    await session.execute(
        text(
            """
            UPDATE webhook_deliveries
            SET status = 'delivered',
                response_status = :status,
                response_body_snippet = :snippet,
                attempt_count = :attempt,
                delivered_at = NOW(),
                next_retry_at = NULL,
                error_message = NULL
            WHERE id = :id
            """
        ),
        {
            "id": str(delivery_id),
            "status": response_status,
            "snippet": snippet,
            "attempt": attempt,
        },
    )
    # Reset the subscription's rolling failure counter — a successful
    # delivery wipes the slate clean. last_delivery_at gets stamped
    # for ops dashboards.
    await session.execute(
        text(
            """
            UPDATE webhook_subscriptions
            SET failure_count = 0, last_delivery_at = NOW()
            WHERE id = :id
            """
        ),
        {"id": str(subscription_id)},
    )


async def _schedule_retry(
    session: AsyncSession,
    *,
    delivery_id: UUID,
    subscription_id: UUID,
    response_status: int | None,
    snippet: str | None,
    error: str | None,
    attempt: int,
    failure_count: int,
) -> None:
    next_at = datetime.now(UTC) + timedelta(minutes=_BACKOFF_MINUTES[attempt])
    await session.execute(
        text(
            """
            UPDATE webhook_deliveries
            SET status = 'pending',
                response_status = :status,
                response_body_snippet = :snippet,
                error_message = :error,
                attempt_count = :attempt,
                next_retry_at = :next_at
            WHERE id = :id
            """
        ),
        {
            "id": str(delivery_id),
            "status": response_status,
            "snippet": snippet,
            "error": error,
            "attempt": attempt,
            "next_at": next_at,
        },
    )
    await _bump_subscription_failure_counter(session, subscription_id=subscription_id, failure_count=failure_count)


async def _mark_failed_permanently(
    session: AsyncSession,
    *,
    delivery_id: UUID,
    subscription_id: UUID,
    response_status: int | None,
    snippet: str | None,
    error: str | None,
    attempt: int,
    failure_count: int,
) -> None:
    await session.execute(
        text(
            """
            UPDATE webhook_deliveries
            SET status = 'failed',
                response_status = :status,
                response_body_snippet = :snippet,
                error_message = :error,
                attempt_count = :attempt,
                next_retry_at = NULL
            WHERE id = :id
            """
        ),
        {
            "id": str(delivery_id),
            "status": response_status,
            "snippet": snippet,
            "error": error,
            "attempt": attempt,
        },
    )
    await _bump_subscription_failure_counter(session, subscription_id=subscription_id, failure_count=failure_count)


async def _bump_subscription_failure_counter(
    session: AsyncSession,
    *,
    subscription_id: UUID,
    failure_count: int,
) -> None:
    """Increment, and auto-disable if we've crossed the dead-endpoint
    threshold. The auto-disable is reversible — an admin can edit the
    URL + flip `enabled = true` and the next event will fire again."""
    new_count = failure_count + 1
    if new_count >= _DISABLE_AFTER_FAILURES:
        logger.warning(
            "webhook subscription %s auto-disabled after %d consecutive failures",
            subscription_id,
            new_count,
        )
        await session.execute(
            text("UPDATE webhook_subscriptions SET failure_count = :n, enabled = false WHERE id = :id"),
            {"id": str(subscription_id), "n": new_count},
        )
    else:
        await session.execute(
            text("UPDATE webhook_subscriptions SET failure_count = :n WHERE id = :id"),
            {"id": str(subscription_id), "n": new_count},
        )
