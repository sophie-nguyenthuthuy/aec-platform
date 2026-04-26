"""No-auth public endpoints for the supplier RFQ-response portal.

Two endpoints, both keyed by a token in the `?t=` query string:

  * `GET  /api/v1/public/rfq/context` — fetch what the supplier sees
    on the response page (project / estimate / BOQ digest, deadline,
    whether they've already responded).
  * `POST /api/v1/public/rfq/respond` — submit a quote.

The token is the only authn — no Bearer header, no `X-Org-ID`. The
endpoints are mounted at `/api/v1/public/...` to make it obvious in
logs and middleware which routes intentionally bypass `require_auth`.

Cross-tenancy: a token is bound to a specific `(rfq_id, supplier_id)`,
so reads/writes use `AdminSessionFactory` (BYPASSRLS). The token's
audience claim (`rfq_response`) plus the tight write surface (only
mutating one slot inside `rfqs.responses[]`) keeps this safe.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from core.envelope import ok
from db.session import AdminSessionFactory
from models.core import Organization, Project
from models.costpulse import BoqItem, Estimate, Rfq, Supplier
from schemas.public_rfq import (
    PublicBoqLine,
    PublicRfqContext,
    PublicRfqQuote,
)
from services.rate_limit import check_and_consume
from services.rfq_tokens import RfqTokenClaims, TokenError, verify_response_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/public/rfq", tags=["public-rfq"])


_MAX_BOQ_DIGEST_LINES = 20

# Per-token rate limits. Numbers picked for a real supplier reload-loop:
# a sane email client / browser refresh shouldn't exceed ~6/min, so 10/min
# leaves headroom while still cutting off a misbehaving script. The submit
# endpoint is tighter — most suppliers POST once, twice at most.
_CONTEXT_RATE_CAPACITY = 10
_CONTEXT_RATE_PER_SECONDS = 60

_RESPOND_RATE_CAPACITY = 5
_RESPOND_RATE_PER_SECONDS = 60


def _enforce_rate_limit(token: str, *, capacity: int, per_seconds: int) -> None:
    """Raise 429 if the per-token bucket is empty.

    Keys on the raw token (which `check_and_consume` hashes internally) so
    each `(rfq, supplier)` link has its own bucket — a single supplier
    can't have one mistake (a refresh loop on context) starve their own
    submit budget, and one supplier's misbehaviour can't deny other
    suppliers their turns.
    """
    if not check_and_consume(token, capacity=capacity, per_seconds=per_seconds):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Rate limit exceeded — please slow down and retry shortly.",
            headers={"Retry-After": str(per_seconds)},
        )


def _verify_or_401(token: str) -> RfqTokenClaims:
    try:
        return verify_response_token(token)
    except TokenError as exc:
        # Generic 401 — don't leak which check failed (expired vs. signature
        # vs. wrong audience). A supplier who lost their link clicks
        # "request resend" upstream; nothing here gates on the reason.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired link") from exc


def _find_supplier_slot(rfq: Rfq, supplier_id: UUID) -> dict | None:
    """Return the existing per-supplier dict in `rfq.responses` or None.

    The dispatcher writes one entry per `sent_to` supplier; if for some
    reason the slot is missing we'll create it on submit, but the
    context endpoint just shows "pending" as if the dispatcher hadn't
    run yet — the supplier doesn't need to know.
    """
    for entry in rfq.responses or []:
        if isinstance(entry, dict) and str(entry.get("supplier_id")) == str(supplier_id):
            return entry
    return None


@router.get("/context")
async def get_rfq_context(
    t: Annotated[str, Query(description="Signed token from the RFQ email")],
) -> dict:
    # Apply rate limit BEFORE verifying the token. A garbage token still
    # spends a verify_jwt CPU cycle, so flood-protection has to gate
    # earlier than auth. The bucket is keyed on the raw `?t=` value, so
    # a brute-force attack against guessed tokens still hits its own
    # bucket per attempt.
    _enforce_rate_limit(t, capacity=_CONTEXT_RATE_CAPACITY, per_seconds=_CONTEXT_RATE_PER_SECONDS)
    claims = _verify_or_401(t)

    async with AdminSessionFactory() as session:
        rfq = (await session.execute(select(Rfq).where(Rfq.id == claims.rfq_id))).scalar_one_or_none()
        if rfq is None:
            # Token signature was valid (so we minted it) but the RFQ row
            # is gone — could be a delete or a misconfigured staging DB.
            # 404 lets the UI distinguish "your link is bad" (401) from
            # "this RFQ has been withdrawn" (404).
            raise HTTPException(status.HTTP_404_NOT_FOUND, "RFQ not found")

        if claims.supplier_id not in (rfq.sent_to or []):
            # Token claimed an RFQ that this supplier wasn't sent to —
            # shouldn't happen unless someone hand-edits a token, but
            # treat it as an auth failure to keep the surface tight.
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token not valid for this RFQ")

        org = (
            await session.execute(select(Organization).where(Organization.id == rfq.organization_id))
        ).scalar_one_or_none()
        if org is None:  # pragma: no cover — orphaned RFQ rows shouldn't exist
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")

        project_name = None
        if rfq.project_id:
            project = (await session.execute(select(Project).where(Project.id == rfq.project_id))).scalar_one_or_none()
            project_name = project.name if project else None

        estimate_name = None
        boq_digest: list[PublicBoqLine] = []
        if rfq.estimate_id:
            estimate = (
                await session.execute(select(Estimate).where(Estimate.id == rfq.estimate_id))
            ).scalar_one_or_none()
            if estimate is not None:
                estimate_name = estimate.name
                lines = (
                    (
                        await session.execute(
                            select(BoqItem)
                            .where(BoqItem.estimate_id == estimate.id)
                            .order_by(BoqItem.sort_order)
                            .limit(_MAX_BOQ_DIGEST_LINES)
                        )
                    )
                    .scalars()
                    .all()
                )
                boq_digest = [
                    PublicBoqLine(
                        description=line.description or "",
                        material_code=line.material_code,
                        quantity=float(line.quantity) if line.quantity is not None else None,
                        unit=line.unit,
                    )
                    for line in lines
                ]

        slot = _find_supplier_slot(rfq, claims.supplier_id)
        submitted_quote = (slot or {}).get("quote") if slot else None
        submission_status = "submitted" if submitted_quote else "pending"

    context = PublicRfqContext(
        organization_name=org.name,
        project_name=project_name,
        estimate_name=estimate_name,
        deadline=rfq.deadline,
        message=None,  # `message` isn't on the Rfq model today; reserved for the future.
        boq_digest=boq_digest,
        submission_status=cast("Literal['pending', 'submitted']", submission_status),
        submitted_quote=submitted_quote,
    )
    return ok(context.model_dump(mode="json"))


@router.post("/respond")
async def submit_rfq_response(
    quote: PublicRfqQuote,
    t: Annotated[str, Query(description="Signed token from the RFQ email")],
) -> dict:
    _enforce_rate_limit(t, capacity=_RESPOND_RATE_CAPACITY, per_seconds=_RESPOND_RATE_PER_SECONDS)
    claims = _verify_or_401(t)

    async with AdminSessionFactory() as session:
        rfq = (await session.execute(select(Rfq).where(Rfq.id == claims.rfq_id))).scalar_one_or_none()
        if rfq is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "RFQ not found")

        if claims.supplier_id not in (rfq.sent_to or []):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token not valid for this RFQ")

        # Confirm the supplier is still visible to the buyer's tenant.
        # Since AdminSessionFactory bypasses RLS, the FK already holds; we
        # just want a sanity check that the supplier hasn't been hard-
        # deleted between dispatch and response.
        supplier = (
            await session.execute(select(Supplier).where(Supplier.id == claims.supplier_id))
        ).scalar_one_or_none()
        if supplier is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier no longer exists")

        responses = list(rfq.responses or [])
        slot_index: int | None = None
        for i, entry in enumerate(responses):
            if isinstance(entry, dict) and str(entry.get("supplier_id")) == str(claims.supplier_id):
                slot_index = i
                break

        now_iso = datetime.now(UTC).isoformat()
        quote_payload = quote.model_dump(mode="json")
        if slot_index is None:
            # Dispatcher didn't write a slot (e.g. dispatch hadn't run
            # yet, or supplier was added later). Create one in-place so
            # the dashboard sees the response.
            responses.append(
                {
                    "supplier_id": str(claims.supplier_id),
                    "status": "responded",
                    "responded_at": now_iso,
                    "quote": quote_payload,
                }
            )
        else:
            entry = dict(responses[slot_index])
            entry["status"] = "responded"
            entry["responded_at"] = now_iso
            entry["quote"] = quote_payload
            responses[slot_index] = entry

        rfq.responses = responses
        flag_modified(rfq, "responses")
        # Buyer-side state machine: as soon as any supplier responds, the
        # RFQ is no longer "sent" but "responded". We don't roll back to
        # "sent" if a response is later overwritten — once any quote
        # exists, the dashboard treats this RFQ as live.
        if rfq.status in (None, "draft", "sent"):
            rfq.status = "responded"

        await session.commit()

    logger.info(
        "public_rfq.submit rfq_id=%s supplier_id=%s",
        claims.rfq_id,
        claims.supplier_id,
    )
    return ok({"status": "received"})
