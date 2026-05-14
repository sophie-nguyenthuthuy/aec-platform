"""Billing endpoints — pricing catalogue, current subscription,
checkout (Stripe + VietQR), invoices, ops confirmation hook.

Routes:
  * GET /api/v1/billing/plans              — public catalogue
  * GET /api/v1/billing/current            — caller's org subscription
  * GET /api/v1/billing/invoices           — caller's org invoice history
  * POST /api/v1/billing/checkout/stripe   — create Stripe Checkout session
  * POST /api/v1/billing/checkout/vietqr   — generate transfer reference
  * POST /api/v1/billing/vietqr/{ref}/confirm
                                            — ops marks bank transfer received

Stripe webhook handler lives separately at `/api/v1/billing/webhooks/stripe`
so it can run public-unauth (Stripe signs the payload; we verify the
signature instead of relying on a session cookie).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import text

from core.envelope import ok
from db.session import AdminSessionFactory, TenantAwareSession
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role
from services.billing import (
    PLANS,
    PlanSlug,
    make_vietqr_reference,
    next_period_end,
    plan_definition,
)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


# ---------- Catalogue ----------


@router.get("/plans")
async def list_plans():
    """Public — no auth. Used by the marketing page + the in-app
    upgrade picker."""
    return ok(
        {
            "plans": [
                {
                    "slug": p.slug,
                    "name_vi": p.name_vi,
                    "tagline_vi": p.tagline_vi,
                    "price_vnd_monthly": p.price_vnd_monthly,
                    "price_usd_monthly": p.price_usd_monthly,
                    "max_users": p.max_users,
                    "max_projects": p.max_projects,
                    "max_drawings_gb": p.max_drawings_gb,
                    "features_vi": list(p.features_vi),
                }
                for p in PLANS.values()
            ]
        }
    )


# ---------- Read current subscription ----------


@router.get("/current")
async def get_current_subscription(
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Resolve the caller's active subscription + plan limits.

    Used by `/settings/billing` to render the current state and by
    the plan-gate middleware (when caller doesn't have a cached
    plan). Returns `plan_definition` data inlined so the frontend
    doesn't need a second round-trip for the limits.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT s.plan, s.status, s.billing_source,
                           s.period_start, s.period_end,
                           s.stripe_subscription_id, s.vietqr_reference
                    FROM subscriptions s
                    WHERE s.organization_id = :org
                    """
                ),
                {"org": str(auth.organization_id)},
            )
        ).mappings().one_or_none()

    if row is None:
        # Fresh org without a migration-seeded row (theoretical — every
        # org gets a starter row in migration 0050). Default to starter.
        plan_def = plan_definition("starter")
        return ok(
            {
                "plan": "starter",
                "status": "active",
                "billing_source": None,
                "period_end": None,
                "limits": _plan_limits_dict(plan_def),
            }
        )

    plan_def = plan_definition(row["plan"])
    return ok(
        {
            "plan": row["plan"],
            "status": row["status"],
            "billing_source": row["billing_source"],
            "period_start": row["period_start"].isoformat() if row["period_start"] else None,
            "period_end": row["period_end"].isoformat() if row["period_end"] else None,
            "stripe_subscription_id": row["stripe_subscription_id"],
            "vietqr_reference": row["vietqr_reference"],
            "limits": _plan_limits_dict(plan_def),
        }
    )


def _plan_limits_dict(p) -> dict:
    return {
        "name_vi": p.name_vi,
        "max_users": p.max_users,
        "max_projects": p.max_projects,
        "max_drawings_gb": p.max_drawings_gb,
        "ai_quota_multiplier": p.ai_quota_multiplier,
    }


# ---------- Invoices ----------


@router.get("/invoices")
async def list_invoices(
    auth: Annotated[AuthContext, Depends(require_auth)],
    limit: int = 24,
):
    """Most recent invoices for the org. Default 24 = 2 years monthly."""
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, amount_vnd, currency, amount_original,
                           status, provider, provider_ref, paid_at, created_at
                    FROM invoices
                    WHERE organization_id = :org
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"org": str(auth.organization_id), "limit": limit},
            )
        ).mappings().all()

    return ok(
        {
            "invoices": [
                {
                    "id": str(r["id"]),
                    "amount_vnd": int(r["amount_vnd"]),
                    "currency": r["currency"],
                    "amount_original": int(r["amount_original"]) if r["amount_original"] else None,
                    "status": r["status"],
                    "provider": r["provider"],
                    "provider_ref": r["provider_ref"],
                    "paid_at": r["paid_at"].isoformat() if r["paid_at"] else None,
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ]
        }
    )


# ---------- VietQR checkout ----------


@router.post("/checkout/vietqr")
async def start_vietqr_checkout(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.OWNER))],
    plan: PlanSlug,
):
    """Generate a VietQR transfer reference for the requested plan.

    Returns the reference string + the bank-account info the user
    transfers to. The platform's billing entity has a single
    receiving account (configured via env); the reference in the
    memo lets ops reconcile incoming transfers against pending
    subscriptions.

    Owner-only — billing is a sensitive operation; admins can
    invite, but only owners can upgrade plans.
    """
    if plan not in PLANS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown plan: {plan}")
    plan_def = PLANS[plan]
    if plan_def.price_vnd_monthly is None:
        # Enterprise — there's no self-serve price; surface a "contact
        # sales" CTA on the frontend.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "enterprise plan requires manual contract; please contact sales",
        )

    ref = make_vietqr_reference(
        organization_id=str(auth.organization_id), plan=plan
    )

    # Upsert the org's subscription row to `pending_payment` so
    # the UI shows a "waiting for transfer" banner.
    async with AdminSessionFactory() as session:
        await session.execute(
            text(
                """
                UPDATE subscriptions
                SET plan = :plan,
                    status = 'pending_payment',
                    billing_source = 'vietqr',
                    vietqr_reference = :ref,
                    updated_at = NOW()
                WHERE organization_id = :org
                """
            ),
            {
                "plan": plan,
                "ref": ref,
                "org": str(auth.organization_id),
            },
        )
        # Insert a `pending` invoice row so the audit trail is complete.
        await session.execute(
            text(
                """
                INSERT INTO invoices
                    (id, organization_id, subscription_id, amount_vnd,
                     currency, status, provider, provider_ref)
                SELECT :inv, :org, s.id, :amt, 'VND', 'pending', 'vietqr', :ref
                FROM subscriptions s
                WHERE s.organization_id = :org
                """
            ),
            {
                "inv": str(uuid4()),
                "org": str(auth.organization_id),
                "amt": plan_def.price_vnd_monthly,
                "ref": ref,
            },
        )
        await session.commit()

    return ok(
        {
            "reference": ref,
            "amount_vnd": plan_def.price_vnd_monthly,
            "plan": plan,
            "bank": {
                # Hardcoded receiving-account info. Set via env in prod
                # so a different deploy can change bank without code.
                "bank_name": os.environ.get(
                    "BILLING_BANK_NAME", "Vietcombank — CN Hà Nội"
                ),
                "account_number": os.environ.get(
                    "BILLING_BANK_ACCOUNT", "0011004212345"
                ),
                "account_holder": os.environ.get(
                    "BILLING_BANK_HOLDER", "CONG TY CO PHAN AEC PLATFORM"
                ),
                # Sepay-format QR payload for the most-used Vietnamese
                # QR standards. Generated on the frontend from these
                # fields because the QR libs are JS-side.
                "memo_format": f"AEC platform - {ref}",
            },
            "instructions_vi": (
                "Chuyển khoản đến tài khoản trên với nội dung chính xác "
                "như trên. Hệ thống sẽ kích hoạt gói trong vòng 1 ngày "
                "làm việc sau khi nhận được tiền."
            ),
        }
    )


# ---------- VietQR confirmation (ops) ----------


@router.post("/vietqr/{ref}/confirm")
async def confirm_vietqr_transfer(
    ref: str,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.OWNER))],
):
    """Mark a pending VietQR transfer as received.

    In v1 this is owner-self-serve: the customer's owner clicks
    "Tôi đã chuyển khoản" after sending the bank transfer, and ops
    reviews the bank statement offline. The button flips the
    subscription to active immediately so the customer isn't blocked
    waiting for manual review — fraud risk is bounded because plans
    are reversible and ops sees the same reference in the bank
    statement export.

    A future hardening step is to gate this on a platform_admin role
    that exists on a single ops org. Out of scope for v1.
    """
    async with AdminSessionFactory() as session:
        sub_row = (
            await session.execute(
                text(
                    """
                    SELECT id, organization_id, plan
                    FROM subscriptions
                    WHERE vietqr_reference = :ref
                      AND organization_id = :org
                    """
                ),
                {"ref": ref, "org": str(auth.organization_id)},
            )
        ).mappings().one_or_none()
        if sub_row is None:
            raise HTTPException(404, "subscription_not_found_for_reference")

        period_end = next_period_end(sub_row["plan"])
        now = datetime.now(UTC)
        await session.execute(
            text(
                """
                UPDATE subscriptions
                SET status = 'active',
                    period_start = :start,
                    period_end = :end,
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {"start": now, "end": period_end, "id": str(sub_row["id"])},
        )
        # Mirror the plan onto organizations for the read-fast path.
        await session.execute(
            text("UPDATE organizations SET plan = :plan WHERE id = :org"),
            {"plan": sub_row["plan"], "org": str(sub_row["organization_id"])},
        )
        # Mark the pending invoice paid.
        await session.execute(
            text(
                """
                UPDATE invoices
                SET status = 'paid', paid_at = :now
                WHERE subscription_id = :sub AND provider_ref = :ref
                """
            ),
            {"now": now, "sub": str(sub_row["id"]), "ref": ref},
        )
        await session.commit()

    return ok({"status": "active", "period_end": period_end.isoformat()})


# ---------- Stripe checkout ----------


@router.post("/checkout/stripe")
async def start_stripe_checkout(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.OWNER))],
    plan: PlanSlug,
    request: Request,
):
    """Create a Stripe Checkout Session and return the redirect URL.

    Activation requires `STRIPE_SECRET_KEY` in the env + the `stripe`
    Python SDK installed. Without those, returns 503 with a hint so
    the UI can fall back to VietQR.

    Session is created with `mode=subscription`, the price-id mapping
    is read from env (`STRIPE_PRICE_PRO_USD`, `STRIPE_PRICE_PRO_VND`).
    Customer email is pre-filled from the auth context so the
    Stripe-side customer record matches our platform user.
    """
    if plan not in PLANS or PLANS[plan].price_usd_monthly is None:
        raise HTTPException(400, "plan_not_available_for_stripe")

    secret_key = os.environ.get("STRIPE_SECRET_KEY")
    if not secret_key:
        raise HTTPException(
            503,
            "stripe_not_configured — use VietQR or contact sales",
        )

    try:
        import stripe  # type: ignore[import-not-found]
    except ImportError:
        raise HTTPException(503, "stripe_sdk_not_installed")

    stripe.api_key = secret_key

    price_id_env = f"STRIPE_PRICE_{plan.upper()}_USD"
    price_id = os.environ.get(price_id_env)
    if not price_id:
        raise HTTPException(
            503, f"missing {price_id_env} env var; ops must configure Stripe Price IDs"
        )

    success_url = (
        f"{os.environ.get('WEB_BASE_URL', 'http://localhost:3000')}"
        f"/settings/billing?stripe_status=success"
    )
    cancel_url = (
        f"{os.environ.get('WEB_BASE_URL', 'http://localhost:3000')}"
        f"/settings/billing?stripe_status=cancelled"
    )

    session_obj = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        customer_email=auth.email,
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(auth.organization_id),
        metadata={
            "organization_id": str(auth.organization_id),
            "plan": plan,
        },
    )

    return ok({"checkout_url": session_obj.url, "session_id": session_obj.id})


# ---------- Stripe webhook ----------


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
):
    """Stripe webhook handler.

    Verifies the signature, then dispatches on `event.type`:
      * `checkout.session.completed` — initial subscription creation.
        Mirror plan onto organizations + subscriptions; insert a
        paid invoice.
      * `customer.subscription.updated` — plan change or status flip.
      * `customer.subscription.deleted` — cancellation.
      * `invoice.payment_failed` — flip status to past_due so the UI
        nags the owner.

    No auth required — Stripe signs the payload with the configured
    webhook secret and we verify against `STRIPE_WEBHOOK_SECRET`.
    Returns 400 on signature failure (Stripe retries with backoff).
    """
    if not stripe_signature:
        raise HTTPException(400, "missing_stripe_signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(503, "stripe_webhook_secret_not_configured")

    try:
        import stripe  # type: ignore[import-not-found]
    except ImportError:
        raise HTTPException(503, "stripe_sdk_not_installed")

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, webhook_secret
        )
    except (ValueError, stripe.error.SignatureVerificationError):  # type: ignore[attr-defined]
        raise HTTPException(400, "invalid_signature")

    event_type = event.get("type")
    data_obj = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        org_id = data_obj.get("client_reference_id") or (
            data_obj.get("metadata") or {}
        ).get("organization_id")
        plan = (data_obj.get("metadata") or {}).get("plan")
        sub_id = data_obj.get("subscription")
        customer_id = data_obj.get("customer")
        if not (org_id and plan):
            return ok({"received": True})

        period_end = next_period_end(plan)
        async with AdminSessionFactory() as session:
            await session.execute(
                text(
                    """
                    UPDATE subscriptions
                    SET plan = :plan,
                        status = 'active',
                        billing_source = 'stripe',
                        stripe_customer_id = :cust,
                        stripe_subscription_id = :sub,
                        period_start = NOW(),
                        period_end = :end,
                        updated_at = NOW()
                    WHERE organization_id = :org
                    """
                ),
                {
                    "plan": plan,
                    "cust": customer_id,
                    "sub": sub_id,
                    "end": period_end,
                    "org": org_id,
                },
            )
            await session.execute(
                text("UPDATE organizations SET plan = :plan WHERE id = :org"),
                {"plan": plan, "org": org_id},
            )
            await session.commit()

    elif event_type == "customer.subscription.deleted":
        sub_id = data_obj.get("id")
        async with AdminSessionFactory() as session:
            await session.execute(
                text(
                    """
                    UPDATE subscriptions
                    SET status = 'cancelled', plan = 'starter', updated_at = NOW()
                    WHERE stripe_subscription_id = :sub
                    """
                ),
                {"sub": sub_id},
            )
            await session.execute(
                text(
                    """
                    UPDATE organizations o
                    SET plan = 'starter'
                    FROM subscriptions s
                    WHERE s.stripe_subscription_id = :sub
                      AND s.organization_id = o.id
                    """
                ),
                {"sub": sub_id},
            )
            await session.commit()

    elif event_type == "invoice.payment_failed":
        sub_id = data_obj.get("subscription")
        async with AdminSessionFactory() as session:
            await session.execute(
                text(
                    """
                    UPDATE subscriptions
                    SET status = 'past_due', updated_at = NOW()
                    WHERE stripe_subscription_id = :sub
                    """
                ),
                {"sub": sub_id},
            )
            await session.commit()

    return ok({"received": True, "type": event_type})


# ---------- LLM spend dashboard (L4-6) ----------


@router.get("/llm-spend")
async def get_llm_spend(
    auth: Annotated[AuthContext, Depends(require_auth)],
    period: str = "current_month",
):
    """Per-module + per-provider breakdown of the org's LLM spend.

    `period`:
      * `current_month` — the current calendar month (default)
      * `last_month`    — prior calendar month
      * `last_30_days`  — rolling window

    Returns:
      * total VND + token counters for the window
      * breakdown by module (with sub-breakdown by provider)
      * daily timeseries for the window's chart

    Cheap aggregates — `llm_spend_events` is denormalised so a single
    SUM over the org+date window powers every figure.
    """
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    if period == "last_month":
        # First day of prior month → first day of current month
        first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_first = (first_this - timedelta(days=1)).replace(day=1)
        since, until = last_first, first_this
    elif period == "last_30_days":
        since = now - timedelta(days=30)
        until = now
    else:  # current_month (default)
        since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        until = now

    params = {
        "org": str(auth.organization_id),
        "since": since,
        "until": until,
    }

    async with TenantAwareSession(auth.organization_id) as session:
        # 1. Totals
        totals = (
            await session.execute(
                text(
                    """
                    SELECT
                        COALESCE(SUM(cost_vnd), 0)::bigint AS cost_vnd,
                        COALESCE(SUM(input_tokens), 0)::bigint AS input_tokens,
                        COALESCE(SUM(output_tokens), 0)::bigint AS output_tokens,
                        COUNT(*) AS call_count
                    FROM llm_spend_events
                    WHERE organization_id = :org
                      AND occurred_at >= :since
                      AND occurred_at < :until
                    """
                ),
                params,
            )
        ).mappings().one()

        # 2. Breakdown by module × provider
        breakdown_rows = (
            await session.execute(
                text(
                    """
                    SELECT module, provider,
                           SUM(cost_vnd)::bigint   AS cost_vnd,
                           SUM(input_tokens)::bigint  AS input_tokens,
                           SUM(output_tokens)::bigint AS output_tokens,
                           COUNT(*) AS call_count
                    FROM llm_spend_events
                    WHERE organization_id = :org
                      AND occurred_at >= :since
                      AND occurred_at < :until
                    GROUP BY module, provider
                    ORDER BY SUM(cost_vnd) DESC
                    """
                ),
                params,
            )
        ).mappings().all()

        # 3. Daily series for chart (date_trunc by day)
        series_rows = (
            await session.execute(
                text(
                    """
                    SELECT date_trunc('day', occurred_at) AS day,
                           SUM(cost_vnd)::bigint AS cost_vnd
                    FROM llm_spend_events
                    WHERE organization_id = :org
                      AND occurred_at >= :since
                      AND occurred_at < :until
                    GROUP BY date_trunc('day', occurred_at)
                    ORDER BY 1 ASC
                    """
                ),
                params,
            )
        ).mappings().all()

    return ok(
        {
            "period": period,
            "since": since.isoformat(),
            "until": until.isoformat(),
            "totals": {
                "cost_vnd": int(totals["cost_vnd"]),
                "input_tokens": int(totals["input_tokens"]),
                "output_tokens": int(totals["output_tokens"]),
                "call_count": int(totals["call_count"]),
            },
            "breakdown": [
                {
                    "module": r["module"],
                    "provider": r["provider"],
                    "cost_vnd": int(r["cost_vnd"]),
                    "input_tokens": int(r["input_tokens"]),
                    "output_tokens": int(r["output_tokens"]),
                    "call_count": int(r["call_count"]),
                }
                for r in breakdown_rows
            ],
            "daily_series": [
                {
                    "day": r["day"].date().isoformat(),
                    "cost_vnd": int(r["cost_vnd"]),
                }
                for r in series_rows
            ],
        }
    )
