"""Webhook subscription CRUD + the test-fire endpoint.

Admin-only. The `secret` is shown ONCE at creation and never echoed
back — losing it forces a delete + recreate. That's the standard
pattern for HMAC secrets and matches what GitHub / Stripe / etc. do.

A small `/webhooks/{id}/test` endpoint enqueues a synthetic event so
the customer can verify their receiver works without waiting for a
real action to happen in the platform.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok
from db.deps import get_db
from middleware.auth import AuthContext
from middleware.rbac import Role, require_min_role
from models.webhooks import WebhookDelivery, WebhookSubscription
from schemas.webhooks import (
    WebhookDeliveryOut,
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreated,
    WebhookSubscriptionOut,
    WebhookSubscriptionUpdate,
)
from services.webhooks import enqueue_event, generate_secret


router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


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
    return ok(
        [WebhookSubscriptionOut.model_validate(r).model_dump(mode="json") for r in rows]
    )


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


@router.get("/{webhook_id}/deliveries")
async def list_deliveries(
    webhook_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
):
    """Recent delivery attempts — debug aid when a customer says
    "your webhook didn't fire." Includes status code + error +
    response snippet."""
    rows = (
        (
            await db.execute(
                select(WebhookDelivery)
                .where(
                    WebhookDelivery.subscription_id == webhook_id,
                    WebhookDelivery.organization_id == auth.organization_id,
                )
                .order_by(WebhookDelivery.created_at.desc())
                .limit(min(limit, 200))
            )
        )
        .scalars()
        .all()
    )
    return ok(
        [WebhookDeliveryOut.model_validate(r).model_dump(mode="json") for r in rows]
    )
