"""Webhook subscription CRUD + the test-fire endpoint.

Admin-only. The `secret` is shown ONCE at creation and never echoed
back — losing it forces a delete + recreate. That's the standard
pattern for HMAC secrets and matches what GitHub / Stripe / etc. do.

A small `/webhooks/{id}/test` endpoint enqueues a synthetic event so
the customer can verify their receiver works without waiting for a
real action to happen in the platform.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok
from db.deps import get_db
from middleware.auth import AuthContext
from middleware.idempotency_route import IdempotentRoute
from middleware.rbac import Role, require_min_role
from models.webhooks import WebhookDelivery, WebhookSubscription
from schemas.webhooks import (
    WebhookDeliveryOut,
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreated,
    WebhookSubscriptionOut,
    WebhookSubscriptionUpdate,
)
from services.webhooks import (
    DEFAULT_ROTATION_GRACE_SECONDS,
    EVENT_CATALOG,
    enqueue_event,
    generate_secret,
    rotate_secret,
)

# Idempotency on POST/PATCH/DELETE — `/docs/api#idempotency`.
# Two write paths benefit most:
#   * `POST /webhooks` (subscription create) — partner CI retries
#     should NOT register two subscribers receiving duplicate events.
#   * `POST /webhooks/{id}/test` — flaky network on the test-fire
#     should not double-fire test events to the partner's receiver.
# `POST /webhooks/deliveries/{id}/redeliver` is also covered as a
# bonus — operator double-clicks shouldn't enqueue two re-deliveries.
router = APIRouter(
    prefix="/api/v1/webhooks",
    tags=["webhooks"],
    route_class=IdempotentRoute,
)


# ---------- Event catalog (public docs) ----------


@router.get("/event-types")
async def list_event_types():
    """Public catalog of every webhook event type the platform emits,
    each with a human description and a payload sample. Drives the
    `/docs/webhooks/events` partner-docs page.

    Public on purpose — partners evaluating the platform read this
    BEFORE getting an API key. No auth dependency. The data is
    documentation, not tenant-scoped.

    Returned as a sorted list of `{event_type, description,
    payload_sample}` so the frontend can render alphabetically without
    re-sorting in JS. Pinned by the integrator-surface snapshot — a
    revert that drops the route or shrinks the catalog goes red on
    the next commit.
    """
    items = sorted(
        (
            {
                "event_type": event_type,
                "description": meta["description"],
                "payload_sample": meta["payload_sample"],
            }
            for event_type, meta in EVENT_CATALOG.items()
        ),
        key=lambda x: x["event_type"],
    )
    return ok(items)


# ---------- Create ----------


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookSubscriptionCreate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Register a new webhook subscription.

    Returns the generated secret in the response — the only time the
    customer sees it. Idempotent on `(org, url)`: re-posting the same
    URL surfaces a 409 instead of silently rotating the secret.
    """
    secret = generate_secret()
    sub = WebhookSubscription(
        id=uuid4(),
        organization_id=auth.organization_id,
        url=str(payload.url),
        secret=secret,
        event_types=list(payload.event_types),
        enabled=True,
        failure_count=0,
        created_by=auth.user_id,
    )
    db.add(sub)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A webhook for this URL already exists in this org.",
        ) from None
    await db.refresh(sub)
    out = WebhookSubscriptionCreated(
        id=sub.id,
        url=sub.url,
        event_types=list(sub.event_types),
        enabled=sub.enabled,
        last_delivery_at=sub.last_delivery_at,
        failure_count=sub.failure_count,
        created_at=sub.created_at,
        secret=secret,
    )
    return ok(out.model_dump(mode="json"))


# ---------- List ----------


@router.get("")
async def list_webhooks(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Every webhook in the caller's org. Secret is intentionally
    never included — see the module docstring."""
    rows = (
        (
            await db.execute(
                select(WebhookSubscription)
                .where(WebhookSubscription.organization_id == auth.organization_id)
                .order_by(WebhookSubscription.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return ok([WebhookSubscriptionOut.model_validate(r).model_dump(mode="json") for r in rows])


# ---------- Update (toggle / change events) ----------


@router.patch("/{webhook_id}")
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookSubscriptionUpdate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sub = (
        await db.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.id == webhook_id,
                WebhookSubscription.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")
    if payload.enabled is not None:
        sub.enabled = payload.enabled
        # Re-enabling resets the auto-disable counter so the next
        # delivery starts fresh — admin took the action of fixing
        # whatever was wrong.
        if payload.enabled:
            sub.failure_count = 0
    if payload.event_types is not None:
        sub.event_types = list(payload.event_types)
    await db.commit()
    await db.refresh(sub)
    return ok(WebhookSubscriptionOut.model_validate(sub).model_dump(mode="json"))


# ---------- Delete ----------


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sub = (
        await db.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.id == webhook_id,
                WebhookSubscription.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        return None  # idempotent — desired end state achieved
    await db.delete(sub)
    await db.commit()
    return None


# ---------- Secret rotation ----------


@router.post("/{webhook_id}/rotate-secret")
async def rotate_webhook_secret(
    webhook_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Issue a NEW HMAC secret for this webhook, retaining the old one
    for a 24h grace window.

    During the grace, the dispatcher emits TWO signature headers per
    delivery:

      * `X-AEC-Signature` — signed with the new secret.
      * `X-AEC-Signature-Previous` — signed with the old secret.

    Receivers verify whichever matches. This lets the customer roll
    their receiver to the new secret without a flag-day deploy: ship
    the new-secret config, smoke-test, then retire the old. Same shape
    as Stripe's webhook rollover.

    Like creation, the new secret is returned in the response body
    EXACTLY ONCE — there's no "show secret" endpoint. If the customer
    loses it before pasting into their receiver, the path forward is
    another rotation.

    Idempotency contract:
      * `Idempotency-Key` (via `IdempotentRoute`) replays the cached
        202 within the 24h dedup window. Two clicks in quick succession
        with the same key get the SAME new secret rather than burning
        through two rotations.
      * Without the header, two rapid rotations DO produce two new
        secrets — the second discards the first as `secret_previous`.
        Receivers running on the original old secret may stop verifying
        sooner than expected. We document this in the response note.

    Audit: writes `webhooks.subscription.rotate_secret` so admins
    answering "did someone rotate this in the last incident?" have a
    durable record. Secret material is NOT logged (before/after empty).
    """
    new_secret = await rotate_secret(
        db,
        subscription_id=webhook_id,
        organization_id=auth.organization_id,
    )
    if new_secret is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")

    # Audit AFTER the commit inside rotate_secret — a partial write
    # would leave an audit row pointing at a rotation that didn't
    # happen. The audit's own commit is in `db.commit()` below; the
    # rotation is already durable, so a failure here doesn't unwind
    # the secret swap (the customer would still see the new secret
    # in their response). That's the safer asymmetry — losing an
    # audit row is recoverable from app logs; losing the rotation
    # would mean the customer's receiver and our DB diverge.
    from services.audit import record as audit_record

    await audit_record(
        db,
        organization_id=auth.organization_id,
        auth=auth,
        action="webhooks.subscription.rotate_secret",
        resource_type="webhook_subscription",
        resource_id=webhook_id,
        # Empty before/after — secret material is never persisted to
        # the audit log even in hashed form. The row is the timestamp
        # + actor; the durable "secret rotated to ..." artefact is the
        # one-shot HTTP response the admin captures.
        before={},
        after={"grace_seconds": DEFAULT_ROTATION_GRACE_SECONDS},
    )
    await db.commit()

    return ok(
        {
            "id": str(webhook_id),
            "secret": new_secret,
            "grace_seconds": DEFAULT_ROTATION_GRACE_SECONDS,
            "note": (
                "Save this secret immediately — it will not be shown "
                "again. The previous secret keeps verifying for "
                f"{DEFAULT_ROTATION_GRACE_SECONDS // 3600} hours so "
                "receivers can roll forward without downtime."
            ),
        }
    )


# ---------- Test fire ----------


@router.post("/{webhook_id}/test", status_code=status.HTTP_202_ACCEPTED)
async def test_webhook(
    webhook_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Enqueue a synthetic `webhook.test` event so the customer can
    verify their receiver responds correctly. The receiver sees the
    same shape as a real event — there's no special "this is a test"
    flag because that would let attackers spoof real events by
    flipping the flag."""
    sub = (
        await db.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.id == webhook_id,
                WebhookSubscription.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")

    inserted = await enqueue_event(
        db,
        organization_id=auth.organization_id,
        event_type="webhook.test",
        payload={
            "message": "This is a test event from AEC Platform.",
            "actor_user_id": str(auth.user_id),
            "subscription_id": str(sub.id),
        },
    )
    await db.commit()
    return ok({"queued": inserted, "subscription_id": str(sub.id)})


# ---------- Recent deliveries ----------


DeliveryStatus = Literal["pending", "delivered", "failed"]


@router.get("/{webhook_id}/deliveries")
async def list_deliveries(
    webhook_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[DeliveryStatus | None, Query(alias="status")] = None,
    since_days: Annotated[int, Query(ge=1, le=90)] = 7,
    limit: int = 50,
):
    """Recent delivery attempts — debug aid when a customer says
    "your webhook didn't fire." Includes status code + error +
    response snippet.

    Filters:
      * `status` — narrow to one of pending/delivered/failed.
      * `since_days` — only rows from the last N days (default 7).
        Capped at 90 because retention prunes terminal rows at 30d
        anyway; longer windows would always be nearly-empty.
    """
    stmt = (
        select(WebhookDelivery)
        .where(
            WebhookDelivery.subscription_id == webhook_id,
            WebhookDelivery.organization_id == auth.organization_id,
            WebhookDelivery.created_at >= datetime.now(UTC) - timedelta(days=since_days),
        )
        .order_by(WebhookDelivery.created_at.desc())
        .limit(min(limit, 200))
    )
    if status_filter is not None:
        stmt = stmt.where(WebhookDelivery.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    return ok([WebhookDeliveryOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get("/{webhook_id}/deliveries/histogram")
async def deliveries_histogram(
    webhook_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
):
    """Day-bucketed delivery counts by status. Drives the small
    histogram on `/settings/webhooks/[id]` so admins can spot failure
    spikes at a glance.

    Postgres `date_trunc('day', created_at AT TIME ZONE 'UTC')` keeps
    the bucket boundary in the same TZ across daylight savings — the
    UI labels read "today / yesterday / 2 days ago" so absolute time
    isn't shown.
    """
    rows = (
        (
            await db.execute(
                text(
                    f"""
                    SELECT date_trunc('day', created_at AT TIME ZONE 'UTC') AS day,
                           status,
                           COUNT(*) AS count
                    FROM webhook_deliveries
                    WHERE subscription_id = :sub_id
                      AND organization_id = :org_id
                      AND created_at >= NOW() - INTERVAL '{int(days)} days'
                    GROUP BY day, status
                    ORDER BY day ASC
                    """
                ),
                {"sub_id": str(webhook_id), "org_id": str(auth.organization_id)},
            )
        )
        .mappings()
        .all()
    )
    # Pivot into one entry per day with status counts. Frontend renders
    # the bars without further computation.
    by_day: dict[str, dict[str, int]] = {}
    for r in rows:
        key = r["day"].isoformat() if r["day"] else ""
        bucket = by_day.setdefault(key, {"day": key, "delivered": 0, "failed": 0, "pending": 0})
        bucket[r["status"]] = int(r["count"])
    return ok(list(by_day.values()))


@router.get("/deliveries/dead-letter")
async def list_dead_letter(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    since_days: Annotated[int, Query(ge=1, le=90)] = 7,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    """Cross-subscription dead-letter feed (status='failed') for the
    calling org. Pinned by tests/test_integrator_surface_snapshot.py
    — do not remove without updating that test."""
    rows = (
        (
            await db.execute(
                select(WebhookDelivery)
                .where(
                    WebhookDelivery.organization_id == auth.organization_id,
                    WebhookDelivery.status == "failed",
                    WebhookDelivery.created_at >= datetime.now(UTC) - timedelta(days=since_days),
                )
                .order_by(WebhookDelivery.created_at.desc())
                .limit(min(limit, 200))
            )
        )
        .scalars()
        .all()
    )
    return ok([WebhookDeliveryOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/deliveries/{delivery_id}/redeliver", status_code=status.HTTP_202_ACCEPTED)
async def redeliver(
    delivery_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Re-enqueue a delivery — usually called on a `failed` row that
    the customer's receiver was down for. We don't mutate the original
    row (it's audit history); we INSERT a fresh delivery with the same
    payload + a new `id` (which doubles as the idempotency key on the
    receiver side).

    Why a new row instead of resetting the old one's status:
      * Retention semantics stay simple — the original failed row ages
        out at 30d; the redelivery is a separate row with its own clock.
      * Audit history shows BOTH attempts, not just the latest.
      * The receiver's idempotency key is `id`. Resetting status would
        keep the same id and the receiver might 200 on the dup without
        actually processing it — a redeliver wouldn't actually deliver.
    """
    src = (
        await db.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.id == delivery_id,
                WebhookDelivery.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "delivery_not_found")

    new_id = uuid4()
    await db.execute(
        text(
            """
            INSERT INTO webhook_deliveries (
                id, subscription_id, organization_id, event_type, payload,
                status, attempt_count, next_retry_at
            ) VALUES (
                :id, :sub_id, :org_id, :event_type, CAST(:payload AS JSONB),
                'pending', 0, NOW()
            )
            """
        ),
        {
            "id": str(new_id),
            "sub_id": str(src.subscription_id),
            "org_id": str(auth.organization_id),
            "event_type": src.event_type,
            "payload": _json_dumps(src.payload),
        },
    )
    await db.commit()
    return ok({"id": str(new_id), "subscription_id": str(src.subscription_id)})


def _json_dumps(v: object) -> str:
    """JSONB binding helper — same shape as services/imports uses for
    `CAST(:x AS JSONB)`. Inlined here so the router doesn't have to
    pull from services for one line."""
    import json

    return json.dumps(v, default=str)
