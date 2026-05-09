"""Dispatch an RFQ to its selected suppliers.

Loads the RFQ inside a TenantAwareSession, renders a per-supplier email with
a short BOQ digest from the linked estimate, and delegates transport to
`services.mailer`. Records each attempt back on `rfqs.responses` so the UI can
show dispatch state before any supplier has quoted.

Responses shape (per-supplier entry):
    {
      "supplier_id": "<uuid>",
      "status": "dispatched" | "bounced" | "skipped",
      "dispatched_at": "<iso8601>",
      "delivery": {"to": "...", "subject": "...", "delivered": bool, "reason": str|None},
      "quote": null
    }
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select

from db.session import TenantAwareSession
from models.costpulse import BoqItem, Estimate, Rfq, Supplier
from services.mailer import send_mail
from services.rfq_tokens import build_response_url

logger = logging.getLogger(__name__)

_MAX_BOQ_LINES = 15

# Transport-retry knobs. Three attempts is enough to ride out a transient
# SMTP blip without holding up the worker; linear-1s backoff keeps the
# total worst-case under 4s so the dispatcher coroutine doesn't starve
# its arq concurrency budget.
_MAX_SEND_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0

# Slot statuses that indicate the supplier has already been served by a
# prior dispatch pass and must NOT be re-emailed on a re-enqueue.
# `bounced` is intentionally NOT in this set — those are the retry
# candidates the hourly cron picks up.
_TERMINAL_SLOT_STATUSES = frozenset({"dispatched", "responded"})


async def _send_with_retry(*, to: str, subject: str, text_body: str, html_body: str | None = None) -> tuple[dict, int]:
    """Send with up to `_MAX_SEND_ATTEMPTS` retries on transient transport errors.

    Returns `(last_delivery_dict, attempts_made)`. The `delivery` dict is
    whatever `send_mail` returned for the attempt we stopped on — i.e. the
    successful one if any attempt delivered, otherwise the last failure.

    Short-circuit cases (return after attempt 1, no backoff):
      * `smtp_not_configured` — config issue, retry won't help.
      * `delivered=True` — obvious win.

    Otherwise we sleep `_BACKOFF_BASE_SECONDS * attempt` between tries
    (linear backoff — 1s, 2s — total ~3s in the worst case).
    """
    last_delivery: dict | None = None
    for attempt in range(1, _MAX_SEND_ATTEMPTS + 1):
        last_delivery = await send_mail(to=to, subject=subject, text_body=text_body, html_body=html_body)
        if last_delivery["delivered"]:
            return last_delivery, attempt
        reason = last_delivery.get("reason") or ""
        if reason == "smtp_not_configured":
            logger.info(
                "rfq_dispatch._send_with_retry no_retry to=%s reason=%s",
                to,
                reason,
            )
            return last_delivery, attempt
        if attempt < _MAX_SEND_ATTEMPTS:
            await asyncio.sleep(_BACKOFF_BASE_SECONDS * attempt)
    # All attempts exhausted — return the last failure.
    assert last_delivery is not None  # loop ran at least once
    return last_delivery, _MAX_SEND_ATTEMPTS


async def dispatch_rfq(*, organization_id: UUID, rfq_id: UUID) -> dict:
    """Best-effort dispatch. Never raises: returns a summary for the worker to log."""
    async with TenantAwareSession(organization_id) as session:
        rfq = (await session.execute(select(Rfq).where(Rfq.id == rfq_id))).scalar_one_or_none()
        if rfq is None:
            logger.warning("rfq_dispatch.missing rfq_id=%s", rfq_id)
            return {"rfq_id": str(rfq_id), "dispatched": 0, "skipped": 0, "reason": "not_found"}

        estimate = None
        boq_digest = ""
        if rfq.estimate_id:
            estimate = (
                await session.execute(select(Estimate).where(Estimate.id == rfq.estimate_id))
            ).scalar_one_or_none()
            if estimate is not None:
                lines = (
                    (
                        await session.execute(
                            select(BoqItem)
                            .where(BoqItem.estimate_id == estimate.id)
                            .order_by(BoqItem.sort_order)
                            .limit(_MAX_BOQ_LINES)
                        )
                    )
                    .scalars()
                    .all()
                )
                boq_digest = _format_boq_digest(lines)

        supplier_ids = list(rfq.sent_to or [])
        suppliers = (
            (await session.execute(select(Supplier).where(Supplier.id.in_(supplier_ids)))).scalars().all()
            if supplier_ids
            else []
        )
        by_id: dict[UUID, Supplier] = {s.id: s for s in suppliers}

        existing: list[dict] = list(rfq.responses or [])
        existing_by_supplier = {str(e.get("supplier_id")): e for e in existing if isinstance(e, dict)}

        dispatched = 0
        skipped = 0
        for sid in supplier_ids:
            supplier = by_id.get(sid)
            entry = existing_by_supplier.get(
                str(sid),
                {
                    "supplier_id": str(sid),
                    "quote": None,
                },
            )

            # Idempotency: skip slots already in a terminal state. A re-enqueue
            # of dispatch (e.g. the hourly bounced-retry cron picking up a
            # sibling slot) must NOT re-email a supplier who's already been
            # served or has already submitted a quote.
            if entry.get("status") in _TERMINAL_SLOT_STATUSES:
                existing_by_supplier[str(sid)] = entry
                continue

            if supplier is None:
                entry.update(
                    {
                        "status": "skipped",
                        "delivery": {"delivered": False, "reason": "supplier_not_visible"},
                    }
                )
                existing_by_supplier[str(sid)] = entry
                skipped += 1
                continue

            email = (supplier.contact or {}).get("email")
            if not email:
                entry.update(
                    {
                        "status": "skipped",
                        "delivery": {"delivered": False, "reason": "no_email_on_file"},
                    }
                )
                existing_by_supplier[str(sid)] = entry
                skipped += 1
                continue

            response_url = build_response_url(rfq_id=rfq.id, supplier_id=supplier.id)
            subject, body = _render(
                rfq=rfq,
                estimate=estimate,
                supplier=supplier,
                boq_digest=boq_digest,
                response_url=response_url,
            )
            delivery, attempts = await _send_with_retry(to=email, subject=subject, text_body=body)
            # Carry forward the `attempts` counter from any prior pass (e.g.
            # the slot was `bounced` from a previous run) so we have a true
            # running total of mail-server hits per supplier.
            prior_attempts = int(entry.get("attempts", 0) or 0)
            entry.update(
                {
                    "status": "dispatched" if delivery["delivered"] else "bounced",
                    "dispatched_at": delivery["dispatched_at"],
                    "attempts": prior_attempts + attempts,
                    "delivery": {
                        "to": delivery["to"],
                        "subject": delivery["subject"],
                        "delivered": delivery["delivered"],
                        "reason": delivery["reason"],
                    },
                }
            )
            existing_by_supplier[str(sid)] = entry
            if delivery["delivered"]:
                dispatched += 1
            else:
                skipped += 1

        rfq.responses = list(existing_by_supplier.values())
        # Flag SQLAlchemy that the mutable JSONB list changed.
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(rfq, "responses")
        rfq.status = "sent" if dispatched else (rfq.status or "draft")

    logger.info(
        "rfq_dispatch.done rfq_id=%s dispatched=%d skipped=%d",
        rfq_id,
        dispatched,
        skipped,
    )
    return {
        "rfq_id": str(rfq_id),
        "dispatched": dispatched,
        "skipped": skipped,
    }


def _format_boq_digest(items: list[BoqItem]) -> str:
    if not items:
        return "(estimate had no BOQ items)"
    lines = []
    for i in items:
        qty = f"{i.quantity}" if i.quantity is not None else "?"
        unit = i.unit or ""
        code = f"[{i.material_code}] " if i.material_code else ""
        lines.append(f"  - {code}{i.description} — {qty} {unit}".rstrip())
    return "\n".join(lines)


def _render(
    *,
    rfq: Rfq,
    estimate: Estimate | None,
    supplier: Supplier,
    boq_digest: str,
    response_url: str,
) -> tuple[str, str]:
    deadline = rfq.deadline.isoformat() if rfq.deadline else "at your earliest convenience"
    estimate_name = estimate.name if estimate else "(no linked estimate)"
    subject = f"RFQ — {estimate_name} (deadline {deadline})"
    body = (
        f"Xin chào {supplier.name},\n\n"
        f"We would like to request a quotation for the following project scope:\n\n"
        f"Estimate: {estimate_name}\n"
        f"RFQ ID:   {rfq.id}\n"
        f"Deadline: {deadline}\n\n"
        f"Indicative scope:\n{boq_digest}\n\n"
        f"To submit your quote, please use the secure response form:\n"
        f"{response_url}\n\n"
        f"The link is unique to your company and expires after the deadline. "
        f"You can also reply to this email if you prefer.\n\n"
        f"Thank you,\nAEC Platform — RFQ Bot\n"
    )
    return subject, body
